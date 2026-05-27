'use client';
import { useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { usePlayerPreferences } from '@/lib/stores/playerStore';

export function SubtitleControls() {
  const { showSubtitles, order, toggleSubtitles, setOrder } = usePlayerPreferences();

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      if (target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA') return;
      const k = e.key.toLowerCase();
      if (k === 's') {
        e.preventDefault();
        toggleSubtitles();
      } else if (k === 'r') {
        e.preventDefault();
        setOrder(order === 'source-first' ? 'target-first' : 'source-first');
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [order, setOrder, toggleSubtitles]);

  return (
    <div className="flex items-center gap-2">
      <Button variant={showSubtitles ? 'default' : 'outline'} onClick={toggleSubtitles}>
        자막 {showSubtitles ? 'ON' : 'OFF'} (S)
      </Button>
      <Button
        variant="outline"
        onClick={() => setOrder(order === 'source-first' ? 'target-first' : 'source-first')}
      >
        순서: {order === 'source-first' ? '원문 위' : '번역문 위'} (R)
      </Button>
    </div>
  );
}
