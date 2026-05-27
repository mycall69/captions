import { test, expect } from '@playwright/test';

test('홈 화면이 표시된다', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('h1')).toContainText('Bilingual Subtitle Studio');
});
