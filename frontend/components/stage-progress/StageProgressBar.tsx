/**
 * StageProgressBar — 6노드 단계 진행 인디케이터 (T105, US2)
 *
 * 와이어프레임 §S2 단계 진행:
 *   ●━━━━━●━━━━━●━━━━━◐━━━━━○━━━━━○
 *   대기   다운  자막  번역   렌더  완료
 *                       ↑ 현재
 *
 * 6노드 순서:
 *   pending → downloading → subtitle_processing → translating → rendering → completed
 *
 * 노드 상태(state):
 *   - done    : 이미 완료된 단계
 *   - current : 현재 진행 중 (회전 인디케이터)
 *   - future  : 아직 도달하지 않은 단계
 *   - error   : 실패가 발생한 단계 (status==='failed' + errorStage 일치)
 *
 * 헌법 V — 한국어 라벨 / 한국어 주석.
 */
import * as React from 'react';
import { cn } from '@/lib/utils';
import type { components } from '@/lib/api/types.gen';
import { STAGE_LABEL_KO } from '@/lib/i18n/jobLabels';

export type JobStatus = components['schemas']['JobStatus'];

// 6 노드 — 'failed' 는 별도 분기 (errorStage 표시)
type StageKey = Exclude<JobStatus, 'failed'>;

const NODE_ORDER: ReadonlyArray<StageKey> = [
  'pending',
  'downloading',
  'subtitle_processing',
  'translating',
  'rendering',
  'completed',
];

type NodeState = 'done' | 'current' | 'future' | 'error';

interface StageProgressBarProps {
  /** 현재 status. 'failed' 인 경우 errorStage 로 실패 단계를 식별한다. */
  status: JobStatus;
  /** 실패 단계 (status==='failed' 일 때만 유효). */
  errorStage?: string | null;
  /**
   * 현재 단계 내 진행률 (0..1). 제공되면 6노드 아래에 % 진행바를 함께 렌더한다.
   * status==='failed' 또는 'completed' 일 때는 표시하지 않는다.
   */
  progress?: number | null;
  className?: string;
}

function resolveNodeState(
  stage: StageKey,
  index: number,
  status: JobStatus,
  errorStage: string | null | undefined,
): NodeState {
  if (status === 'failed') {
    // 실패한 단계를 error 로 강조하고, 그 이전 단계는 done, 이후는 future.
    if (errorStage && errorStage === stage) return 'error';
    if (!errorStage) {
      // errorStage 가 없으면 모든 노드를 future 처리 (보수적).
      return 'future';
    }
    const errorIndex = NODE_ORDER.indexOf(errorStage as StageKey);
    if (errorIndex === -1) return 'future';
    if (index < errorIndex) return 'done';
    return 'future';
  }
  // completed → 모든 단계가 done
  if (status === 'completed') return 'done';
  const currentIndex = NODE_ORDER.indexOf(status as StageKey);
  if (currentIndex === -1) return 'future';
  if (index < currentIndex) return 'done';
  if (index === currentIndex) return 'current';
  return 'future';
}

// 상태별 스타일 — state-* 접두 클래스를 명시적으로 부여해 테스트에서 구분 가능.
const STATE_STYLE: Record<NodeState, string> = {
  done: 'state-done bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
  current: 'state-current bg-violet-500/20 text-violet-200 border-violet-500/50',
  future: 'state-future bg-muted text-muted-foreground border-border',
  error: 'state-error bg-destructive/20 text-destructive border-destructive/40',
};

export function StageProgressBar({
  status,
  errorStage,
  progress,
  className,
}: StageProgressBarProps) {
  // 진행률 바 렌더 가능 여부 — 종결 상태에서는 노출하지 않는다.
  const showProgress =
    typeof progress === 'number' && status !== 'failed' && status !== 'completed';
  const pct = showProgress ? Math.round((progress ?? 0) * 100) : 0;

  return (
    <div className={cn('space-y-3', className)}>
      <div
        data-testid="stage-progress-bar"
        className="flex w-full items-start justify-between gap-2"
        role="list"
        aria-label="작업 단계 진행"
      >
        {NODE_ORDER.map((stage, index) => {
          const state = resolveNodeState(stage, index, status, errorStage);
          const isLast = index === NODE_ORDER.length - 1;
          return (
            <React.Fragment key={stage}>
              <div
                data-stage={stage}
                data-state={state}
                data-testid="stage-node"
                role="listitem"
                aria-current={state === 'current' ? 'step' : undefined}
                className={cn(
                  'flex flex-1 min-w-0 flex-col items-center gap-1.5 stage-node',
                  `stage-${stage}`,
                  STATE_STYLE[state],
                  'rounded-md border px-2 py-2',
                )}
              >
                <div className="flex h-6 w-6 items-center justify-center">
                  {state === 'current' ? (
                    // 회전 인디케이터 — Tailwind animate-spin (CSS keyframes)
                    <span
                      aria-hidden
                      data-testid="stage-current-indicator"
                      className="inline-block h-4 w-4 rounded-full border-2 border-current border-t-transparent animate-spin"
                    />
                  ) : state === 'done' ? (
                    <span aria-hidden className="text-base font-bold">✓</span>
                  ) : state === 'error' ? (
                    <span aria-hidden className="text-base font-bold">✕</span>
                  ) : (
                    <span aria-hidden className="text-base">○</span>
                  )}
                </div>
                <span className="truncate text-[11px] font-medium">
                  {STAGE_LABEL_KO[stage]}
                </span>
              </div>
              {!isLast && (
                <div
                  aria-hidden
                  className={cn(
                    'mt-4 h-0.5 flex-1 self-start',
                    // 연결선: 다음 단계 시작 전까지의 progress 를 done 색으로
                    // (이번 node 가 done 인 경우만 done 색, 아니면 muted)
                    state === 'done' ? 'bg-emerald-500/40' : 'bg-border',
                  )}
                />
              )}
            </React.Fragment>
          );
        })}
      </div>

      {showProgress && (
        <div className="space-y-1" data-testid="stage-progress-percent">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>현재 단계 진행률</span>
            <span>{pct}%</span>
          </div>
          <div
            className="h-2 w-full overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct}
          >
            <div
              className="h-full bg-violet-500 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
