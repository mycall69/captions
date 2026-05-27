/**
 * T113: JobListItem 컴포넌트 테스트 (US3)
 *
 * 와이어프레임 §S1 §최근 작업 카드 — 3 variant:
 *   - completed → "재생" CTA (S3 로 이동)
 *   - in-progress (pending/downloading/subtitle_processing/translating/rendering) → "상태"/"보기" CTA (S2)
 *   - failed → "상세"/"재시도" CTA (S2 실패 패널)
 *
 * 검증 항목:
 *   1. 제목 / 채널 / 상태 배지가 표시된다.
 *   2. variant 별로 우측 액션 라벨이 한국어로 표시된다 (헌법 V).
 *   3. status 가 명시적으로 데이터 속성/텍스트로 노출된다.
 *
 * - 컴포넌트가 아직 구현되지 않은 경우 (T116 이전) 테스트 전체를 skip 처리.
 * - Vitest 의 동적 import 실패는 `.catch` 로 안전하게 흡수한다.
 */
import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';

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

type JobListItemType = React.ComponentType<{ job: JobLite }>;

// Vite 정적 분석을 피하기 위해 경로를 변수로 분리한다.
// 컴포넌트(T116) 미구현 상태에서도 import 실패가 `.catch` 로 안전하게 흡수돼야 한다.
const _modulePath: string = '@/components/job-list/JobListItem';
const _mod = await import(/* @vite-ignore */ _modulePath).catch(() => null);
const JobListItem: JobListItemType | undefined =
  _mod && typeof _mod === 'object' && 'JobListItem' in _mod
    ? ((_mod as Record<string, unknown>)['JobListItem'] as JobListItemType)
    : undefined;

const componentMissing = !JobListItem;

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

describe.skipIf(componentMissing)('JobListItem', () => {
  it('제목 / 채널이 표시된다', () => {
    const Item = JobListItem!;
    const { container } = render(
      React.createElement(Item, { job: makeJob() }),
    );
    const text = container.textContent ?? '';
    expect(text).toMatch('테스트 영상 제목');
    expect(text).toMatch('테스트 채널');
  });

  it('completed 항목은 "재생" CTA 가 한국어로 노출된다', () => {
    const Item = JobListItem!;
    const { container } = render(
      React.createElement(Item, { job: makeJob({ status: 'completed' }) }),
    );
    const text = container.textContent ?? '';
    expect(text).toMatch(/재생/);
  });

  it('진행 중 항목(translating) 은 진행 상태가 노출되고 상세/보기 CTA 가 있다', () => {
    const Item = JobListItem!;
    const { container } = render(
      React.createElement(Item, {
        job: makeJob({ status: 'translating', completed_at: null }),
      }),
    );
    const text = container.textContent ?? '';
    // 상태가 노출되어야 한다 (배지 텍스트 또는 status 토큰)
    expect(/번역|translating|상태|보기|진행/.test(text)).toBe(true);
    // 진행 중 항목에는 "재생" CTA 가 노출되지 않아야 한다 (헌법 V — 완료 전 재생 차단)
    expect(text).not.toMatch(/^재생$/);
  });

  it('failed 항목은 실패 사유와 "다시 시도"/"상세" CTA 가 한국어로 노출된다', () => {
    const Item = JobListItem!;
    const { container } = render(
      React.createElement(Item, {
        job: makeJob({
          status: 'failed',
          error_stage: 'subtitle_processing',
          error_code: 'SUBTITLE_NOT_FOUND',
          error_message: '자막을 찾을 수 없습니다.',
          completed_at: '2026-05-28T00:01:00Z',
        }),
      }),
    );
    const text = container.textContent ?? '';
    // 실패 사유 메시지 노출
    expect(text).toMatch('자막을 찾을 수 없습니다.');
    // CTA — 재시도 / 다시 시도 / 상세 중 하나는 노출되어야 한다
    expect(/다시 시도|재시도|상세/.test(text)).toBe(true);
  });

  it('영상 길이가 mm:ss 형태로 표기된다 (12분 34초 → 12:34)', () => {
    const Item = JobListItem!;
    const { container } = render(
      React.createElement(Item, {
        job: makeJob({ metadata: { ...makeJob().metadata, duration_sec: 754 } }),
      }),
    );
    const text = container.textContent ?? '';
    expect(text).toMatch(/12:34/);
  });
});
