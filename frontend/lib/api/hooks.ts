/**
 * lib/api/hooks.ts — TanStack Query 훅 + SSE → cache merge (T110, US2)
 *
 * 책임:
 *   1. `useJob(jobId)` — `GET /v1/jobs/{id}` 를 TanStack Query 로 캐싱.
 *   2. `useJobWithEvents(jobId)` — SSE 이벤트를 partial setQueryData 로 머지하여
 *      `useJob` 캐시를 페이지 리로드 없이 갱신.
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

export function jobQueryKey(jobId: string): ['job', string] {
  return ['job', jobId];
}

/** GET /v1/jobs/{id} — 표준 단건 조회. */
export function useJob(jobId: string | null | undefined) {
  return useQuery({
    queryKey: jobId ? jobQueryKey(jobId) : ['job', ''],
    queryFn: async () => apiFetch<Job>(`/jobs/${jobId}`),
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
