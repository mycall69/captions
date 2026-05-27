/**
 * T096: US2 progress visibility — Playwright e2e
 *
 * User Story 2 인수 시나리오 (spec.md §US2):
 *   - 진행 중 작업에서 단계 전이 / 진행률이 SSE 로 푸시되어 UI 가 페이지 리로드 없이 갱신된다.
 *   - 실패 이벤트(`job.failed`) 수신 시 FailurePanel 이 사유와 함께 노출된다.
 *
 * 본 테스트는 `app/jobs/[id]/page.tsx` 가 SSE 구독을 통합한 뒤(T101+) 활성화된다.
 * T104-T111 구현 완료 후 활성화 (test.fixme → test).
 *
 * 와이어프레임 §S2 — StageProgressBar(6노드) + StatusBadge + FailurePanel.
 */
import { test, expect } from '@playwright/test';

const SSE_PATH_PATTERN = /\/v1\/jobs\/.+\/events$/;

test.describe('US2: 작업 진행 상황 실시간 가시화 (P2 acceptance)', () => {
  test(
    'SSE 단계 전이 이벤트가 StageProgressBar 를 페이지 새로고침 없이 갱신한다',
    async ({ page }) => {
      // 1) GET /v1/jobs/<id> 응답 mock — in-progress 상태로 진입하게 한다
      await page.route('**/v1/jobs/*', async (route) => {
        if (route.request().method() !== 'GET') {
          await route.fallback();
          return;
        }
        await route.fulfill({
          json: {
            success: true,
            data: {
              id: 'test-job-id-001',
              source_url: 'https://www.youtube.com/watch?v=abcdefghijk',
              youtube_video_id: 'abcdefghijk',
              status: 'downloading',
              metadata: {
                title: 'Test Video',
                channel: 'Test Channel',
                duration_sec: 120,
                subtitle_source: 'manual',
              },
              created_at: '2026-05-28T00:00:00Z',
              updated_at: '2026-05-28T00:00:00Z',
              reused: false,
            },
            request_id: 'req-001',
          },
        });
      });

      // 2) SSE 스트림 mock — state_changed 4건을 순차 전송
      await page.route(SSE_PATH_PATTERN, async (route) => {
        const body = [
          'id: 1',
          'event: job.state_changed',
          'data: {"job_id":"test-job-id-001","event_id":"01HX2T00000000000000000001","seq":1,"previous_status":"pending","status":"downloading","stage":"downloading","at":"2026-05-28T00:00:01Z","published_at":"2026-05-28T00:00:01Z"}',
          '',
          'id: 2',
          'event: job.state_changed',
          'data: {"job_id":"test-job-id-001","event_id":"01HX2T00000000000000000002","seq":2,"previous_status":"downloading","status":"subtitle_processing","stage":"subtitle_processing","at":"2026-05-28T00:00:05Z","published_at":"2026-05-28T00:00:05Z"}',
          '',
          'id: 3',
          'event: job.state_changed',
          'data: {"job_id":"test-job-id-001","event_id":"01HX2T00000000000000000003","seq":3,"previous_status":"subtitle_processing","status":"translating","stage":"translating","at":"2026-05-28T00:00:10Z","published_at":"2026-05-28T00:00:10Z"}',
          '',
          'id: 4',
          'event: job.state_changed',
          'data: {"job_id":"test-job-id-001","event_id":"01HX2T00000000000000000004","seq":4,"previous_status":"translating","status":"rendering","stage":"rendering","at":"2026-05-28T00:00:15Z","published_at":"2026-05-28T00:00:15Z"}',
          '',
          '',
        ].join('\n');

        await route.fulfill({
          status: 200,
          headers: {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
          },
          body,
        });
      });

      // 3) S2 페이지 진입
      await page.goto('/jobs/test-job-id-001');

      // 4) StageProgressBar 가 렌더링되어야 한다
      const progressBar = page.locator('[data-testid="stage-progress-bar"]');
      await expect(progressBar).toBeVisible();

      // 5) 마지막 이벤트가 도달한 후 rendering 노드가 current 상태여야 한다.
      //    구현체가 data-stage / data-state 또는 class 로 표시할 수 있으므로
      //    "현재 단계" 라벨 텍스트 가시성을 대신 검증한다.
      await expect(page.getByText(/렌더|rendering/i)).toBeVisible();
    },
  );

  test(
    'SSE job.failed 이벤트가 FailurePanel 에 사유와 함께 노출된다',
    async ({ page }) => {
      // 1) GET /v1/jobs/<id> — failed 상태로 응답 mock
      await page.route('**/v1/jobs/*', async (route) => {
        if (route.request().method() !== 'GET') {
          await route.fallback();
          return;
        }
        await route.fulfill({
          json: {
            success: true,
            data: {
              id: 'test-job-id-002',
              source_url: 'https://www.youtube.com/watch?v=abcdefghijk',
              youtube_video_id: 'abcdefghijk',
              status: 'subtitle_processing',
              metadata: {
                title: 'Test Video',
                channel: 'Test Channel',
                duration_sec: 120,
                subtitle_source: null,
              },
              created_at: '2026-05-28T00:00:00Z',
              updated_at: '2026-05-28T00:00:00Z',
              reused: false,
            },
            request_id: 'req-002',
          },
        });
      });

      // 2) SSE — job.failed 이벤트 1건
      await page.route(SSE_PATH_PATTERN, async (route) => {
        const payload = {
          job_id: 'test-job-id-002',
          event_id: '01HX2T00000000000000000010',
          seq: 1,
          status: 'failed',
          error_stage: 'subtitle_processing',
          error_code: 'SUBTITLE_NOT_FOUND',
          error_message: '이 영상에는 한국어 / 일본어 자막이 없습니다.',
          at: '2026-05-28T00:00:30Z',
          published_at: '2026-05-28T00:00:30Z',
        };
        const body = [
          'id: 10',
          'event: job.failed',
          `data: ${JSON.stringify(payload)}`,
          '',
          '',
        ].join('\n');

        await route.fulfill({
          status: 200,
          headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
          body,
        });
      });

      // 3) S2 페이지 진입
      await page.goto('/jobs/test-job-id-002');

      // 4) FailurePanel 가시성 + 사유 / 단계 텍스트 확인
      const failurePanel = page.locator('[data-testid="failure-panel"]');
      await expect(failurePanel).toBeVisible();
      await expect(
        page.getByText('이 영상에는 한국어 / 일본어 자막이 없습니다.'),
      ).toBeVisible();
      await expect(page.getByText(/subtitle_processing|자막/)).toBeVisible();
    },
  );
});
