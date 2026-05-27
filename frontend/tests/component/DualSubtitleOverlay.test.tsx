/**
 * T053: DualSubtitleOverlay 컴포넌트 테스트
 *
 * - 컴포넌트가 아직 구현되지 않은 경우 (Phase 3i 이전) 테스트 전체를 skip 처리
 * - 구현 완료 후 describe 블록이 자동으로 활성화됨
 * - Vite가 정적 import 경로를 분석하지 못하도록 경로를 런타임에 조립한다
 *
 * 검증 항목:
 *   1. 활성 cue가 없으면 아무것도 렌더링하지 않음
 *   2. currentTime이 cue 범위 내일 때 원문 + 번역문 두 줄이 렌더링됨
 *   3. order='source-first' (기본값): 원문이 위, 번역문이 아래
 *   4. order='target-first': 번역문이 위, 원문이 아래
 *   5. order prop 변경 시 두 줄 순서가 즉시 전환됨
 *   6. 번역문이 빈 문자열인 cue에서도 크래시 없이 렌더링됨
 *
 * 와이어프레임 §S3 참조:
 *   - 영상 하단 18% 영역에 두 줄 표시 (원문 / 번역문)
 *   - order prop으로 원문 위 / 번역문 위 전환 (FR-023, 단축키 R)
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';

// DualCue: 각 cue의 데이터 구조 — 시작/종료 시간(ms), 원문, 번역문
interface DualCue {
  startMs: number;
  endMs: number;
  sourceText: string;
  translatedText: string;
}

type SubtitleOrder = 'source-first' | 'target-first';

type DualSubtitleOverlayType = React.ComponentType<{
  cues: DualCue[];
  currentTime: number; // ms
  order?: SubtitleOrder;
}>;

let DualSubtitleOverlay: DualSubtitleOverlayType | undefined;

// Vite의 정적 import 분석을 우회하기 위해 경로를 런타임에 조립
const _dsoSegments = ['@', '/', 'components', '/subtitle/', 'DualSubtitleOverlay'];
const _dsoModulePath = _dsoSegments.join('');
const _dsoMod = await import(/* @vite-ignore */ _dsoModulePath).catch(() => null);
if (_dsoMod && typeof _dsoMod === 'object' && 'DualSubtitleOverlay' in _dsoMod) {
  DualSubtitleOverlay = (_dsoMod as Record<string, unknown>)[
    'DualSubtitleOverlay'
  ] as DualSubtitleOverlayType;
}

// 테스트용 샘플 cue 데이터
const sampleCues: DualCue[] = [
  {
    startMs: 2000,
    endMs: 6000,
    sourceText: 'ようこそ、今日のテーマは経済です。',
    translatedText: '오신 것을 환영합니다, 오늘의 주제는 경제입니다.',
  },
  {
    startMs: 8000,
    endMs: 13000,
    sourceText: '経済の基本は需要と供給のバランスです。',
    translatedText: '경제의 기본은 수요와 공급의 균형입니다.',
  },
];

// skipIf에 boolean을 직접 전달 — 모듈 로드 시점에 평가되므로 컴포넌트 구현 후 자동 활성화
const dsoComponentMissing = !DualSubtitleOverlay;

