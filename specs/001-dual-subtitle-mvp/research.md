# Research: Dual Subtitle MVP

**Feature**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md)

**Created**: 2026-05-27

본 문서는 plan에서 등장하는 모든 기술적 결정에 대한 **선택지·근거·대안**을 기록한다.
각 결정은 "Decision / Rationale / Alternatives considered" 형식이며 헌법 게이트에
대응하는 항목을 포함한다.

## 1. Celery 브로커 선택 (Redis)

**Decision**: Redis 7.x를 브로커 + 결과 백엔드로 사용. Homebrew(`brew install redis`)로
설치, `brew services start redis`로 데몬 실행.

**Rationale**:
- 헌법 IV(Docker 금지) + macOS 네이티브 운영. Redis는 brew 패키지로 단일 명령 설치.
- Celery 공식 권장 브로커이며 메시지 손실·재시도·우선순위 모두 안정 지원.
- Redis Pub/Sub을 SSE 이벤트 fan-out 채널로 재사용 가능(이벤트 버스 별도 운영 불요).
- 결과 백엔드를 Redis로 두면 task 상태 조회가 일관됨(SQLite 결과 백엔드는 lock 경합 위험).

**Alternatives considered**:
- **RabbitMQ**: 기능 풍부하나 brew 설정·관리 부담 큼. 라우팅 패턴이 필요하지 않은 MVP에는 과대.
- **SQLite/Filesystem 브로커(Celery 지원)**: lock 경합·이벤트 fan-out 부재. SQLite를 브로커로 사용하면 헌법 II(Queue-Based)와 충돌 가능.
- **Redis Streams**: 본 MVP의 chain/chord 패턴은 Celery 기본 큐 + Pub/Sub로 충분. Streams 도입은 후속 확장에서 재검토.

## 2. 실시간 상태 전달 (SSE)

**Decision**: 작업 상태/진행률은 **Server-Sent Events (SSE)** 로 전달. 엔드포인트
`GET /v1/jobs/{id}/events`. 워커는 상태 변경 시 Redis Pub/Sub 채널 `job:{id}`에 publish하고,
FastAPI SSE 핸들러가 구독하여 클라이언트로 push.

**Rationale**:
- 한 방향 push만 필요 — WebSocket 양방향 기능 불필요.
- HTTP/1.1 호환, 프록시·브라우저 native 지원, 자동 재연결 내장.
- TanStack Query와 결합해 부분 invalidate 패턴 단순.
- 헌법 II(stateless API)와 자연 부합: SSE 핸들러는 구독 후 stream 종료까지만 상태 보유.

**Alternatives considered**:
- **WebSocket**: 과한 양방향 기능. 라이브러리 의존 추가.
- **Long polling**: SC-002(5초 이내) 만족 가능하나 트래픽 비효율.
- **Short polling**: 가장 단순하나 N개 작업·N개 브라우저 탭 환경에서 부하 누적.

**Fallback**: SSE 연결 끊김 또는 미지원 환경에서는 자동으로 5초 폴링으로 degrade(클라이언트 hook).

## 3. SQLite 동시성 (WAL + 직렬화)

**Decision**: SQLite WAL 모드 활성화. async SQLAlchemy + `aiosqlite`. 쓰기는 단일
**Repository 계층**을 통해 직렬화(트랜잭션 짧게 유지). 워커는 task 단위로 새 connection 생성.

**Rationale**:
- 헌법 — SQLite-specific SQL 금지지만 PRAGMA(`journal_mode=WAL`) 설정은 portable 범주.
- WAL이면 다중 reader + 단일 writer 동시성 확보, MVP의 N=2 워커 + API 1프로세스 부하에 충분.
- 쓰기 직렬화 패턴은 PostgreSQL 이주 시 그대로 사용 가능.

**Alternatives considered**:
- **즉시 PostgreSQL 도입**: 헌법은 SQLite First. brew + 추가 운영 부담. MVP 단계는 과한 선택.
- **SQLite + `BEGIN IMMEDIATE`** 광범위 사용: lock 점유 시간 증가. 짧은 트랜잭션 가이드가 더 적합.

