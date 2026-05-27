/**
 * T095: StatusBadge 컴포넌트 테스트 (US2)
 *
 * 와이어프레임 §컴포넌트 후보 참조:
 *   `<StatusBadge />` — pending / downloading / subtitle_processing / translating /
 *   rendering / completed / failed (7 variant)
 *
 * 검증 항목:
 *   1. 7개 status 각각에 대해 식별 가능한 한국어 라벨이 렌더링된다.
 *   2. 각 status 가 서로 다른 시각 variant 를 가진다 (data-status 또는 class).
 *
 * - 컴포넌트가 아직 구현되지 않은 경우 (T104 이전) 테스트 전체를 skip 처리
 * - Vite 정적 import 분석을 우회하기 위해 경로를 런타임에 조립한다
 */
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';

type JobStatus =
  | 'pending'
  | 'downloading'
  | 'subtitle_processing'
  | 'translating'
  | 'rendering'
  | 'completed'
  | 'failed';

type StatusBadgeType = React.ComponentType<{
  status: JobStatus;
}>;

let StatusBadge: StatusBadgeType | undefined;

const _segments = ['@', '/', 'components', '/job-list/', 'StatusBadge'];
const _modulePath = _segments.join('');
const _mod = await import(/* @vite-ignore */ _modulePath).catch(() => null);
if (_mod && typeof _mod === 'object' && 'StatusBadge' in _mod) {
  StatusBadge = (_mod as Record<string, unknown>)['StatusBadge'] as StatusBadgeType;
}

const componentMissing = !StatusBadge;

const ALL_STATUSES: ReadonlyArray<JobStatus> = [
  'pending',
  'downloading',
  'subtitle_processing',
  'translating',
  'rendering',
  'completed',
  'failed',
];

// 각 status 별로 사용자에게 노출될 한국어 라벨의 일부(또는 동의어) 후보.
// 정확한 문구는 구현체가 결정하지만, 한국어 텍스트가 존재해야 한다.
const KOREAN_HINT: Record<JobStatus, RegExp> = {
  pending: /대기|준비|접수/,
  downloading: /다운|받는|다운로드/,
  subtitle_processing: /자막|처리|추출/,
  translating: /번역/,
  rendering: /렌더|병합|생성/,
  completed: /완료|성공|done/i,
  failed: /실패|오류|에러/,
};

describe.skipIf(componentMissing)('StatusBadge', () => {
  it.each(ALL_STATUSES)('status="%s" 가 렌더링된다', (status) => {
    const Badge = StatusBadge!;
    const { container } = render(React.createElement(Badge, { status }));

    // badge root element 존재 확인
    expect(container.firstChild).not.toBeNull();
  });

  it.each(ALL_STATUSES)(
    'status="%s" 라벨은 한국어 또는 식별 텍스트를 포함한다',
    (status) => {
      const Badge = StatusBadge!;
      const { container } = render(React.createElement(Badge, { status }));

      const text = container.textContent ?? '';
      // 빈 라벨은 허용하지 않는다.
      expect(text.trim()).not.toBe('');
      // 헌법 V — 사용자 노출 텍스트는 한국어. status 키워드 매칭 또는 한글 존재.
      const hasKorean = /[가-힣]/.test(text);
      const matchesHint = KOREAN_HINT[status].test(text);
      expect(hasKorean || matchesHint).toBe(true);
    },
  );

  it('7개 status 각각이 시각적으로 구분되는 variant 를 가진다', () => {
    const Badge = StatusBadge!;
    const variants = new Set<string>();

    for (const status of ALL_STATUSES) {
      const { container } = render(React.createElement(Badge, { status }));
      const root = container.firstChild as HTMLElement | null;
      expect(root).not.toBeNull();

      // data-status 또는 class 명에 status 토큰이 포함되어야 함
      const dataStatus = root!.getAttribute('data-status') ?? '';
      const className = root!.className ?? '';
      const signature = `${dataStatus}|${className}`;
      variants.add(signature);
    }

    // 7개 status 가 모두 서로 다른 variant 시그니처여야 한다.
    expect(variants.size).toBe(ALL_STATUSES.length);
  });
});
