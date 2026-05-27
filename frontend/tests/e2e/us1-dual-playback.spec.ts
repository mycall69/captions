/**
 * T054: US1 P1 인수 테스트 — dual subtitle 재생 전체 흐름 (Playwright e2e)
 *
 * User Story 1 완전 경로:
 *   YouTube URL 입력 → 처리 완료 → dual subtitle 재생
 *
 * 주의사항:
 *   - 이 테스트는 Phase 3i (UrlInputCard, DualSubtitleOverlay, S1/S3 페이지) 구현 전까지 실패(red) 상태
 *   - 의도적으로 skip/fixme 처리하지 않음 — 명확한 실패가 no-op skip보다 유용한 TDD red 상태
 *   - Phase 3i 구현 완료 후 API mock (page.route) 및 SSE mock을 추가하여 완성할 것
 *
 * 인수 기준 (spec.md §User Story 1):
 *   AC-1: URL 입력 → 처리 시작 → dual subtitle과 함께 재생
 *   AC-3: 자막 토글 (끔 → 사라짐, 켬 → 복원)
 *   AC-4: 언어 표시 순서 전환 (원문↔번역문, 단축키 R)
 */
import { test, expect } from '@playwright/test';

test.describe('US1: dual subtitle 재생 (P1 acceptance)', () => {
  test('YouTube URL → 처리 완료 → dual subtitle 재생', async ({ page }) => {
    // 1. 메인 페이지 진입
    await page.goto('/');

    // 2. URL 입력 — 유효한 YouTube 영상 URL
    const input = page.getByRole('textbox');
    await input.fill('https://www.youtube.com/watch?v=abcdefghijk');

    // 3. "시작" 버튼 클릭
    await page.getByRole('button', { name: /시작/ }).click();

    // 4. 작업 상세 페이지(/jobs/:id)로 라우팅 확인
    await expect(page).toHaveURL(/\/jobs\//);

    // 5. 처리 완료 대기 — e2e 환경에서는 page.route()로 API mock을 적용해 즉시 completed 전이
    //    Phase 3i 구현 시 아래 mock을 추가한다:
    //
    //    await page.route('**/api/jobs/**', async (route) => {
    //      await route.fulfill({
    //        json: { id: 'test-job-id', status: 'completed', ... }
    //      });
    //    });
    //
    //    SSE mock (EventSource):
    //    await page.route('**/api/jobs/**/events', async (route) => {
    //      await route.fulfill({
    //        headers: { 'Content-Type': 'text/event-stream' },
    //        body: 'data: {"type":"status_changed","status":"completed"}\n\n',
    //      });
    //    });

    // 6. 재생 가능 상태 진입 확인 — 자막 컨트롤 버튼 노출 대기
    await expect(page.getByRole('button', { name: /자막/ })).toBeVisible({ timeout: 10000 });

    // 7. Dual subtitle overlay 확인
    const overlay = page.locator('[data-testid="dual-subtitle-overlay"]');
    await expect(overlay).toBeVisible();

    // 8. 자막 토글 테스트 (AC-3) — 단축키 S
    await page.keyboard.press('s');
    await expect(overlay).toBeHidden();

    // 자막 다시 켜기
    await page.keyboard.press('s');
    await expect(overlay).toBeVisible();

    // 9. 언어 순서 전환 테스트 (AC-4) — 단축키 R
    //    source-first (원문 위) → target-first (번역문 위)
    const lines = page.locator('[data-testid="dual-line"]');
    await expect(lines).toHaveCount(2);

    // 순서 전환 전 첫 번째 줄 텍스트 저장
    const firstLineBeforeSwap = await lines.nth(0).textContent();

    await page.keyboard.press('r');

    // 순서 전환 후 첫 번째 줄이 바뀌어야 함
    const firstLineAfterSwap = await lines.nth(0).textContent();
    expect(firstLineAfterSwap).not.toBe(firstLineBeforeSwap);
  });

  test('유효하지 않은 URL 입력 시 오류 메시지가 표시되고 작업이 생성되지 않는다', async ({
    page,
  }) => {
    // 1. 메인 페이지 진입
    await page.goto('/');

    // 2. 유효하지 않은 URL 입력
    const input = page.getByRole('textbox');
    await input.fill('https://google.com/not-youtube');

    // 3. "시작" 버튼이 비활성화 상태이거나 클릭 시 오류를 표시해야 함
    const button = page.getByRole('button', { name: /시작/ });

    // 버튼이 비활성화되어 있으면 오류 메시지가 이미 표시 중
    const isDisabled = await button.isDisabled();
    if (!isDisabled) {
      await button.click();
    }

    // 4. 페이지 URL이 변경되지 않아야 함 (작업 미생성)
    await expect(page).toHaveURL('/');

    // 5. 오류 메시지 또는 비활성화 상태 확인
    const hasError =
      isDisabled ||
      (await page.locator('[role="alert"], [aria-live="assertive"]').count()) > 0;
    expect(hasError).toBe(true);
  });

  test('자막 없는 영상 처리 시 사용자 친화적 실패 메시지가 표시된다', async ({ page }) => {
    // 1. 메인 페이지 진입
    await page.goto('/');

    // 2. 자막 없는 영상 URL 입력 (API mock으로 failed 응답을 반환)
    //    Phase 3i에서 page.route()로 mock을 추가할 것
    const input = page.getByRole('textbox');
    await input.fill('https://www.youtube.com/watch?v=no-subtitle-video');
    await page.getByRole('button', { name: /시작/ }).click();

    // 3. 처리 실패 후 실패 메시지 확인 (spec.md Edge Case 참조)
    //    - "자막을 찾을 수 없습니다" 또는 유사한 한국어 메시지
    await expect(page).toHaveURL(/\/jobs\//);
    // 실패 사유 메시지 대기 (timeout: 10초)
    await expect(page.getByText(/자막|실패|찾을 수 없/)).toBeVisible({ timeout: 10000 });
  });
});