## 4. 워커 파이프라인 위상 (Celery chain + 단계별 task)

**Decision**: Celery `chain(download → extract_subtitles → translate → render)`. 각 단계는
**독립 task**이며 자체 retry 정책을 가진다. 단계 시작/완료 시 도메인 서비스를 통해 DB 상태
전이와 이벤트 publish를 수행.

**Rationale**:
- 단계마다 idempotent 보장 (입력=job_id, 출력=DB/파일시스템 상태).
- 한 단계 실패가 후속 단계 자동 취소로 이어짐(`link_error` + chain 전파).
- 단계별 retry·취소·재시작 정책을 자연스럽게 분리.

**Alternatives considered**:
- **단일 god task**: 헌법 III(giant file/모듈 금지) 위반.
- **chord(병렬 다운로드·자막 추출)**: 자막 메타 의존성으로 인해 직렬이 더 단순. 후속 확장 시 chord 도입 여지.
- **외부 워크플로 엔진(Temporal/Prefect)**: MVP 과대 설계.

## 5. 번역 청크 정책 (60초 윈도우 + context 패딩)

**Decision**: 시간축 기준 60초 윈도우로 cue 묶음 구성. cue 경계 보존(중간 자르기 금지).
각 청크 호출 시 **직전·직후 각 3 cue**를 `context_before`, `context_after`로 함께
전달하되 번역 결과에는 포함하지 않는다.

**Rationale**:
- 60초는 일반적 LLM 컨텍스트 활용에 안전한 길이이며 SC-001(15분 ≤ 10분)을 만족하기 위해
  병렬 호출 N=2 정도면 충분.
- context 패딩으로 화자 일관성·문맥 보존(헌법 — context-preserving translation).
- chunk 입력·결과는 콘텐츠 해시로 결정성을 갖추므로 캐시 적중 가능.

**Alternatives considered**:
- **cue 단위(1줄씩)**: 호출 폭증·문맥 단절.
- **전체 자막 일괄**: 토큰 한도 초과 위험, 재시도 비용 큼, 부분 실패 불가.
- **문장 경계 기반(NLP segmentation)**: ja/ko 모두 segmentation 정확도 편차 큼. MVP에는 과한 복잡도.

## 6. TranslationProvider Protocol

**Decision**: Python `typing.Protocol`로 정의. 단일 메서드 `translate_chunk(...)`만 노출.
adapter는 `app/infrastructure/providers/claude_adapter.py`에서 Anthropic SDK 직접 사용.
도메인·태스크는 Protocol에만 의존.

```python
class TranslationProvider(Protocol):
    async def translate_chunk(
        self,
        source_lang: Lang,
        target_lang: Lang,
        cues: list[SubtitleCue],
        context_before: list[SubtitleCue],
        context_after: list[SubtitleCue],
    ) -> TranslatedChunk: ...
```

**Rationale**:
- 헌법 — Translation Provider Abstraction NON-NEGOTIABLE.
- ABC가 아닌 Protocol을 택해 duck-typing 친화, 테스트의 `FakeTranslationProvider` 작성이 쉬움.
- 단일 메서드 → 변경 비용 최소. 메서드가 늘면 어댑터 부담 증가.

**Alternatives considered**:
- **ABC + 다중 메서드(estimate_cost, list_models 등)**: provider 차이 노출, 헌법 II(SoC) 위반.
- **함수 기반 콜백**: 어댑터 상태(rate limiter, 캐시 핸들)를 보관하기 불편.

## 7. ffmpeg 사용 범위 (MVP는 컨테이너 변환만, soft subtitle)

**Decision**: MVP는 **하드 자막 burn-in 미사용**. yt-dlp가 산출한 mp4를 그대로 서빙(필요 시
ffmpeg `-c copy` remux). dual subtitle은 SRT/VTT 파일로 별도 산출되어 다운로드 가능하며,
브라우저에서는 두 언어 cue 배열을 받아 `DualSubtitleOverlay`가 클라이언트 측 overlay로
표시한다.

