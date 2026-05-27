/**
 * T114: US3 최근 작업 재방문 — Playwright e2e
 *
 * User Story 3 인수 시나리오 (spec.md §US3, FR-029, FR-030, FR-004):
 *   - S1 메인 페이지에 최근 작업 목록(최대 5건)이 노출된다.
 *   - 완료 항목을 클릭하면 S3(/jobs/:id) 재생 페이지로 진입한다.
 *   - 빈 상태에서는 EmptyState 안내 문구가 노출된다.
 *
 * 본 테스트는 GET /v1/jobs API mock 으로 가짜 작업 1건(completed) 을 주입한 뒤
 * 클릭 시 /jobs/:id 라우팅을 검증한다. S3 의 비디오 player 렌더링은 별도
 * US1 e2e 가 다루므로 여기서는 URL 변화로 라우팅만 검증한다.
 */
import { test, expect } from '@playwright/test';

const SAMPLE_JOB_ID = '01KSAMPLEJOB0000000000000A';

test.describe('US3: 최근 작업 재방문 (P3 acceptance)', () => {
  test(
    '최근 작업 목록에서 완료 항목 클릭 시 /jobs/:id 로 이동한다',
    async ({ page }) => {
      // 1) GET /v1/jobs (목록) — completed 1건
      await page.route('**/v1/jobs**', async (route) => {
        const url = route.request().url();
        const method = route.request().method();
        // POST 는 fallthrough — S1 의 URL 입력 핸들러는 본 테스트에서 사용하지 않음.
        // GET /v1/jobs (정확 매칭 — query string 만 있을 수 있다) 만 응답한다.
        const isListGet =
          method === 'GET' && /\/v1\/jobs(\?|$)/.test(url);
        if (!isListGet) {
          await route.fallback();
          return;
        }
        await route.fulfill({
          json: {
            success: true,
            data: {
              items: [
                {
                  id: SAMPLE_JOB_ID,
                  source_url: 'https://www.youtube.com/watch?v=abcdefghijk',
                  youtube_video_id: 'abcdefghijk',
                  status: 'completed',
                  metadata: {
                    title: '재방문 테스트 영상',
                    channel: '테스트 채널',
                    duration_sec: 754,
                    subtitle_source: 'manual',
                  },
                  created_at: '2026-05-28T00:00:00Z',
                  updated_at: '2026-05-28T00:05:00Z',
                  completed_at: '2026-05-28T00:05:00Z',
                  reused: false,
                },
              ],
              next_cursor: null,
            },
            request_id: 'req-us3-list',
          },
        });
      });

      // 2) S1 진입
      await page.goto('/');

      // 3) 최근 작업 카드의 제목이 노출되어야 한다
      await expect(page.getByText('재방문 테스트 영상')).toBeVisible();

      // 4) "재생" CTA 클릭 → /jobs/:id 라우팅
      await page.getByRole('button', { name: /재생/ }).first().click();
      await expect(page).toHaveURL(new RegExp(`/jobs/${SAMPLE_JOB_ID}`));
    },
  );

  test('최근 작업이 없을 때 EmptyState 안내가 노출된다', async ({ page }) => {
    await page.route('**/v1/jobs**', async (route) => {
      const isListGet =
        route.request().method() === 'GET' &&
        /\/v1\/jobs(\?|$)/.test(route.request().url());
      if (!isListGet) {
        await route.fallback();
        return;
      }
      await route.fulfill({
        json: {
          success: true,
          data: { items: [], next_cursor: null },
          request_id: 'req-us3-empty',
        },
      });
    });

    await page.goto('/');

    // 빈 상태 안내 문구 (와이어프레임 §C3)
    await expect(page.getByText(/아직 처리한 영상이 없습니다|최근 작업이 없습니다/)).toBeVisible();
  });
});
