'use client';
import type { SubtitleOrder } from '@/lib/stores/playerStore';

// AutoSubtitleBadge 의 정본은 StatusBadge.tsx 에 있다 — 재-export 로 호환성을 유지한다.
export { AutoSubtitleBadge } from '@/components/job-list/StatusBadge';

export interface DualCue {
  start_ms: number;
  end_ms: number;
  source: string;
  translated: string;
}

interface DualSubtitleOverlayProps {
  cues: DualCue[];
  currentTimeMs: number;
  order?: SubtitleOrder;
  show?: boolean;
}

export function DualSubtitleOverlay({
  cues,
  currentTimeMs,
  order = 'source-first',
  show = true,
}: DualSubtitleOverlayProps) {
  const active = cues.find((c) => currentTimeMs >= c.start_ms && currentTimeMs < c.end_ms);
  if (!active || !show) return null;

  const sourceEl = (
    <div key="source" data-testid="dual-source" className="px-4 py-1 text-2xl font-semibold">
      {active.source}
    </div>
  );
  const translatedEl = (
    <div key="translated" data-testid="dual-translated" className="px-4 py-1 text-xl">
      {active.translated}
    </div>
  );

  return (
    <div
      className="pointer-events-none absolute bottom-16 left-1/2 -translate-x-1/2 flex flex-col items-center gap-1 text-center text-white drop-shadow-lg"
      data-testid="dual-subtitle-overlay"
    >
      {order === 'source-first' ? <>{sourceEl}{translatedEl}</> : <>{translatedEl}{sourceEl}</>}
    </div>
  );
}
