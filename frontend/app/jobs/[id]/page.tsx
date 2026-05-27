/**
 * 작업 상세 페이지 — S2 (진행/실패) + S3 (재생) 분기 (T111, US2)
 *
 * 와이어프레임:
 *   - state ∈ {pending..rendering, failed}: S2 (MetadataPanel + StatusBadge + StageProgressBar
 *     + StageLog + FailurePanel 조건부)
 *   - state === 'completed': S3 (VideoPlayer + DualSubtitleOverlay + Controls + CueList)
 *
 * SSE 이벤트는 `useJobWithEvents` 에서 TanStack Query cache 로 머지되어 자동 재렌더.
 */
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
import { useJobWithEvents } from '@/lib/api/hooks';
import { StatusBadge } from '@/components/job-list/StatusBadge';
import { StageProgressBar } from '@/components/stage-progress/StageProgressBar';
import { StageLog } from '@/components/stage-progress/StageLog';
import { FailurePanel } from '@/components/stage-progress/FailurePanel';
import { MetadataPanel } from '@/components/job-detail/MetadataPanel';

type SubtitleBundle = components['schemas']['SubtitleBundle'];

export default function JobPage() {
  const params = useParams();
  const jobId = String(params.id);

  // SSE 구독 + TanStack Query 단건 fetch 통합 훅
  const { job, events, error: jobError } = useJobWithEvents(jobId);

  const [bundle, setBundle] = useState<SubtitleBundle | null>(null);
  const [bundleError, setBundleError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [currentTimeMs, setCurrentTimeMs] = useState(0);
  const { showSubtitles, order } = usePlayerPreferences();

  // 완료 시 자막 번들 fetch (S3 진입 트리거)
  useEffect(() => {
    if (job?.status !== 'completed' || bundle !== null) return;
    let cancel = false;
    void (async () => {
      try {
        const b = await apiFetch<SubtitleBundle>(`/jobs/${jobId}/subtitles?limit=500`);
        if (!cancel) setBundle(b);
      } catch (err) {
        if (!cancel) setBundleError(String(err));
      }
    })();
    return () => {
      cancel = true;
    };
  }, [job?.status, bundle, jobId]);

  if (jobError) {
    return (
      <p role="alert" className="text-destructive">
        {String(jobError)}
      </p>
    );
  }
  if (!job) return <p>로딩 중…</p>;

  // ─────────────────── S2: 진행 / 실패 분기 ───────────────────
  if (job.status !== 'completed') {
    return (
      <div className="space-y-6" data-testid="job-s2">
        <MetadataPanel
          metadata={job.metadata}
          jobId={jobId}
          sourceLanguage={job.source_language ?? null}
          targetLanguage={job.target_language ?? null}
          createdAt={job.created_at}
        />

        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold">단계 진행</h2>
            <StatusBadge status={job.status} />
          </div>
          <StageProgressBar status={job.status} errorStage={job.error_stage ?? null} />
          {typeof job.progress === 'number' && job.status !== 'failed' && (
            <div className="space-y-1">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>현재 단계 진행률</span>
                <span>{Math.round((job.progress ?? 0) * 100)}%</span>
              </div>
              <div
                className="h-2 w-full overflow-hidden rounded-full bg-muted"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round((job.progress ?? 0) * 100)}
              >
                <div
                  className="h-full bg-violet-500 transition-all"
                  style={{ width: `${Math.round((job.progress ?? 0) * 100)}%` }}
                />
              </div>
            </div>
          )}
        </section>

        {job.status === 'failed' && (
          <FailurePanel
            errorStage={job.error_stage ?? null}
            errorCode={job.error_code ?? null}
            errorMessage={job.error_message ?? null}
            failedAt={job.updated_at}
            sourceUrl={job.source_url}
          />
        )}

        <section className="space-y-2">
          <h2 className="text-base font-semibold">단계별 로그</h2>
          <StageLog events={events} />
        </section>
      </div>
    );
  }

  // ─────────────────── S3: 재생 ───────────────────
  if (bundleError) {
    return (
      <p role="alert" className="text-destructive">
        {bundleError}
      </p>
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
    <div className="space-y-4" data-testid="job-s3">
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
