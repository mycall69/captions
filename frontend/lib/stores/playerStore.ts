import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type SubtitleOrder = 'source-first' | 'target-first';
export type SubtitleFormat = 'srt' | 'vtt';

interface PlayerPreferences {
  showSubtitles: boolean;
  order: SubtitleOrder;
  format: SubtitleFormat;
  toggleSubtitles: () => void;
  setOrder: (order: SubtitleOrder) => void;
  setFormat: (format: SubtitleFormat) => void;
}

export const usePlayerPreferences = create<PlayerPreferences>()(
  persist(
    (set) => ({
      showSubtitles: true,
      order: 'source-first',
      format: 'srt',
      toggleSubtitles: () => set((s) => ({ showSubtitles: !s.showSubtitles })),
      setOrder: (order) => set({ order }),
      setFormat: (format) => set({ format }),
    }),
    { name: 'bilingual-subtitle-player-preferences' },
  ),
);
