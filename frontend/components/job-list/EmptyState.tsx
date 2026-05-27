/**
 * EmptyState — S1 최근 작업 빈 상태 안내 (T117, US3)
 *
 * 와이어프레임 §C3 (S1 빈 상태):
 *   📺  아직 처리한 영상이 없습니다.
 *       위에 YouTube URL을 붙여넣고 시작해 보세요.
 *
 * 헌법 V — 모든 사용자 노출 텍스트는 한국어.
 */
import * as React from 'react';
import { cn } from '@/lib/utils';

interface EmptyStateProps {
  className?: string;
}

export function EmptyState({ className }: EmptyStateProps) {
  return (
    <div
      data-testid="recent-jobs-empty"
      role="status"
      className={cn(
        'flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-card/40 px-6 py-12 text-center',
        className,
      )}
    >
      <div aria-hidden className="text-3xl">
        📺
      </div>
      <p className="text-base font-medium text-foreground">아직 처리한 영상이 없습니다.</p>
      <p className="text-sm text-muted-foreground">
        위에 YouTube URL을 붙여넣고 시작해 보세요.
      </p>
    </div>
  );
}