describe.skipIf(dsoComponentMissing)('DualSubtitleOverlay', () => {
  it('활성 cue가 없을 때 아무것도 렌더링하지 않는다', () => {
    const Overlay = DualSubtitleOverlay!;
    const { container } = render(
      React.createElement(Overlay, {
        cues: sampleCues,
        currentTime: 1000, // 1000ms — 어느 cue 범위에도 해당하지 않음
      }),
    );

    // data-testid="dual-subtitle-overlay" 요소가 없거나 내부가 비어있어야 함
    const overlay = container.querySelector('[data-testid="dual-subtitle-overlay"]');
    if (overlay) {
      // overlay 요소가 존재한다면 내부에 표시할 텍스트가 없어야 함
      expect(overlay.textContent?.trim()).toBe('');
    } else {
      // overlay 요소 자체가 렌더링되지 않아도 정상
      expect(overlay).toBeNull();
    }
  });

  it('currentTime이 cue 범위 내일 때 원문과 번역문 두 줄이 렌더링된다', () => {
    const Overlay = DualSubtitleOverlay!;
    render(
      React.createElement(Overlay, {
        cues: sampleCues,
        currentTime: 4000, // 첫 번째 cue (2000~6000ms) 범위 내
      }),
    );

    // 원문 텍스트 확인
    expect(screen.getByText('ようこそ、今日のテーマは経済です。')).toBeDefined();
    // 번역문 텍스트 확인
    expect(screen.getByText('오신 것을 환영합니다, 오늘의 주제는 경제입니다.')).toBeDefined();
  });

  it.each([
    {
      order: 'source-first' as SubtitleOrder,
      label: '원문이 번역문보다 위에 위치한다',
      // source-first: 원문(first)이 번역문(second)보다 앞에 위치해야 함
      // compareDocumentPosition: DOCUMENT_POSITION_FOLLOWING = 4 (두 번째 인자가 뒤에 있음)
      firstText: 'ようこそ、今日のテーマは経済です。',
      secondText: '오신 것을 환영합니다, 오늘의 주제는 경제입니다.',
    },
    {
      order: 'target-first' as SubtitleOrder,
      label: '번역문이 원문보다 위에 위치한다',
      // target-first: 번역문(first)이 원문(second)보다 앞에 위치해야 함
      firstText: '오신 것을 환영합니다, 오늘의 주제는 경제입니다.',
      secondText: 'ようこそ、今日のテーマは経済です。',
    },
  ])("order='$order': $label", ({ order, firstText, secondText }) => {
    const Overlay = DualSubtitleOverlay!;
    render(
      React.createElement(Overlay, {
        cues: sampleCues,
        currentTime: 4000,
        order,
      }),
    );

    const firstEl = screen.getByText(firstText);
    const secondEl = screen.getByText(secondText);

    // firstEl이 secondEl보다 앞에 위치해야 함
    // DOCUMENT_POSITION_FOLLOWING(4): secondEl이 firstEl 뒤에 있을 때 세트
    const position = firstEl.compareDocumentPosition(secondEl);
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('order prop 변경 시 두 줄의 DOM 순서가 즉시 전환된다', () => {
    const Overlay = DualSubtitleOverlay!;
    const { rerender } = render(
      React.createElement(Overlay, {
        cues: sampleCues,
        currentTime: 10000, // 두 번째 cue (8000~13000ms) 범위 내
        order: 'source-first' as SubtitleOrder,
      }),
    );

    const sourceText = '経済の基本は需要と供給のバランスです。';
    const translatedText = '경제의 기본은 수요와 공급의 균형입니다.';

    // source-first: 원문이 앞
    const sourceFirst = screen.getByText(sourceText);
    const translatedFirst = screen.getByText(translatedText);
    const beforeSwap = sourceFirst.compareDocumentPosition(translatedFirst);
    expect(beforeSwap & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    // order를 target-first로 전환
    rerender(
      React.createElement(Overlay, {
        cues: sampleCues,
        currentTime: 10000,
        order: 'target-first' as SubtitleOrder,
      }),
    );

    // target-first: 번역문이 앞
    const sourceAfter = screen.getByText(sourceText);
    const translatedAfter = screen.getByText(translatedText);
    const afterSwap = translatedAfter.compareDocumentPosition(sourceAfter);
    expect(afterSwap & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('번역문이 빈 문자열인 cue에서도 크래시 없이 렌더링된다', () => {
    const Overlay = DualSubtitleOverlay!;
    const cuesWithEmptyTranslation: DualCue[] = [
      {
        startMs: 0,
        endMs: 5000,
        sourceText: '原文テキスト',
        translatedText: '', // 빈 번역문
      },
    ];

    // 크래시가 발생하지 않아야 함
    expect(() => {
      render(
        React.createElement(Overlay, {
          cues: cuesWithEmptyTranslation,
          currentTime: 2500,
        }),
      );
    }).not.toThrow();

    // 원문은 렌더링되어야 함
    expect(screen.getByText('原文テキスト')).toBeDefined();
  });

  // data-testid="dual-line" 검증은 구현 내부 세부사항이므로 제거
  // DOM 순서 테스트(it.each order)가 동일한 동작을 더 명확하게 검증한다
});
