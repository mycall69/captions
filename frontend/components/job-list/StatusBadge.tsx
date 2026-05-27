/**
 * StatusBadge — 작업 상태 7-variant 배지 (T104, US2)
 *
 * 와이어프레임 §S1 / §S2 참조:
 *   pending / downloading / subtitle_processing / translating / rendering / completed / failed
 *
 * 헌법 V — 사용자 노출 텍스트는 한국어. 식별자(JobStatus)는 영문 토큰 그대로 유지.
 *
 * 자동 자막 출처 배지(`AutoSubtitleBadge`)도 본 모듈에서 함께 노출 — 와이어프레임 S3 헤더의
 * "🤖 자동 자막 기반" 표시(FR-021a, Edge Case 사용자 품질 인지).
 */
import * as React from 'react';
import { cn } from '@/lib/utils';
import type { components } from '@/lib/api/types.gen';
import { STATUS_BADGE_LABEL_KO } from '@/lib/i18n/jobLabels';

export type JobStatus = components['schemas']['JobStatus'];

interface StatusBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  status: JobStatus;
}

// 시각 토큰 — 각 status 가 서로 다른 className 시그니처를 갖도록 분리한다.
// data-status 속성으로도 식별 가능 (테스트 / 디버깅 / e2e 친화).
const STATUS_STYLE: Record<JobStatus, string> = {
  pending: 'bg-muted text-muted-foreground border-border',
  downloading: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  subtitle_processing: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30',
  translating: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
  rendering: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  completed: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  failed: 'bg-destructive/15 text-destructive border-destructive/30',
};

// 시각 큐(icon) — 단순 unicode 마커. 디자인 단계에서 lucide 아이콘으로 교체 가능.
const STATUS_ICON: Record<JobStatus, string> = {
  pending: '·',
  downloading: '↓',
  subtitle_processing: '✎',
  translating: '⤴',
  rendering: '⚙',
  completed: '✓',
  failed: '✕',
};

export function StatusBadge({ status, className, ...rest }: StatusBadgeProps) {
  const label = STATUS_BADGE_LABEL_KO[status];
  // role="status" / aria-label 은 가시 텍스트가 이미 동일 정보를 전달하므로 제거.
  // (목록에 다수 배치될 때 polite live region 으로 동작하는 부작용을 막는다.)
  return (
    <span
      data-status={status}
      data-testid="status-badge"
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium',
        STATUS_STYLE[status],
        className,
      )}
      {...rest}
    >
      <span aria-hidden className="font-bold">
        {STATUS_ICON[status]}
      </span>
      <span>{label}</span>
    </span>
  );
}

/**
 * 자동 자막 출처 배지 — VideoMetadata.subtitle_source === 'auto' 일 때 헤더에 노출.
 * S3 와이어프레임 § 자동 자막 출처일 때 명시.
 */
export function AutoSubtitleBadge({ className }: { className?: string }) {
  return (
    <span
      data-testid="auto-subtitle-badge"
      className={cn(
        'inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground',
        className,
      )}
    >
      <span aria-hidden>🤖</span>
      <span>자동 자막 기반</span>
    </span>
  );
}
