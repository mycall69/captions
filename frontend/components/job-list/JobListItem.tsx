/**
 * JobListItem — S1 최근 작업 카드 1행 (T116, US3)
 *
 * 와이어프레임 §S1 §최근 작업 카드 참조:
 *   - 좌측 썸네일(MVP: 단순 placeholder — YouTube 썸네일 URL 사용 안 함)
 *   - 중앙: 제목 · 채널 · 길이(mm:ss) · 자막 출처
 *   - 우측: StatusBadge + 상태별 액션 버튼
 *       completed → "재생" (S3, /jobs/:id)
 *       in-progress (pending/downloading/subtitle_processing/translating/rendering) → "상태 보기" (S2)
 *       failed     → "다시 시도" (현재는 S2 로 이동해 실패 패널 표시; FR-004 의 재요청은 후속)
 *
 * 헌법 V — 모든 사용자 노출 텍스트는 한국어.
 */
'use client';
import * as React from 'react';
import { useRouter } from 'next/navigation';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { StatusBadge } from '@/components/job-list/StatusBadge';
import type { components } from '@/lib/api/types.gen';
import { STAGE_LABEL_KO } from '@/lib/i18n/jobLabels';

export type Job = components['schemas']['Job'];

interface JobListItemProps {
  job: Job;
  className?: string;
}

const TERMINAL_COMPLETED: Job['status'] = 'completed';
const TERMINAL_FAILED: Job['status'] = 'failed';

function formatDuration(sec: number | null | undefined): string {
  if (typeof sec !== 'number' || sec <= 0 || Number.isNaN(sec)) return '—';
  const total = Math.floor(sec);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, '0');
  const ss = String(s).padStart(2, '0');
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}

export function JobListItem({ job, className }: JobListItemProps) {
  const router = useRouter();
  const title = job.metadata.title ?? job.youtube_video_id;
  const channel = job.metadata.channel ?? '';
  const duration = formatDuration(job.metadata.duration_sec ?? null);
  const isCompleted = job.status === TERMINAL_COMPLETED;
  const isFailed = job.status === TERMINAL_FAILED;
  const isInProgress = !isCompleted && !isFailed;

  const subtitleSourceLabel =
    job.metadata.subtitle_source === 'manual'
      ? '수동 자막'
      : job.metadata.subtitle_source === 'auto'
        ? '자동 자막'
        : null;

  // 현재 단계 라벨 — 진행 중 카드에 안내 텍스트로 함께 노출한다.
  const stageLabel = STAGE_LABEL_KO[job.status];

  // CTA 라벨 / 핸들러 — variant 별 정책.
  const cta = isCompleted
    ? { label: '재생', variant: 'default' as const }
    : isFailed
      ? { label: '다시 시도', variant: 'outline' as const }
      : { label: '상태 보기', variant: 'secondary' as const };

  const handleClick = () => {
    router.push(`/jobs/${job.id}`);
  };

  return (
    <li
      data-testid="job-list-item"
      data-job-id={job.id}
      data-status={job.status}
      className={cn(
        'flex items-center gap-4 rounded-lg border border-border bg-card p-4 shadow-sm',
        className,
      )}
    >
      {/* 좌측 썸네일 placeholder — 디자인 단계에서 실제 이미지로 교체 가능 */}
      <div
        aria-hidden
        className="flex h-16 w-24 flex-none items-center justify-center rounded-md bg-muted text-muted-foreground"
      >
        <span className="text-xl">▶</span>
      </div>

      <div className="min-w-0 flex-1">
        <div className="truncate text-base font-semibold text-foreground">{title}</div>
        <div className="mt-1 truncate text-sm text-muted-foreground">
          {channel && <span>{channel}</span>}
          {channel && <span className="mx-1">·</span>}
          <span>{duration}</span>
          {subtitleSourceLabel && (
            <>
              <span className="mx-1">·</span>
              <span>{subtitleSourceLabel}</span>
            </>
          )}
        </div>
        {isInProgress && (
          <div className="mt-1 text-xs text-muted-foreground">
            진행 단계: <span className="font-medium">{stageLabel}</span>
            {typeof job.progress === 'number' && job.progress > 0 && (
              <span className="ml-2">{Math.round(job.progress * 100)}%</span>
            )}
          </div>
        )}
        {isFailed && job.error_message && (
          <div className="mt-1 truncate text-xs text-destructive">
            실패 사유: {job.error_message}
          </div>
        )}
      </div>

      <div className="flex flex-none items-center gap-3">
        <StatusBadge status={job.status} />
        <Button variant={cta.variant} size="sm" onClick={handleClick}>
          {cta.label}
        </Button>
      </div>
    </li>
  );
}
