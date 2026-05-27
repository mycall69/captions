/**
 * MetadataPanel — 영상 메타데이터 패널 (T108, US2)
 *
 * 와이어프레임 §S2 상단:
 *   ┌──────────────────┐  「日本語で学ぶ経済」
 *   │     [썸네일]      │  채널: ABC  ·  길이 12:34  ·  ja → ko
 *   │                  │  자막 출처: 수동(ja)        제출: 2분 전
 *   └──────────────────┘
 *
 * 헌법 V — 한국어 라벨 / 한국어 주석. metadata.title 은 원문 보존(다국어 영상 제목).
 */
import * as React from 'react';
import { cn } from '@/lib/utils';
import { AutoSubtitleBadge } from '@/components/job-list/StatusBadge';
import type { components } from '@/lib/api/types.gen';

export type VideoMetadata = components['schemas']['VideoMetadata'];
export type Language = components['schemas']['Language'];

interface MetadataPanelProps {
  metadata: VideoMetadata;
  /** Job id — 썸네일 fallback alt 로 사용. */
  jobId?: string;
  /** 원본 / 대상 언어 (있을 때만 표시). */
  sourceLanguage?: Language | null;
  targetLanguage?: Language | null;
  /** 작업 생성 시각 ISO-8601. */
  createdAt?: string | null;
  /** 썸네일 URL (있을 때만). 백엔드가 직접 제공하지 않으면 null. */
  thumbnailUrl?: string | null;
  className?: string;
}

// duration_sec → mm:ss / hh:mm:ss
function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '—';
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

const LANGUAGE_LABEL: Record<string, string> = {
  ko: '한국어',
  ja: '일본어',
};

function formatLanguagePair(
  source?: Language | null,
  target?: Language | null,
): string | null {
  if (!source || !target) return null;
  return `${LANGUAGE_LABEL[source] ?? source} → ${LANGUAGE_LABEL[target] ?? target}`;
}

// "n분 전" 등의 상대 시간 — 단순 구현 (MVP).
function formatRelativeTime(iso?: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const diffMs = Date.now() - d.getTime();
  const sec = Math.floor(diffMs / 1000);
  if (sec < 5) return '방금 전';
  if (sec < 60) return `${sec}초 전`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}분 전`;
  const hour = Math.floor(min / 60);
  if (hour < 24) return `${hour}시간 전`;
  const day = Math.floor(hour / 24);
  return `${day}일 전`;
}

export function MetadataPanel({
  metadata,
  jobId,
  sourceLanguage,
  targetLanguage,
  createdAt,
  thumbnailUrl,
  className,
}: MetadataPanelProps) {
  const langPair = formatLanguagePair(sourceLanguage, targetLanguage);
  const relative = formatRelativeTime(createdAt);

  return (
    <section
      data-testid="metadata-panel"
      className={cn(
        'flex gap-4 rounded-lg border border-border bg-card p-4',
        className,
      )}
      aria-label="영상 정보"
    >
      <div
        className={cn(
          'flex h-24 w-40 shrink-0 items-center justify-center overflow-hidden rounded bg-muted text-xs text-muted-foreground',
        )}
        aria-hidden={!thumbnailUrl}
      >
        {thumbnailUrl ? (
          // 디자인 단계에서 next/image 로 교체 가능. MVP 단순 img.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={thumbnailUrl}
            alt={metadata.title ?? jobId ?? '영상 썸네일'}
            className="h-full w-full object-cover"
          />
        ) : (
          <span>썸네일 없음</span>
        )}
      </div>

      <div className="min-w-0 flex-1 space-y-1.5">
        <h1
          data-testid="metadata-title"
          className="truncate text-lg font-semibold"
          title={metadata.title ?? undefined}
        >
          {metadata.title ?? jobId ?? '제목 없음'}
        </h1>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-sm text-muted-foreground">
          {metadata.channel && (
            <>
              <dt>채널:</dt>
              <dd data-testid="metadata-channel" className="truncate">
                {metadata.channel}
              </dd>
            </>
          )}
          <dt>길이:</dt>
          <dd data-testid="metadata-duration">
            {formatDuration(metadata.duration_sec)}
          </dd>
          {langPair && (
            <>
              <dt>언어:</dt>
              <dd data-testid="metadata-language">{langPair}</dd>
            </>
          )}
          {metadata.subtitle_source && (
            <>
              <dt>자막 출처:</dt>
              <dd data-testid="metadata-subtitle-source" className="flex items-center gap-2">
                <span>
                  {metadata.subtitle_source === 'manual' ? '수동' : '자동'}
                </span>
                {metadata.subtitle_source === 'auto' && <AutoSubtitleBadge />}
              </dd>
            </>
          )}
          {relative && (
            <>
              <dt>제출:</dt>
              <dd data-testid="metadata-submitted">{relative}</dd>
            </>
          )}
        </dl>
      </div>
    </section>
  );
}
