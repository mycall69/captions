'use client';
import { useEffect, useRef, useState } from 'react';
import { useParams } from 'next/navigation';
import { apiFetch } from '@/lib/api/client';
import type { components } from '@/lib/api/types.gen';
import { VideoPlayer } from '@/components/player/VideoPlayer';
import { DualSubtitleOverlay, AutoSubtitleBadge } from '@/components/player/DualSubtitleOverlay';
import type { DualCue } from '@/components/player/DualSubtitleOverlay';
import { SubtitleControls } from '@/components/player/SubtitleControls';
import { SubtitleCueList } from '@/components/player/SubtitleCueList';
import { DownloadActions } from '@/components/player/DownloadActions';
import { usePlayerPreferences } from '@/lib/stores/playerStore';

type Job = components['schemas']['Job'];
type SubtitleBundle = components['schemas']['SubtitleBundle'];

export default function JobPage() {
  const params = useParams();
  const jobId = String(params.id);
  const [job, setJob] = useState<Job | null>(null);
  const [bundle, setBundle] = useState<SubtitleBundle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [currentTimeMs, setCurrentTimeMs] = useState(0);
  const { showSubtitles, order } = usePlayerPreferences();

  useEffect(() => {
    let cancel = false;
    async function tick() {
      try {
        const j = await apiFetch<Job>(`/jobs/${jobId}`);
        if (cancel) return;
        setJob(j);
        if (j.status === 'completed' && bundle === null) {
          const b = await apiFetch<SubtitleBundle>(`/jobs/${jobId}/subtitles?limit=500`);
          if (cancel) return;
          setBundle(b);
        }
      } catch (err) {
        if (!cancel) setError(String(err));
      }
    }
    void tick();
    const interval = setInterval(() => void tick(), 3000);
    return () => {
      cancel = true;
      clearInterval(interval);
    };
  }, [jobId, bundle]);

  if (error) return <p role="alert" className="text-destructive">{error}</p>;
  if (!job) return <p>로딩 중…</p>;

  if (job.status !== 'completed') {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold">{job.metadata.title ?? jobId}</h1>
        <p>현재 상태: <strong>{job.status}</strong></p>
        {job.status === 'failed' && (
          <p role="alert" className="text-destructive">
            실패: {job.error_message ?? job.error_code ?? '알 수 없음'}
          </p>
        )}
      </div>
    );
  }

  const dualCues: DualCue[] = bundle
    ? bundle.source_cues.map((s, i) => ({
        start_ms: s.start_ms,
        end_ms: s.end_ms,
        source: s.text,
        translated: bundle.translated_cues[i]?.text ?? '',
      }))
    : [];

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">{job.metadata.title ?? jobId}</h1>
          <p className="text-sm text-muted-foreground">{job.metadata.channel}</p>
        </div>
        {job.metadata.subtitle_source === 'auto' && <AutoSubtitleBadge />}
      </header>
      <div className="relative">
        <VideoPlayer
          jobId={jobId}
          ref={videoRef}
          onTimeUpdate={(ms) => setCurrentTimeMs(ms)}
        />
        <DualSubtitleOverlay
          cues={dualCues}
          currentTimeMs={currentTimeMs}
          order={order}
          show={showSubtitles}
        />
      </div>
      <SubtitleControls />
      <SubtitleCueList
        cues={dualCues}
        currentTimeMs={currentTimeMs}
        onSeek={(ms) => {
          if (videoRef.current) videoRef.current.currentTime = ms / 1000;
        }}
      />
      <DownloadActions jobId={jobId} />
    </div>
  );
}
