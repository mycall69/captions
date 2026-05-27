'use client';
import type { SubtitleOrder } from '@/lib/stores/playerStore';

export interface DualCue {
  startMs: number;
  endMs: number;
  sourceText: string;
  translatedText: string;
}

interface DualSubtitleOverlayProps {
  cues: DualCue[];
  currentTime: number;
  order?: SubtitleOrder;
  show?: boolean;
}

export function DualSubtitleOverlay({
  cues,
  currentTime,
  order = 'source-first',
  show = true,
}: DualSubtitleOverlayProps) {
  const active = cues.find((c) => currentTime >= c.startMs && currentTime < c.endMs);
  if (!active || !show) return null;

  const sourceEl = (
    <div key="source" data-testid="dual-source" className="px-4 py-1 text-2xl font-semibold">
      {active.sourceText}
    </div>
  );
  const translatedEl = (
    <div key="translated" data-testid="dual-translated" className="px-4 py-1 text-xl">
      {active.translatedText}
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
