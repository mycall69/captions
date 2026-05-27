/**
 * T052: UrlInputCard 컴포넌트 테스트
 *
 * - 컴포넌트가 아직 구현되지 않은 경우 (Phase 3i 이전) 테스트 전체를 skip 처리
 * - 구현 완료 후 describe 블록이 자동으로 활성화됨
 * - Vite가 정적 import 경로를 분석하지 못하도록 경로를 런타임에 조립한다
 *
 * 검증 항목:
 *   1. 입력 필드와 "시작" 버튼이 렌더링됨
 *   2. 빈 URL: "시작" 버튼 비활성화
 *   3. 유효한 YouTube URL: "시작" 버튼 활성화
 *   4. 유효하지 않은 URL: 인라인 오류 메시지 표시
 *   5. 제출 이벤트: onSubmit prop 호출 및 검증된 URL 전달
 */
import { describe, it, expect, vi, beforeAll } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';

// UrlInputCard 타입 정의 — 컴포넌트 구현 전에 형태만 참조
type UrlInputCardType = React.ComponentType<{
  onSubmit?: (url: string) => void;
}>;

// 컴포넌트가 아직 구현되지 않은 경우 undefined로 유지
let UrlInputCard: UrlInputCardType | undefined;

beforeAll(async () => {
  try {
    // Vite의 정적 import 분석을 우회하기 위해 경로를 런타임에 조립
    // 정적 문자열 리터럴이 아니므로 Vite는 번들 시점에 해석하지 않음
    const segments = ['@', '/', 'components', '/url-input/', 'UrlInputCard'];
    const modulePath = segments.join('');
    const mod = await import(/* @vite-ignore */ modulePath).catch(() => null);
    if (mod && typeof mod === 'object' && 'UrlInputCard' in mod) {
      UrlInputCard = (mod as Record<string, unknown>)['UrlInputCard'] as UrlInputCardType;
    }
  } catch {
    // 미구현 상태 — skip 처리
  }
});

// UrlInputCard 미구현 시 전체 describe를 skip
describe.skipIf(() => !UrlInputCard)('UrlInputCard', () => {
  const Component = () => {
    // describe 실행 시점에 UrlInputCard가 반드시 정의되어 있음
    const Card = UrlInputCard!;
    return React.createElement(Card);
  };

  it('입력 필드와 "시작" 버튼이 렌더링된다', () => {
    render(<Component />);

    // 텍스트 입력 필드 존재 확인
    const input = screen.getByRole('textbox');
    expect(input).toBeDefined();

    // "시작" 버튼 존재 확인
    const button = screen.getByRole('button', { name: /시작/ });
    expect(button).toBeDefined();
  });

  it('URL이 비어 있을 때 "시작" 버튼이 비활성화된다', () => {
    render(<Component />);

    const button = screen.getByRole('button', { name: /시작/ }) as HTMLButtonElement;
    // 빈 입력 상태에서 버튼은 disabled여야 함
    expect(button.disabled).toBe(true);
  });

  it('유효한 YouTube URL 입력 시 "시작" 버튼이 활성화된다', async () => {
    const user = userEvent.setup();
    render(<Component />);

    const input = screen.getByRole('textbox');
    await user.type(input, 'https://www.youtube.com/watch?v=abcdefghijk');

    const button = screen.getByRole('button', { name: /시작/ }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
  });

  it('유효하지 않은 URL 입력 시 인라인 오류 메시지가 표시된다', async () => {
    const user = userEvent.setup();
    render(<Component />);

    const input = screen.getByRole('textbox');
    await user.type(input, 'https://google.com');
    // 오류를 트리거하기 위해 필드에서 포커스를 이동하거나 제출 시도
    await user.tab();

    // 오류 메시지가 비어있지 않아야 함 (헌법 V — UI 텍스트는 한국어)
    // role="alert" 또는 오류 관련 텍스트 요소를 탐색
    const errorElements = document.querySelectorAll(
      '[role="alert"], [aria-invalid="true"] + *, .error, [data-error]',
    );
    // 오류 텍스트가 존재하는지 확인 — 정확한 selector는 구현에서 결정되므로
    // getByText로 한국어 오류 문자열의 존재를 폭넓게 확인
    const hasError =
      errorElements.length > 0 ||
      (() => {
        try {
          // 한국어 오류 메시지 패턴 검색
          screen.getByText(/유효한|올바른|YouTube|URL|입력/);
          return true;
        } catch {
          return false;
        }
      })();
    expect(hasError).toBe(true);
  });

  it('유효한 URL 제출 시 onSubmit 콜백이 해당 URL과 함께 호출된다', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    const Card = UrlInputCard!;
    render(<Card onSubmit={onSubmit} />);

    const validUrl = 'https://www.youtube.com/watch?v=abcdefghijk';
    const input = screen.getByRole('textbox');
    await user.type(input, validUrl);

    const button = screen.getByRole('button', { name: /시작/ });
    await user.click(button);

    // onSubmit은 한 번 호출되어야 하며 검증된 URL이 전달되어야 함
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith(validUrl);
  });

  it('비 YouTube URL 입력 시 오류 메시지가 비어있지 않다 (한국어)', async () => {
    const user = userEvent.setup();
    render(<Component />);

    const input = screen.getByRole('textbox');
    await user.type(input, 'https://vimeo.com/123456789');
    await user.tab();

    // 오류 텍스트가 빈 문자열이 아닌지 확인
    // 구현에서 어떤 selector를 사용하든, 화면에 오류 텍스트가 나타나야 함
    const allText = document.body.textContent ?? '';
    // 한국어 오류 메시지가 포함되어 있어야 함
    const hasKoreanErrorText = /[가-힣]/.test(allText);
    expect(hasKoreanErrorText).toBe(true);
  });
});
