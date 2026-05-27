/**
 * StageLog — 단계별 타임라인 로그 (T106, US2)
 *
 * 와이어프레임 §S2 ── 단계별 로그 ──:
 *   ✓ pending                09:31:02  · 작업 접수
 *   ✓ downloading            09:31:04  · mp4 다운로드 완료 (38 MB)
 *   ✓ subtitle_processing    09:31:22  · 수동 ja 자막 추출 (143 cues)
 *   ⏳ translating           09:31:30  · 청크 12/26 진행 중
 *   · rendering
 *   · completed
 *
 * 입력: SSE 로 수신된 JobEvent 목록 (시간순). 본 컴포넌트는 표시만 담당하며 fetch / merge 는
 * 호출자(`useJobEvents`)에서 처리한다.
 *
 * 헌법 V — 한국어 라벨 / 한국어 주석.
 */
import * as React from 'react';
import { cn } from '@/lib/utils';
import type { JobStatus } from '@/components/job-list/StatusBadge';

/**
 * SSE 이벤트의 frontend-side normalized 표현.
 * contracts/events.md 의 `job.state_changed` / `job.progress` / `job.info` / `job.completed` /
 * `job.failed` 를 한 모양으로 합친다.
 */
export interface JobEvent {
  /** SSE id (job_event.id) */
  event_id: string;
  /** event 타입 */
  type:
    | 'job.state_changed'
    | 'job.progress'
    | 'job.info'
    | 'job.completed'
    | 'job.failed';
  /** ISO-8601 UTC timestamp */
  at: string;
  /** 관련 stage / status (job.info 등에서는 null 가능) */
  stage?: JobStatus | string | null;
  status?: JobStatus | null;
  /** 표시용 detail 문자열 (한국어). 호출자가 가공해서 넘긴다. */
  detail?: string | null;
  /** progress 0..1 */
  progress?: number | null;
}

interface StageLogProps {
  events: JobEvent[];
  className?: string;
}

// stage / status 의 한국어 라벨 — StageProgressBar / StatusBadge 와 일관.
const STAGE_LABEL: Record<string, string> = {
  pending: '대기',
  downloading: '다운로드',
  subtitle_processing: '자막 처리',
  translating: '번역',
  rendering: '렌더링',
  completed: '완료',
  failed: '실패',
};

// 시간 포맷 — HH:mm:ss (사용자 로케일).
function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleTimeString('ko-KR', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch {
    return iso;
  }
}

function eventMarker(ev: JobEvent): string {
  if (ev.type === 'job.failed') return '✕';
  if (ev.type === 'job.completed') return '✓';
  if (ev.type === 'job.state_changed') {
    // 종결 단계가 아니면 진입(current); completed 로의 전이는 완료(done) 마커
    if (ev.status === 'completed') return '✓';
    return '⏳';
  }
  if (ev.type === 'job.progress') return '·';
  return 'ℹ';
}

export function StageLog({ events, className }: StageLogProps) {
  if (events.length === 0) {
    return (
      <p
        data-testid="stage-log-empty"
        className={cn('text-sm text-muted-foreground', className)}
      >
        아직 기록된 이벤트가 없습니다.
      </p>
    );
  }

  return (
    <ol
      data-testid="stage-log"
      className={cn('space-y-1 font-mono text-sm', className)}
      aria-label="단계별 로그"
    >
      {events.map((ev) => {
        const stageKey = (ev.stage ?? ev.status ?? '') as string;
        const stageLabel = STAGE_LABEL[stageKey] ?? stageKey ?? '';
        return (
          <li
            key={ev.event_id}
            data-event-type={ev.type}
            data-stage={stageKey}
            className="flex items-baseline gap-2"
          >
            <span aria-hidden className="w-4 text-center text-base">
              {eventMarker(ev)}
            </span>
            <span className="w-32 truncate text-foreground">{stageLabel || stageKey}</span>
            <span className="w-20 text-muted-foreground">{formatTime(ev.at)}</span>
            {ev.detail ? (
              <span className="text-muted-foreground">· {ev.detail}</span>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
