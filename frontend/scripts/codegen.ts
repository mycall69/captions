/**
 * OpenAPI → TypeScript 타입 생성 스크립트
 *
 * 직접 실행 방법: npx tsx scripts/codegen.ts
 * npm 스크립트: npm run codegen
 *
 * 입력: ../specs/001-dual-subtitle-mvp/contracts/openapi.yaml
 * 출력: lib/api/types.gen.ts
 */
import { spawnSync } from 'node:child_process';

const SPEC = '../specs/001-dual-subtitle-mvp/contracts/openapi.yaml';
const OUT = 'lib/api/types.gen.ts';

console.log(`[codegen] 입력: ${SPEC}`);
console.log(`[codegen] 출력: ${OUT}`);

const result = spawnSync('npx', ['openapi-typescript', SPEC, '-o', OUT], { stdio: 'inherit' });
process.exit(result.status ?? 1);
