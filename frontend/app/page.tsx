'use client';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { apiFetch, ApiError } from '@/lib/api/client';
import { UrlInputCard } from '@/components/url-input/UrlInputCard';
import type { components } from '@/lib/api/types.gen';

type Job = components['schemas']['Job'];

export default function HomePage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

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
    </div>
  );
}
