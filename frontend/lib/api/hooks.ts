/**
 * lib/api/hooks.ts — TanStack Query 훅 + SSE → cache merge (T110, T118, US2/US3)
 *
 * 책임:
 *   1. `useJob(jobId)` — `GET /v1/jobs/{id}` 를 TanStack Query 로 캐싱.
 *   2. `useJobWithEvents(jobId)` — SSE 이벤트를 partial setQueryData 로 머지하여
 *      `useJob` 캐시를 페이지 리로드 없이 갱신.
 *   3. `useRecentJobs(...)` — `GET /v1/jobs` 최근 작업 목록 (US3).
 *
 * 헌법 V — 한국어 주석.
 */
'use client';
import * as React from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api/client';
import type { components } from '@/lib/api/types.gen';
import { useJobEvents, type RawEventPayload } from '@/lib/sse';
import type { JobEvent as UiJobEvent } from '@/components/stage-progress/StageLog';

export type Job = components['schemas']['Job'];
export type JobStatus = components['schemas']['JobStatus'];

/** GET /v1/jobs 응답 data 형태 (openapi.yaml §JobListEnvelope.data). */
export interface JobListData {
  items: Job[];
  next_cursor: string | null;
}

export function jobQueryKey(jobId: string): ['job', string] {
  return ['job', jobId];
}

/** GET /v1/jobs/{id} — 표준 단건 조회. */
export function useJob(jobId: string | null | undefined) {
  return useQuery({
    queryKey: jobId ? jobQueryKey(jobId) : ['job', ''],
    queryFn: async () => {
      // enabled: Boolean(jobId) 로 호출이 차단되지만, 타입 narrow 를 위해 명시 가드.
      if (!jobId) throw new Error('jobId required');
      return apiFetch<Job>(`/jobs/${jobId}`);
    },
    enabled: Boolean(jobId),
    // 진행 중인 작업은 SSE 가 갱신을 책임지므로 refetch 비활성화.
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    staleTime: 30_000,
  });
}

/**
 * SSE 이벤트 → Job partial merge.
 * - job.state_changed → status, progress=0 으로 리셋
 * - job.progress      → progress 갱신
 * - job.failed        → status='failed' + error_* 필드
 * - job.completed     → status='completed' + completed_at
 *
 * old 가 없는 경우(첫 이벤트가 SSE 로 도착) 는 no-op (useJob 의 initial fetch 가 곧 채움).
 */
function mergeEvent(old: Job | undefined, ev: UiJobEvent, raw: RawEventPayload): Job | undefined {
  if (!old) return old;
  const next: Job = { ...old };
  let changed = false;

  if (ev.type === 'job.state_changed') {
    if (raw.status && raw.status !== next.status) {
      next.status = raw.status;
      next.progress = 0;
      changed = true;
    }
  } else if (ev.type === 'job.progress') {
    if (typeof raw.progress === 'number' && raw.progress !== next.progress) {
      next.progress = raw.progress;
      changed = true;
    }
    // progress 이벤트의 stage 가 현재 status 와 다르면 status 도 동기화 (안전망).
    if (raw.status && raw.status !== next.status) {
      next.status = raw.status;
      changed = true;
    }
  } else if (ev.type === 'job.failed') {
    next.status = 'failed';
    next.error_stage = raw.error_stage ?? null;
    next.error_code = raw.error_code ?? null;
    next.error_message = raw.error_message ?? null;
    next.updated_at = raw.at ?? next.updated_at;
    changed = true;
  } else if (ev.type === 'job.completed') {
    next.status = 'completed';
    next.completed_at = raw.completed_at ?? raw.at ?? next.updated_at;
    next.updated_at = raw.at ?? next.updated_at;
    changed = true;
  }

  return changed ? next : old;
}

/**
 * useJob + useJobEvents 통합 훅.
 *
 * 반환: { job, events, latestEvent, connectionState, error, isLoading }
 *
 * SSE 이벤트 수신 시 TanStack Query cache (`['job', jobId]`) 를 partial 업데이트한다.
 * 페이지는 `useJob` 결과만 구독해도 자동으로 갱신된다.
 */
export function useJobWithEvents(jobId: string | null | undefined) {
  const queryClient = useQueryClient();
  const query = useJob(jobId);

  const handleEvent = React.useCallback(
    (ev: UiJobEvent, raw: RawEventPayload) => {
      if (!jobId) return;
      queryClient.setQueryData<Job>(jobQueryKey(jobId), (old) => mergeEvent(old, ev, raw));
    },
    [queryClient, jobId],
  );

  // 폴링 폴백이 가져온 snapshot 도 cache 에 반영.
  const handleSnapshot = React.useCallback(
    (snapshot: Job) => {
      if (!jobId) return;
      queryClient.setQueryData<Job>(jobQueryKey(jobId), snapshot);
    },
    [queryClient, jobId],
  );

  const { events, latestEvent, connectionState } = useJobEvents(jobId, {
    onEvent: handleEvent,
    onSnapshot: handleSnapshot,
    enabled: Boolean(jobId),
  });

  return {
    job: query.data,
    events,
    latestEvent,
    connectionState,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}

/**
 * useRecentJobs — `GET /v1/jobs` 최근 작업 목록 (T118, US3).
 *
 * 와이어프레임 §S1 — 메인 페이지 하단 "최근 작업" 카드에서 사용.
 *
 * 정책:
 *   - staleTime 10s — 잦은 재요청을 막되 탭 복귀 시 새로고침되도록 한다.
 *   - 진행 중 항목의 실시간 갱신은 페이지의 useJobWithEvents 가 담당한다
 *     (목록 자체는 SSE 구독을 열지 않고 stale 시간 + 사용자 액션으로 갱신).
 *   - status 필터는 반복 쿼리 파라미터로 전달한다 (openapi.yaml style=form, explode=true).
 *
 * @param options.limit 페이지 당 최대 항목 수 (1~50, 기본 5 — S1 카드 5건 기준).
 * @param options.status 상태 필터 — 단일 또는 복수.
 */
export function useRecentJobs(options?: {
  limit?: number;
  status?: JobStatus | JobStatus[];
}) {
  const limit = options?.limit ?? 5;
  const statuses: JobStatus[] | undefined = options?.status
    ? Array.isArray(options.status)
      ? options.status
      : [options.status]
    : undefined;

  return useQuery({
    queryKey: ['jobs', 'recent', limit, statuses ?? null] as const,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set('limit', String(limit));
      if (statuses) {
        for (const s of statuses) params.append('status', s);
      }
      return apiFetch<JobListData>(`/jobs?${params.toString()}`);
    },
    staleTime: 10_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });
}