**Rationale**:
- 헌법은 hard / soft 둘 다 지원해야 함을 명시했으나 MVP에서는 **soft가 충분**하고 burn-in은
  렌더 시간·디스크 사용량·실패 지점을 크게 늘림(SC-001 위협).
- 브라우저 overlay는 토글·순서 전환을 즉시 처리하기에 UX가 더 우수(US1-3·US1-4).
- ffmpeg 호출 표면이 좁아져 헌법 보안 FR-033 위반 가능성 감소.

**Alternatives considered**:
- **항상 burn-in**: 처리 시간 ↑, 토글 불가(매번 재렌더 필요).
- **mp4 sidecar VTT track**: HTML5 `<track>`은 단일 언어 cue만 표시 가능, 두 줄 합성 정책이
  브라우저별로 상이 → 자체 overlay가 더 안정적.

**Future expansion**: hard subtitle 옵션은 ADR `0002-hardsub-render.md`(미작성)에서 다룸.

## 8. dual subtitle 파일 형식 (cue별 두 줄)

**Decision**: 다운로드용 dual SRT/VTT는 **하나의 cue 안에 두 줄**(원문/번역)로 구성.
순서(`source-first` / `target-first`)는 다운로드 query parameter로 결정. VTT는 `WEBVTT`
헤더 + cue 한 블록 안에 줄바꿈으로 두 줄 작성.

**Rationale**:
- 미디어 플레이어 일반 호환성 보장(VLC, MPV, 외부 플레이어가 두 줄을 그대로 렌더).
- VTT의 CSS class를 통한 라인별 스타일링은 후속 확장에서 도입.

**Alternatives considered**:
- **두 트랙 파일 동시 다운로드**: 사용자가 외부 플레이어에 두 트랙을 결합하기 번거롭다.
- **ASS/SSA**: 스타일링은 풍부하지만 호환성 / 라이브러리 부담 증가.

## 9. URL 검증 정책

**Decision**: 도메인 allowlist + 영상 ID 추출 검증.
- 허용 host: `www.youtube.com`, `youtube.com`, `m.youtube.com`, `youtu.be`
- `v=` query 또는 `youtu.be/<id>` 경로에서 11자 ID 추출 가능해야 함.
- playlist (`list=...`) 파라미터는 무시(MVP는 단일 영상). 명시적 playlist URL(`/playlist?list=...`)은 거절.

**Rationale**:
- 헌법 보안 FR-031/032. 임의 URL 허용 시 yt-dlp가 다른 사이트로 빠질 위험.

**Alternatives considered**:
- **자유 URL + yt-dlp 위임**: 신뢰 표면 확대, 헌법 위반.
- **정규식 한 줄로 검증**: edge case(시간 파라미터 `t=`, 모바일 URL) 누락 가능.

## 10. 동일 URL 재요청 처리

**Decision**: `POST /v1/jobs`는 영상 ID 정규화 후 다음 분기:
1. 동일 ID의 `completed` 작업이 존재 → `200 OK` + `{ data: { job_id, reused: true } }` 반환.
2. 동일 ID의 진행 중 작업이 존재 → `409 Conflict` 대신 `200 OK` + `{ data: { job_id, reused: true } }` 반환(현재 작업으로 안내).
3. 그 외 → `201 Created` 신규 작업.

**Rationale**:
- 사용자 관점에서 "이미 있다 → 그곳으로 이동"이 가장 직관적(FR-004 + Edge Case).
- 409는 클라이언트가 별도 분기 처리해야 하므로 UX 부담 증가.

**Alternatives considered**:
- **항상 신규 처리**: FR-004 위반.
- **완료작업만 재사용, 진행 중은 409**: 동일 결과를 두 경로로 처리하게 됨. 일관성 저하.

## 11. 자막 cue 저장 형태 (DB row vs 파일)

