/**
 * useJobEvents — SSE 구독 + 폴백 폴링 훅 (T109, US2)
 *
 * 책임:
 *   1. `/api/v1/jobs/{id}/events` 에 EventSource 로 구독한다.
 *   2. 각 이벤트(`job.state_changed` / `job.progress` / `job.info` / `job.completed` / `job.failed`)
 *      를 JobEvent 로 정규화해 buffer 에 누적한다.
 *   3. EventSource 가 실패한 경우 5초 폴링 폴백으로 `GET /api/v1/jobs/{id}` 를 호출한다.
 *   4. 외부 콜백(onEvent) 을 통해 TanStack Query cache 등으로 partial update 를 전달한다.
 *
 * Last-Event-ID 는 표준 EventSource 가 자동 헤더에 실어 보내므로 별도 처리 불필요.
 *
 * 헌법 V — 한국어 주석.
 */
'use client';
import * as React from 'react';
import type { components } from '@/lib/api/types.gen';
import type { JobEvent as UiJobEvent } from '@/components/stage-progress/StageLog';

export type Job = components['schemas']['Job'];
export type JobStatus = components['schemas']['JobStatus'];

export type ConnectionState = 'connecting' | 'open' | 'closed' | 'error' | 'polling';

/** SSE 원시 payload 의 partial schema — contracts/events.md 참조. */
export interface RawEventPayload {
  job_id?: string;
  event_id?: string | number;
  seq?: number;
  previous_status?: JobStatus | null;
  status?: JobStatus | null;
  stage?: string | null;
  progress?: number | null;
  detail?: Record<string, unknown> | null;
  at?: string | null;
  published_at?: string | null;
  // job.failed
  error_stage?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  // job.info
  code?: string | null;
  message?: string | null;
  // job.completed
  completed_at?: string | null;
  assets?: Record<string, string> | null;
}

/** detail 객체를 한국어 텍스트로 가공한다 (StageLog 표시용). */
function summarizeDetail(stage: string | null | undefined, detail: Record<string, unknown> | null | undefined): string | null {
  if (!detail) return null;
  if (stage === 'translating') {
    const idx = detail.chunk_index;
    const total = detail.chunk_total;
    if (typeof idx === 'number' && typeof total === 'number') {
      return `청크 ${idx}/${total} 진행 중`;
    }
  }
  if (stage === 'downloading') {
    const got = detail.downloaded_bytes;
    const total = detail.total_bytes;
    if (typeof got === 'number') {
      const mb = (got / (1024 * 1024)).toFixed(1);
      if (typeof total === 'number' && total > 0) {
        const pct = Math.floor((got / total) * 100);
        return `다운로드 ${mb} MB (${pct}%)`;
      }
      return `다운로드 ${mb} MB`;
    }
  }
  if (stage === 'subtitle_processing') {
    const count = detail.cue_count;
    if (typeof count === 'number') return `자막 ${count} cues 추출`;
  }
  if (stage === 'rendering') {
    const fmt = detail.format;
    if (typeof fmt === 'string') return `포맷 ${fmt}`;
  }
  return null;
}

/** 원시 SSE 이벤트 → UI 용 JobEvent. */
export function normalizeEvent(
  type: UiJobEvent['type'],
  sseId: string,
  payload: RawEventPayload,
): UiJobEvent {
  const at = payload.at ?? payload.published_at ?? payload.completed_at ?? new Date().toISOString();
  const stage = payload.stage ?? payload.status ?? null;
  let detailText: string | null = null;
  if (type === 'job.progress') {
    detailText = summarizeDetail(stage, payload.detail ?? null);
  } else if (type === 'job.state_changed') {
    detailText = `진입 — ${stage ?? ''}`;
  } else if (type === 'job.failed') {
    detailText = payload.error_message ?? null;
  } else if (type === 'job.completed') {
    detailText = '재생 가능';
  } else if (type === 'job.info') {
    detailText = payload.message ?? null;
  }
  return {
    event_id: String(payload.event_id ?? sseId),
    type,
    at,
    stage: (stage as UiJobEvent['stage']) ?? null,
    status: (payload.status as JobStatus) ?? null,
    detail: detailText,
    progress: payload.progress ?? null,
  };
}

export interface UseJobEventsOptions {
  /**
   * 각 이벤트 수신 시 호출되는 콜백. TanStack Query cache 업데이트 등에 사용.
   * normalized JobEvent + raw payload 을 함께 넘긴다.
   */
  onEvent?: (event: UiJobEvent, raw: RawEventPayload) => void;
  /** Job snapshot (폴링 폴백 결과 또는 query cache). */
  onSnapshot?: (job: Job) => void;
  /** 활성/비활성 토글 — false 면 connection 을 열지 않는다. */
  enabled?: boolean;
  /** 폴백 폴링 주기 (ms). 기본 5000. */
  pollIntervalMs?: number;
}

