// MSW node server setup for e2e (used by tests that need to mock the API).
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';

export const handlers = [
  // 기본 핸들러 — 개별 테스트에서 server.use(...)로 덮어쓴다.
];

export const server = setupServer(...handlers);