**Decision**: `subtitle_cue` 테이블에 **행 단위로 저장**. 한 트랙당 보통 100~3000행.
원문·번역 트랙 각각 별 트랙 ID 보유. 추가로 원본 SRT/VTT 파일은 `var/storage/<job_id>/`에
보존(재현/디버깅용).

**Rationale**:
- API가 cue 범위 페이지네이션·seek 기반 조회를 수행할 수 있어 UI(자막 미리보기 리스트, 클릭하여 seek)에 직접 도움.
- SQLite는 수천~수만 행 부담 없음.
- 헌법 — 미디어 산출물은 파일시스템, 메타데이터는 DB라는 분리를 유지.

**Alternatives considered**:
- **JSON blob 컬럼**: 페이지네이션·검색 제약.
- **파일만 보관 + API에서 매번 파싱**: 비효율.

## 12. 캐시 전략

**Decision**: 번역 청크 결과를 Redis에 캐시. 키는 `tx:{sha256(source_lang+target_lang+normalized_text)}`.
TTL 7일. cache hit 시 provider 호출을 생략하고 결과만 DB에 기록.

**Rationale**:
- 동일/유사 콘텐츠 재처리(예: 영상 자막의 동일 인트로)에서 비용·시간 절감.
- Redis가 이미 운용 중이므로 추가 인프라 없음.
- 결정성: chunk 콘텐츠 해시 기반이라 정확한 일치만 허용 → 안전.

**Alternatives considered**:
- **DB 테이블 캐시**: 쓰기 부하 증가, lock 경합 우려.
- **캐시 미사용**: MVP 단순화엔 좋으나 비용·시간 측면에서 손실 큼.

## 13. 로깅·관찰성

**Decision**: structlog 채택. 모든 로그는 JSON 라인 출력. 필수 필드: `ts, level, msg, request_id, job_id, task_id, stage, error_code`. FastAPI 미들웨어가 `request_id`를 부여하고
컨텍스트 변수에 주입. Celery는 task 시작 시 동일 컨텍스트 propagate.

**Rationale**:
- 헌법 — structured logging 필수.
- JSON 출력은 후속 stack(Vector/Loki 등) 도입 시 그대로 활용 가능.

**Alternatives considered**:
- **표준 logging 텍스트 포맷**: 검색·필터 비효율.
- **OpenTelemetry tracing 즉시 도입**: 가치 있으나 MVP 범위 외. 후속 확장.

## 14. 인증·테넌시

**Decision**: MVP는 인증 없음. 모든 작업은 단일 호스트의 공용 컨텍스트. 헌법 FR-035의
rate limit은 client IP 기준.

**Rationale**:
- spec Assumptions(인증 없음)과 정합. 추후 로그인 도입 시 `user_id` 컬럼만 추가하면 됨(데이터 모델에 nullable 슬롯 예약).

**Alternatives considered**:
- **익명 토큰**: 후속 확장. MVP에는 과한 설계.

## 15. 테스트 fixture 영상/자막

**Decision**: 저작권 안전한 짧은 fixture 자막 파일을 `backend/tests/fixtures/subtitles/`
에 직접 보관. 실제 yt-dlp 호출은 단위/통합 테스트에서 mock하고, 한 개의 end-to-end smoke
테스트만 실제 네트워크를 사용한다(CI는 default skip, 로컬 검증 시 환경변수로 활성화).

**Rationale**:
- 외부 네트워크 의존성을 일상 테스트에서 제거(헌법 — 테스트 신뢰성).
- fixture만으로 SC-004(±200ms 정렬) 검증 가능.

**Alternatives considered**:
- **항상 실제 호출**: 네트워크·저작권 리스크.
- **vcrpy로 응답 녹화**: yt-dlp 출력은 동적이며 외부 시스템 응답 변동성이 커서 노후화 우려.

---

## 16. Clarification 결정 (Session 2026-05-27)