export interface UseJobEventsResult {
  events: UiJobEvent[];
  latestEvent: UiJobEvent | null;
  connectionState: ConnectionState;
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? '/api/v1';

const SSE_EVENT_TYPES: ReadonlyArray<UiJobEvent['type']> = [
  'job.state_changed',
  'job.progress',
  'job.info',
  'job.completed',
  'job.failed',
];

/**
 * 작업 SSE 이벤트 구독 훅.
 *
 * 종결 이벤트(job.completed / job.failed) 수신 시 EventSource 를 명시적으로 닫는다.
 * EventSource open 실패 / error 시에는 폴링 폴백으로 전환한다.
 */
export function useJobEvents(
  jobId: string | null | undefined,
  options: UseJobEventsOptions = {},
): UseJobEventsResult {
  const { onEvent, onSnapshot, enabled = true, pollIntervalMs = 5000 } = options;

  // 최신 콜백 참조 유지 — effect 의존성을 안정화
  const onEventRef = React.useRef(onEvent);
  const onSnapshotRef = React.useRef(onSnapshot);
  React.useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);
  React.useEffect(() => {
    onSnapshotRef.current = onSnapshot;
  }, [onSnapshot]);

  const [events, setEvents] = React.useState<UiJobEvent[]>([]);
  const [connectionState, setConnectionState] = React.useState<ConnectionState>('connecting');

  const appendEvent = React.useCallback((ev: UiJobEvent, raw: RawEventPayload) => {
    setEvents((prev) => {
      // event_id 중복 방지 (재연결 시 replay 와 신규 stream 의 경계).
      if (prev.some((e) => e.event_id === ev.event_id)) return prev;
      return [...prev, ev];
    });
    onEventRef.current?.(ev, raw);
  }, []);

  React.useEffect(() => {
    if (!enabled || !jobId) {
      setConnectionState('closed');
      return;
    }

    // jobId/enabled 가 바뀔 때 이전 작업의 이벤트 버퍼를 비운다 — 페이지 전환 시 잔여 표시 방지.
    setEvents([]);
    setConnectionState('connecting');

    let closed = false;
    let es: EventSource | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    // ── 폴링 폴백 ──────────────────────────────────────────────
    function startPolling() {
      if (closed || pollTimer) return;
      setConnectionState('polling');
      const tick = async () => {
        if (closed) return;
        try {
          const res = await fetch(`${API_BASE}/jobs/${jobId}`, {
            headers: { 'content-type': 'application/json' },
          });
          if (!res.ok) return;
          const body = (await res.json()) as { success: boolean; data?: Job };
          if (body.success && body.data) {
            onSnapshotRef.current?.(body.data);
            // 폴링으로 종결 상태 감지 시 폴링 정지.
            if (body.data.status === 'completed' || body.data.status === 'failed') {
              if (pollTimer) {
                clearInterval(pollTimer);
                pollTimer = null;
              }
              setConnectionState('closed');
            }
          }
        } catch {
          // 네트워크 일시 실패는 다음 tick 에서 재시도.
        }
      };
      void tick();
      pollTimer = setInterval(() => void tick(), pollIntervalMs);
    }

    // ── EventSource 구독 ───────────────────────────────────────
    try {
      es = new EventSource(`${API_BASE}/jobs/${jobId}/events`);
    } catch {
      startPolling();
      return () => {
        closed = true;
        if (pollTimer) clearInterval(pollTimer);
      };
    }

    es.onopen = () => {
      if (closed) return;
      setConnectionState('open');
    };

    const handleEvent = (type: UiJobEvent['type']) => (msg: MessageEvent<string>) => {
      if (closed) return;
      try {
        const raw = JSON.parse(msg.data) as RawEventPayload;
        const normalized = normalizeEvent(type, msg.lastEventId ?? '', raw);
        appendEvent(normalized, raw);

        // 종결 이벤트 수신 시 connection 정리.
        if (type === 'job.completed' || type === 'job.failed') {
          es?.close();
          setConnectionState('closed');
        }
      } catch {
        // payload 파싱 실패는 무시 (서버가 contract 어김).
      }
    };

    for (const t of SSE_EVENT_TYPES) {
      es.addEventListener(t, handleEvent(t) as EventListener);
    }

    es.onerror = () => {
      if (closed) return;
      // EventSource 는 자체적으로 재연결하지만, readyState===CLOSED 면 폴링으로 전환.
      if (!es || es.readyState === EventSource.CLOSED) {
        setConnectionState('error');
        startPolling();
      } else {
        setConnectionState('connecting');
      }
    };

    return () => {
      closed = true;
      es?.close();
      es = null;
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    };
  }, [enabled, jobId, pollIntervalMs, appendEvent]);

  const latestEvent = events.length > 0 ? events[events.length - 1]! : null;

  return { events, latestEvent, connectionState };
}
