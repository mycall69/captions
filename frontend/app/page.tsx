/**
 * S1 — 메인 페이지 (URL 입력 + 최근 작업).
 *
 * T119 (US3) — 기존 URL 입력 카드 아래에 최근 작업 목록을 통합한다.
 * 와이어프레임 §S1 참조 (wireframes.md).
 *
 * - 최대 5건 노출 (`useRecentJobs({ limit: 5 })`)
 * - 빈 결과 → `EmptyState`
 * - 5건일 때 `[ 전체 보기 → ]` CTA 노출 — `/jobs` 인덱스 페이지는 MVP 범위 밖이므로
 *   disabled 버튼 + 한국어 안내 텍스트로만 노출한다(헌법 V).
 *
 * 헌법 V — 모든 사용자 노출 텍스트는 한국어.
 */
'use client';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { apiFetch, ApiError } from '@/lib/api/client';
import { Button } from '@/components/ui/button';
import { UrlInputCard } from '@/components/url-input/UrlInputCard';
import { JobListItem } from '@/components/job-list/JobListItem';
import { EmptyState } from '@/components/job-list/EmptyState';
import { useRecentJobs } from '@/lib/api/hooks';
import type { components } from '@/lib/api/types.gen';

type Job = components['schemas']['Job'];

export default function HomePage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const recent = useRecentJobs({ limit: 5 });

  async function handleSubmit(url: string) {
    setError(null);
    setSubmitting(true);
    try {
      const job = await apiFetch<Job>('/jobs', {
        method: 'POST',
        body: JSON.stringify({ url }),
      });
      router.push(`/jobs/${job.id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError('알 수 없는 오류가 발생했습니다.');
      }
    } finally {
      setSubmitting(false);
    }
  }

  const items = recent.data?.items ?? [];
  const isEmpty = !recent.isLoading && items.length === 0;

  return (
    <div className="space-y-8">
      <div className="text-center">
        <h1 className="text-3xl font-semibold">두 언어로 영상 학습을 시작하세요</h1>
        <p className="mt-2 text-muted-foreground">일본어 ↔ 한국어 이중 자막을 자동으로 생성합니다</p>
      </div>
      <UrlInputCard onSubmit={handleSubmit} />
      {submitting && <p className="text-center text-sm text-muted-foreground">작업을 생성하는 중…</p>}
      {error && (
        <p role="alert" className="text-center text-sm text-destructive">
          {error}
        </p>
      )}

      <section aria-labelledby="recent-jobs-heading" className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 id="recent-jobs-heading" className="text-lg font-semibold">
            최근 작업
          </h2>
          <Button
            variant="outline"
            size="sm"
            onClick={() => recent.refetch()}
            disabled={recent.isFetching}
          >
            {recent.isFetching ? '새로고침 중…' : '새로고침 ↻'}
          </Button>
        </div>

        {recent.isLoading && (
          <p className="text-sm text-muted-foreground">최근 작업을 불러오는 중…</p>
        )}

        {recent.isError && !recent.isLoading && (
          <p role="alert" className="text-sm text-destructive">
            최근 작업을 불러오지 못했습니다.
          </p>
        )}

        {isEmpty && !recent.isError && <EmptyState />}

        {items.length > 0 && (
          <ul className="space-y-2">
            {items.map((job) => (
              <JobListItem key={job.id} job={job} />
            ))}
          </ul>
        )}

        {/*
          와이어프레임 §S1 — 5건이 모두 채워졌을 때만 "전체 보기" CTA 를 노출한다.
          `/jobs` 인덱스 페이지는 MVP 범위 밖이므로 disabled 버튼으로 노출하고
          title 속성으로 안내한다.
        */}
        {items.length >= 5 && (
          <div className="flex justify-end pt-1">
            <button
              type="button"
              disabled
              title="추후 구현 예정"
              aria-disabled="true"
              className="text-sm text-muted-foreground opacity-60 cursor-not-allowed"
            >
              전체 보기 →
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