`/speckit-clarify` 1차 세션에서 확정된 5건의 결정. 각 항목은 [spec.md §Clarifications](./spec.md#clarifications)의 Q&A를 ADR 풍으로 정리한 것이며, 해당 결정이 plan / tasks / contracts에 어떻게 반영되었는지를 추적한다.

### 16.1 번역 어조(register) 보존

**Decision**: KO↔JA 번역은 원문 어조를 보존한다. KO 합니다체 ↔ JA です·ます체, KO 한다체 ↔ JA だ·である체. cue 내부 어조가 혼재하면 다수 어조를 따른다.

**Rationale**:
- spec FR-014의 "context-preserving translation" 정신과 가장 부합. 학습 사용자가 원문 어조 학습 시에도 유리.
- 정중체/친근체로 일률 통일하면 콘텐츠 특성(뉴스, 다큐, 예능, 일상 vlog)에 따라 위화감이 발생.

**Alternatives considered**:
- **항상 정중체**: 학습에 무난하지만 캐주얼 콘텐츠 톤이 어색.
- **항상 친근체**: vlog·예능에는 적합하나 비즈니스·뉴스에 부적합.
- **사용자 전역 설정**: MVP 범위 확장 필요(설정 UI·저장 모델).

**Reflected in**:
- [spec.md](./spec.md) FR-014, §Clarifications Q1
- [plan.md](./plan.md) §Constraints (어조 보존 항목), §Translation Pipeline (어조 보존 bullet)
- [tasks.md](./tasks.md) T062 (Claude adapter 어조 추론 + prompt 분기)

### 16.2 영상 길이 하드 상한 120분

**Decision**: 입력 영상 길이가 120분(7200초)을 초과하면 메타데이터 단계에서 즉시 거절한다 (`INVALID_INPUT`). 작업은 생성되지 않으며 DB에 기록되지 않는다. (1차 결정: 2026-05-27 — 60분, 2차 결정: 2026-05-28 — 120분으로 확장.)

**Rationale**:
- 기존 Assumptions의 "권장 ≤60분"은 모호("best-effort")해 운영 / 비용 / UX 예측이 어려웠다.
- 1차 60분 cap은 단편 학습 콘텐츠는 커버했으나 강의·세미나·라이브 다이제스트(전형적 60~120분) 수요를 배제했다. 운영 안정성 검증 후 120분으로 확장.
- 120분이어도 chunk 분할 번역과 동시성 2 정책으로 단일 작업의 자원 점유는 선형적으로 증가할 뿐, 비선형 폭발은 없다 (chunk 단위 retry·resume).
- 사용자 입력 시점에 거절하면 기대치가 명확해지고 큐·자원 보호.

**Cost / Time projection (120분 영상 기준 1건)**:
- 자막 cue 수 ≈ 1,500~2,200건(콘텐츠 밀도 의존). chunk(20~30 cue) 분할 시 약 50~110 chunk.
- Claude Opus 4.7 호출 ≈ 50~110건, 평균 입력+출력 토큰을 60분 영상의 2배로 단순 가정 → 토큰 비용 약 2× 증가.
- end-to-end 처리 시간: 다운로드·자막 추출은 영상 길이에 거의 비례, 번역은 chunk 직렬 처리 시 2배. 동시 작업 2건 동시 실행 시 큐 대기 시간 증가 가능 → 운영 모니터링 항목.

**Alternatives considered**:
- **유지 60분 cap**: 강의·세미나 등 수요를 계속 배제.
- **180분 cap 이상**: 단일 실패 시 손실 비용·디스크 점유가 가파르게 증가, MVP 운영 모니터링 부담 큼.
- **상한 없음 (best-effort)**: 운영 리스크 큼.

**Reflected in**:
- [spec.md](./spec.md) FR-003, Edge Cases ("120분 초과 영상"), Assumptions ("영상 길이 하드 상한 = 120분"), §Clarifications 2026-05-28
- [plan.md](./plan.md) §Constraints ("영상 길이 하드 상한 120분")
- [tasks.md](./tasks.md) T065 (메타데이터 검증), T070 (jobs service 분기) — 60분 기준으로 구현되었던 검증을 120분으로 갱신
- [contracts/openapi.yaml](./contracts/openapi.yaml) BadRequest examples — `video_too_long`

### 16.3 취소 시 부분 산출물 완전 삭제

**Decision**: 작업 취소 확정 시 `var/storage/<job_id>/` 전체를 즉시 삭제한다. DB의 `video_job` 행은 감사 목적으로 유지하되 상태를 `failed`, `error_code=USER_CANCELLED`로 기록한다.

**Rationale**:
- 디스크 점유와 상태 일관성 측면에서 가장 명확. 사용자가 동일 URL을 다시 처리해도 깨끗한 상태에서 시작.
- 부분 산출물(중간 자막, 부분 번역)을 노출하면 사용자 혼동 가능.

**Alternatives considered**:
- **부분 산출물 보존 + 수동 정리**: 디버깅 편의가 있으나 운영 부담 증가, 디스크 누수 위험.
- **완료 자산만 보존**: 규칙 복잡도 증가, MVP 가치 대비 과한 설계.

**Reflected in**:
- [spec.md](./spec.md) FR-028, §Clarifications Q3
- [tasks.md](./tasks.md) T103 (DELETE cancel — purge_job_directory 호출), T020 (filesystem helper 확장)

### 16.4 보존 정책 — 자동 정리 없음

**Decision**: MVP는 자동 정리 정책을 갖지 않는다. 완료·실패 작업의 메타데이터(DB)와 산출물(`var/storage/`)은 사용자가 수동으로 삭제할 때까지 무기한 보존된다.

**Rationale**:
- MVP는 단일 호스트·단일 사용자 전제(헌법 IV / spec Assumptions)와 정합.
- 자동 정리 정책은 정책 자체가 잘못 설계되면 사용자 데이터 손실 → 신중한 선택이 필요. 후속 확장에서 운영 데이터를 보며 결정.

**Alternatives considered**:
- **30일 후 자동 삭제**: 안전하지만 학습자가 같은 영상을 30일 후 다시 보고 싶을 수 있음.
- **최대 N건 유지**: UI 최근 목록과 정합이 좋으나 사용자 의도와 어긋날 가능성(중요한 작업이 밀려 삭제).
- **수동 삭제 API만 제공**: 가치는 있으나 MVP 범위 확장. 후속 확장에서 도입.

**Reflected in**:
- [spec.md](./spec.md) Assumptions ("데이터 보존 기간"), §Clarifications Q4

### 16.5 동시 처리 상한 = 2 (환경변수로 조정)

**Decision**: 동시에 진행되는 작업 수는 기본 2건으로 제한한다. 초과 작업은 `pending` 상태로 큐에 보류되어 자원이 비는 즉시 처리된다. 운영 시 환경변수 `JOB_CONCURRENCY`로 조정 가능.

**Rationale**:
- macOS 단일 호스트의 CPU·네트워크 자원 경합이 적절한 수준.
- 3건 이상이면 Claude provider rate limit / yt-dlp 네트워크 경합 / 디스크 IO 경합 위험 증가.
- 환경변수 노출로 운영 유연성 확보.

**Alternatives considered**:
- **1건 직렬**: UX 단순하나 처리량 제한.
- **4건**: 처리량 증가하지만 단일 호스트 부담 큼.
- **하드 상한 미명시 + env만**: 계약 명확성 저하, 신규 사용자가 의도하지 않은 부하 발생 가능.

**Reflected in**:
- [spec.md](./spec.md) FR-027, SC-007, §Clarifications Q5
- [plan.md](./plan.md) §Scale/Scope (`JOB_CONCURRENCY` 명시)
- [tasks.md](./tasks.md) T011 (settings 필드 추가), Celery worker 기동 명령에 `--concurrency` 반영

---

### 미해결 항목

없음. 모든 NEEDS CLARIFICATION 해소. plan.md의 Constitution Check 모든 게이트 통과. spec.md §Clarifications Q1~Q5 모두 plan / tasks / contracts에 반영됨.
