/**
 * 헌법 VI(Always-On Logging) — Next.js 서버가 처리한 모든 HTTP 요청을
 * `logs/frontend/access.log` 에 한 줄로 기록한다.
 *
 * 구조:
 * - 본 middleware 는 Edge runtime 기본값으로 실행되어 파일시스템에 직접 접근할 수 없으므로,
 *   요청 메타데이터를 `/api/internal/access-log` 라우트(Node runtime)에 fire-and-forget POST
 *   하여 위임한다.
 * - 무한 루프 회피를 위해 `/api/internal/access-log` 경로 자체는 기록하지 않는다.
 *
 * 한계 (후속 개선):
 * - middleware 는 실제 응답 status / 총 처리 시간을 알 수 없다 → status=200(best-effort),
 *   duration_ms=middleware 자체 처리 시간만 기록. 정확한 값이 필요하면 reverse proxy
 *   (예: nginx access log) 또는 Next.js custom server 도입 검토.
 */

import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const INTERNAL_LOG_PATH = '/api/internal/access-log';

export async function middleware(request: NextRequest): Promise<NextResponse> {
  const url = request.nextUrl;

  // self-loop 방지: 로그 적재 endpoint 자체는 기록하지 않는다.
  if (url.pathname === INTERNAL_LOG_PATH) {
    return NextResponse.next();
  }

  const start = Date.now();
  const requestId = request.headers.get('x-request-id') ?? crypto.randomUUID();
  const response = NextResponse.next();
  response.headers.set('x-request-id', requestId);

  const payload = {
    timestamp: new Date().toISOString(),
    method: request.method,
    path: url.pathname + url.search,
    status: 200, // middleware 는 실제 응답 status 를 모름 (best-effort)
    duration_ms: Date.now() - start,
    request_id: requestId,
    referrer: request.headers.get('referer') ?? '',
    user_agent: request.headers.get('user-agent') ?? '',
  };

  // fire-and-forget — 로그 적재 실패가 사용자 요청을 방해하지 않도록 한다.
  void fetch(`${url.origin}${INTERNAL_LOG_PATH}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  }).catch(() => {
    // swallow — 로깅 실패는 silently 무시
  });

  return response;
}

export const config = {
  matcher: [
    // 정적 자산·favicon 은 제외하고 모든 페이지/RSC/api 요청을 캡처한다.
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|map)$).*)',
  ],
};
