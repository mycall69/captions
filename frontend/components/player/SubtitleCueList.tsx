'use client';
import type { DualCue } from './DualSubtitleOverlay';

interface SubtitleCueListProps {
  cues: DualCue[];
  currentTimeMs: number;
  onSeek: (timeMs: number) => void;
}

function formatTime(ms: number): string {
  const s = Math.floor(ms / 1000);
  const mm = Math.floor(s / 60).toString().padStart(2, '0');
  const ss = (s % 60).toString().padStart(2, '0');
  return `${mm}:${ss}`;
}

export function SubtitleCueList({ cues, currentTimeMs, onSeek }: SubtitleCueListProps) {
  return (
    <ul className="max-h-96 space-y-1 overflow-y-auto rounded-md border border-border p-2">
      {cues.map((cue, i) => {
        const active = currentTimeMs >= cue.start_ms && currentTimeMs < cue.end_ms;
        return (
          <li key={i}>
            <button
              type="button"
              onClick={() => onSeek(cue.start_ms)}
              className={`block w-full rounded p-2 text-left text-sm hover:bg-muted ${active ? 'bg-muted' : ''}`}
            >
              <div className="font-mono text-xs text-muted-foreground">{formatTime(cue.start_ms)}</div>
              <div>{cue.source}</div>
              <div className="text-muted-foreground">{cue.translated}</div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
