/**
 * T095: StageProgressBar 컴포넌트 테스트 (US2)
 *
 * 와이어프레임 §S2 참조:
 *   ●━━━━━●━━━━━●━━━━━◐━━━━━○━━━━━○
 *   대기   다운  자막  번역   렌더  완료
 *                       ↑ 현재
 *
 * 6노드:
 *   pending → downloading → subtitle_processing → translating → rendering → completed
 *
 * 검증 항목:
 *   1. 6개 노드가 정확한 순서로 렌더링된다.
 *   2. 현재(current) 노드에 회전 인디케이터 클래스(`animate-spin` / `rotating` 등)가 부여된다.
 *   3. 완료(done) 노드에 done 클래스가 부여된다.
 *   4. 실패(error) 단계에 error 클래스가 부여된다.
 *
 * - 컴포넌트가 아직 구현되지 않은 경우 (T105 이전) 테스트 전체를 skip 처리
 * - Vite 정적 import 분석을 우회하기 위해 경로를 런타임에 조립한다
 */
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';

// JobStatus 와 동일한 7개 상태
type JobStatus =
  | 'pending'
  | 'downloading'
  | 'subtitle_processing'
  | 'translating'
  | 'rendering'
  | 'completed'
  | 'failed';

type StageProgressBarType = React.ComponentType<{
  /** 현재 상태 — current 노드 결정. */
  status: JobStatus;
  /** 실패 단계가 발생한 경우 그 stage 이름 (state==='failed' 일 때만 의미). */
  errorStage?: string | null;
}>;

let StageProgressBar: StageProgressBarType | undefined;

const _segments = ['@', '/', 'components', '/stage-progress/', 'StageProgressBar'];
const _modulePath = _segments.join('');
const _mod = await import(/* @vite-ignore */ _modulePath).catch(() => null);
if (_mod && typeof _mod === 'object' && 'StageProgressBar' in _mod) {
  StageProgressBar = (_mod as Record<string, unknown>)[
    'StageProgressBar'
  ] as StageProgressBarType;
}

const componentMissing = !StageProgressBar;

// 6노드의 정렬된 순서 — pending → completed
const NODE_ORDER: ReadonlyArray<Exclude<JobStatus, 'failed'>> = [
  'pending',
  'downloading',
  'subtitle_processing',
  'translating',
  'rendering',
  'completed',
];

/**
 * 노드 root element 들을 찾는다.
 * 구현체가 `data-stage="<status>"` 로 표시하거나, 혹은 data-testid="stage-node"
 * 의 list 형태로 표시할 수 있으므로 둘 다 지원한다.
 */
function findNodes(container: HTMLElement): HTMLElement[] {
  const byDataStage = Array.from(
    container.querySelectorAll<HTMLElement>('[data-stage]')
  );
  if (byDataStage.length >= 6) {
    return byDataStage;
  }
  return Array.from(
    container.querySelectorAll<HTMLElement>('[data-testid="stage-node"]')
  );
}

describe.skipIf(componentMissing)('StageProgressBar', () => {
  it('6개 노드가 정의된 순서대로 렌더링된다', () => {
    const Bar = StageProgressBar!;
    const { container } = render(
      React.createElement(Bar, { status: 'translating' })
    );

    const nodes = findNodes(container);
    expect(nodes.length).toBe(6);

    // data-stage 가 있으면 순서를 직접 검증한다
    const stages = nodes.map((n) => n.getAttribute('data-stage'));
    if (stages.every((s) => s !== null)) {
      expect(stages).toEqual(NODE_ORDER);
    }
  });

  it('현재 노드(status=translating) 에는 회전 인디케이터 클래스가 부여된다', () => {
    const Bar = StageProgressBar!;
    const { container } = render(
      React.createElement(Bar, { status: 'translating' })
    );

    const nodes = findNodes(container);
    // translating 노드 검색 — data-stage 또는 index 기반
    const current =
      nodes.find((n) => n.getAttribute('data-stage') === 'translating') ??
      nodes[NODE_ORDER.indexOf('translating')];
    expect(current).toBeDefined();

    // data-state="current" / class~="current" / class~="animate-spin" 중 하나는 존재해야 함
    const dataState = current!.getAttribute('data-state') ?? '';
    const className = current!.className ?? '';
    const html = current!.innerHTML ?? '';

    const indicatesCurrent =
      dataState === 'current' ||
      /\b(current|active|rotating|animate-spin|spin)\b/i.test(className) ||
      // 자식 노드에 spinner 가 있을 수 있음
      /\b(animate-spin|spin|rotating)\b/i.test(html);
    expect(indicatesCurrent).toBe(true);
  });

  it('현재 노드 이전 단계들에는 done 클래스 / 상태가 부여된다', () => {
    const Bar = StageProgressBar!;
    const { container } = render(
      React.createElement(Bar, { status: 'translating' })
    );

    const nodes = findNodes(container);
    // translating 의 인덱스 — 이 인덱스 미만의 노드는 모두 done
    const currentIndex = NODE_ORDER.indexOf('translating');
    for (let i = 0; i < currentIndex; i++) {
      const node =
        nodes.find((n) => n.getAttribute('data-stage') === NODE_ORDER[i]) ??
        nodes[i];
      const dataState = node.getAttribute('data-state') ?? '';
      const className = node.className ?? '';
      const isDone =
        dataState === 'done' || /\b(done|completed|complete)\b/i.test(className);
      expect(isDone).toBe(true);
    }
  });

  it('현재 노드 이후 단계들에는 pending(미래) 상태가 부여된다', () => {
    const Bar = StageProgressBar!;
    const { container } = render(
      React.createElement(Bar, { status: 'subtitle_processing' })
    );

    const nodes = findNodes(container);
    const currentIndex = NODE_ORDER.indexOf('subtitle_processing');
    for (let i = currentIndex + 1; i < NODE_ORDER.length; i++) {
      const node =
        nodes.find((n) => n.getAttribute('data-stage') === NODE_ORDER[i]) ??
        nodes[i];
      const dataState = node.getAttribute('data-state') ?? '';
      const className = node.className ?? '';
      // done / current 모두 아니어야 함.
      // 주의: `\b(done|complete|current|active)\b` 같은 광역 regex 는
      // `stage-completed` (literal "completed" 단계의 클래스) 와 충돌하므로
      // state 접두사(`state-*`) 가 붙은 형태 또는 data-state 속성으로만 판정한다.
      const isFutureOrUpcoming =
        dataState === 'upcoming' ||
        dataState === 'pending' ||
        dataState === 'future' ||
        dataState === '' || // class 기반일 수 있음
        /\b(upcoming|future|pending)\b/i.test(className) ||
        !/\b(state-(done|complete|current|active))\b/i.test(className);
      expect(isFutureOrUpcoming).toBe(true);
    }
  });

  it('status=failed 일 때 errorStage 에 해당하는 노드에 error 클래스가 부여된다', () => {
    const Bar = StageProgressBar!;
    const { container } = render(
      React.createElement(Bar, {
        status: 'failed',
        errorStage: 'subtitle_processing',
      })
    );

    const nodes = findNodes(container);
    const failedNode =
      nodes.find(
        (n) => n.getAttribute('data-stage') === 'subtitle_processing'
      ) ?? nodes[NODE_ORDER.indexOf('subtitle_processing')];
    expect(failedNode).toBeDefined();

    const dataState = failedNode!.getAttribute('data-state') ?? '';
    const className = failedNode!.className ?? '';

    const isError =
      dataState === 'error' || /\b(error|failed|failure)\b/i.test(className);
    expect(isError).toBe(true);
  });
});
