import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AppHeader } from '@/components/header/AppHeader';

describe('AppHeader', () => {
  it('제품명 텍스트가 렌더링된다', () => {
    render(<AppHeader />);
    // getByText: 매칭 실패 시 예외를 던지므로 별도 matcher 없이 검증 가능
    const heading = screen.getByText('Bilingual Subtitle Studio');
    expect(heading).toBeDefined();
  });

  it('로고 링크가 / 를 가리킨다', () => {
    render(<AppHeader />);
    const links = screen.getAllByRole('link');
    const homeLink = links.find((el: HTMLElement) => el.getAttribute('href') === '/');
    expect(homeLink).toBeDefined();
  });

  it('"새 작업" 버튼이 존재한다', () => {
    render(<AppHeader />);
    const btn = screen.getByText('새 작업');
    expect(btn).toBeDefined();
  });
});
