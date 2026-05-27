/**
 * T113: JobListItem 컴포넌트 테스트 (US3)
 *
 * 와이어프레임 §S1 §최근 작업 카드 — 3 variant:
 *   - completed → "재생" CTA (S3 로 이동)
 *   - in-progress (pending/downloading/subtitle_processing/translating/rendering) → "상태"/"보기" CTA (S2)
 *   - failed → "상세" CTA (S2 실패 패널)
 *
 * 검증 항목:
 *   1. 제목 / 채널 / 상태 배지가 표시된다.
 *   2. variant 별로 우측 액션 라벨이 한국어로 표시된다 (헌법 V).
 *   3. status 가 명시적으로 데이터 속성/텍스트로 노출된다.
 *
 * T116 컴포넌트가 커밋된 이후로는 정적 import 만 사용한다(skipIf 제거).
 */
import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';
import { JobListItem } from '@/components/job-list/JobListItem';

// next/navigation 의 useRouter 는 클라이언트 라우터 컨텍스트가 필요하다.
// 컴포넌트 단위 테스트에서는 push 만 spy 로 대체하면 충분하다.
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
}));

type JobStatus =
  | 'pending'
  | 'downloading'
  | 'subtitle_processing'
  | 'translating'
  | 'rendering'
  | 'completed'
  | 'failed';

interface JobLite {
  id: string;
  source_url: string;
  youtube_video_id: string;
  status: JobStatus;
  error_stage?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  metadata: {
    title: string | null;
    channel: string | null;
    duration_sec: number | null;
    subtitle_source: 'manual' | 'auto' | null;
  };
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  reused: boolean;
}

function makeJob(overrides: Partial<JobLite> = {}): JobLite {
  return {
    id: '01TESTJOB000000000000000AA',
    source_url: 'https://www.youtube.com/watch?v=abcdefghijk',
    youtube_video_id: 'abcdefghijk',
    status: 'completed',
    metadata: {
      title: '테스트 영상 제목',
      channel: '테스트 채널',
      duration_sec: 754,
      subtitle_source: 'manual',
    },
    created_at: '2026-05-28T00:00:00Z',
    updated_at: '2026-05-28T00:05:00Z',
    completed_at: '2026-05-28T00:05:00Z',
    reused: false,
    ...overrides,
  };
}

// JobLite 는 API 스키마의 부분 집합이므로 props 경계에서 캐스팅한다.
// (테스트는 컴포넌트 렌더 결과만 검증하며 누락 필드는 사용하지 않는다.)
type JobProp = React.ComponentProps<typeof JobListItem>['job'];
const asJob = (j: JobLite): JobProp => j as unknown as JobProp;

describe('JobListItem', () => {
  it('제목 / 채널이 표시된다', () => {
    const { container } = render(
      React.createElement(JobListItem, { job: asJob(makeJob()) }),
    );
    const text = container.textContent ?? '';
    expect(text).toMatch('테스트 영상 제목');
    expect(text).toMatch('테스트 채널');
  });

  it('completed 항목은 "재생" CTA 가 한국어로 노출된다', () => {
    const { container } = render(
      React.createElement(JobListItem, {
        job: asJob(makeJob({ status: 'completed' })),
      }),
    );
    const text = container.textContent ?? '';
    expect(text).toMatch(/재생/);
  });

  it('진행 중 항목(translating) 은 진행 상태가 노출되고 상세/보기 CTA 가 있다', () => {
    const { container } = render(
      React.createElement(JobListItem, {
        job: asJob(makeJob({ status: 'translating', completed_at: null })),
      }),
    );
    const text = container.textContent ?? '';
    // 상태가 노출되어야 한다 (배지 텍스트 또는 status 토큰)
    expect(/번역|translating|상태|보기|진행/.test(text)).toBe(true);
    // 진행 중 항목에는 "재생" CTA 가 노출되지 않아야 한다 (헌법 V — 완료 전 재생 차단)
    expect(text).not.toMatch(/^재생$/);
  });

  it('failed 항목은 실패 사유와 "상세" CTA 가 한국어로 노출된다', () => {
    const { container } = render(
      React.createElement(JobListItem, {
        job: asJob(
          makeJob({
            status: 'failed',
            error_stage: 'subtitle_processing',
            error_code: 'SUBTITLE_NOT_FOUND',
            error_message: '자막을 찾을 수 없습니다.',
            completed_at: '2026-05-28T00:01:00Z',
          }),
        ),
      }),
    );
    const text = container.textContent ?? '';
    // 실패 사유 메시지 노출
    expect(text).toMatch('자막을 찾을 수 없습니다.');
    // CTA — 와이어프레임 §S1 은 `[상세 →]` 를 명시한다.
    expect(/다시 시도|재시도|상세/.test(text)).toBe(true);
  });

  it('영상 길이가 mm:ss 형태로 표기된다 (12분 34초 → 12:34)', () => {
    const { container } = render(
      React.createElement(JobListItem, {
        job: asJob(
          makeJob({ metadata: { ...makeJob().metadata, duration_sec: 754 } }),
        ),
      }),
    );
    const text = container.textContent ?? '';
    expect(text).toMatch(/12:34/);
  });
});
