/**
 * 헌법 VI(Always-On Logging) — Edge middleware 에서 fire-and-forget POST 로 전달된
 * access log 페이로드를 `logs/frontend/access.log` 에 한 줄(JSON) append 한다.
 *
 * Node runtime 전용 (fs 접근). 다른 라우트가 본 경로를 호출하지 못하도록 middleware 가
 * 자기 자신 경로를 skip 처리한다.
 *
 * 시크릿 마스킹: payload 키 중 api_key/oauth_token/authorization/password/secret/token
 * 정규식과 일치하는 키는 ***REDACTED*** 로 치환 후 적재한다.
 */

import { promises as fs } from 'node:fs';
import path from 'node:path';
import { NextResponse } from 'next/server';

export const runtime = 'nodejs';
// 본 로그 적재는 항상 동적이므로 캐시/정적 분석 회피.
export const dynamic = 'force-dynamic';

// 저장소 루트 / logs / frontend / access.log — `frontend/` 가 cwd 라고 가정.
const LOG_FILE = path.resolve(process.cwd(), '..', 'logs', 'frontend', 'access.log');

const SECRET_KEY_RE = /^(api[_-]?key|oauth[_-]?token|authorization|password|secret|token)$/i;
const MASK = '***REDACTED***';

function maskSecrets(obj: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    out[k] = SECRET_KEY_RE.test(k) ? MASK : v;
  }
  return out;
}

export async function POST(req: Request): Promise<NextResponse> {
  try {
    const raw = (await req.json()) as Record<string, unknown>;
    const safe = maskSecrets(raw);
    const line = `${JSON.stringify(safe)}\n`;
    await fs.mkdir(path.dirname(LOG_FILE), { recursive: true });
    await fs.appendFile(LOG_FILE, line, 'utf-8');
  } catch {
    // 로깅 실패는 swallow — 사용자 요청 흐름에 영향 없음
  }
  return NextResponse.json({ ok: true });
}
