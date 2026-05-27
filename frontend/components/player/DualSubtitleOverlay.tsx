'use client';
import type { SubtitleOrder } from '@/lib/stores/playerStore';

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

export function AutoSubtitleBadge() {
  return (
    <span
      data-testid="auto-subtitle-badge"
      className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
    >
      🤖 자동 자막 기반
    </span>
  );
}
