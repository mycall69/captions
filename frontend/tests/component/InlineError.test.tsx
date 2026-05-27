/**
 * T122: InlineError 컴포넌트 테스트.
 *
 * 검증 항목:
 *   1. 한국어 message 가 그대로 렌더링된다 (헌법 V).
 *   2. `code` 를 전달하면 `data-error-code` 속성과 텍스트에 노출된다.
 *   3. `role="alert"` 가 부여되어 스크린리더가 즉시 읽도록 한다.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';

import { InlineError } from '@/components/feedback/InlineError';

describe('InlineError', () => {
  it('한국어 message 를 렌더링한다', () => {
    render(<InlineError message="URL 형식이 올바르지 않습니다." />);
    expect(screen.getByText('URL 형식이 올바르지 않습니다.')).toBeTruthy();
  });

  it('role="alert" 속성이 부여된다', () => {
    render(<InlineError message="잠시 후 다시 시도해 주세요." />);
    const alert = screen.getByRole('alert');
    expect(alert).toBeTruthy();
  });

  it('code 를 전달하면 data-error-code 속성과 텍스트에 노출한다', () => {
    render(<InlineError message="요청이 너무 많습니다." code="RATE_LIMITED" />);
    const alert = screen.getByTestId('inline-error');
    expect(alert.getAttribute('data-error-code')).toBe('RATE_LIMITED');
    expect(alert.textContent).toContain('RATE_LIMITED');
  });

  it('code 미전달 시 data-error-code 가 비어 있다', () => {
    render(<InlineError message="알 수 없는 오류" />);
    const alert = screen.getByTestId('inline-error');
    // attribute 자체가 없거나 빈 문자열이어야 한다.
    const code = alert.getAttribute('data-error-code');
    expect(code === null || code === '').toBe(true);
  });
});
