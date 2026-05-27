# T128 — quickstart §6 end-to-end 검증 follow-up

## 본 문서의 위치

본 문서는 [tasks.md T128](../tasks.md) 의 산출물이다.
[quickstart.md §6](../quickstart.md) 의 end-to-end 시나리오는 다음 외부 의존을 모두 요구한다.

- 유효한 `ANTHROPIC_API_KEY` (실 비용 발생)
- 인터넷 접속 가능한 YouTube 영상 URL 및 yt-dlp가 자막을 추출 가능한 영상
- 로컬 redis 인스턴스 (Celery broker)
- 로컬 ffmpeg 실행 환경

자동화 환경(에이전트 / CI)에서 위 의존을 충족할 수 없으므로 **본 task는 사용자가
직접 로컬에서 수행**해야 한다. 본 문서는 그 시점에 사용할 체크리스트와 알려진
deviation을 정리한다.

---

## 검증 시점 권장

- 본 PR(`001-dual-subtitle-mvp`) 머지 직전 1회
- 정식 0.1 출시 직전 1회 (회귀 확인)

---

## §6 체크리스트 (사용자 수행)

각 단계를 수행하며 ✅ 또는 ❌ 로 기록한다.

- [ ] **1단계**: `http://localhost:3000` 진입 시 URL 입력란이 자동으로 포커스되는지 확인 (US1, S1 와이어프레임)
- [ ] **2단계**: 자막이 있는 짧은(권장 5분 이내) 일본어 YouTube 영상 URL을 입력란에 붙여넣고 `시작` 클릭
- [ ] **3단계**: 클릭 후 같은 페이지에서 상세 페이지(S2)로 라우팅되며 단계 인디케이터가 표시되는지 확인 (FR-012)
- [ ] **4단계**: 다음 단계 전이가 화면에 반영되기까지 평균 5초 이내인지 확인 (SC-002 / FR-013 — SSE)
  - `pending → downloading → subtitle_processing → translating → rendering → completed`
- [ ] **5단계**: `completed` 상태가 되면 재생 화면(S3)이 열리고, 영상 위에 듀얼 자막이 오버레이되는지 확인 (FR-018)
- [ ] **6단계**:
  - [ ] 자막 토글(원문 / 번역 / 양쪽 / 비활성)이 즉시 동작하는지 (FR-022)
  - [ ] 자막 순서 전환(`source-first` ↔ `target-first`)이 즉시 동작하는지 (FR-023)
  - [ ] SRT / VTT 다운로드 링크가 동작하고 파일 안에 두 언어가 한 cue 두 줄로 들어 있는지 (FR-018)

---

## 알려진 Deviation (현 시점 기준)

다음 항목은 자동화 테스트로 부분 검증되었으나 실제 환경에서 별도 확인이 필요하다.

### 1. T123 — Real-network smoke 테스트의 영상 안정성

`backend/tests/media/test_smoke_real.py` 는 `RUN_REAL_NETWORK=1` 시에만 실행되며,
사용하는 YouTube 영상 URL의 장기 가용성은 검증되지 않았다. 영상이 비공개로 전환되거나
자막이 제거될 경우 smoke 테스트가 실패한다. PR 직전 1회 수동 확인을 권장한다.

### 2. T124 — SSE latency 측정 기준

`backend/tests/integration/test_performance.py` 의 SC-002 latency assertion은
**fakeredis(in-memory)** 환경에서 측정된 값이다. 실제 redis(네트워크 hop 포함)
환경에서의 latency는 별도 측정이 필요하며, redis 사양 / 네트워크 RTT에 따라
편차가 발생할 수 있다.

### 3. T103 — 취소 후 storage purge

cancel 후 `var/storage/<job_id>/` 가 완전히 삭제되는지는 통합 테스트
(`tests/integration/test_jobs_cancel.py::TestCancelPurgesJobStorage`)에서 검증되었으나,
실제 yt-dlp가 partial 다운로드 중 중단된 경우의 정리 동작은 수동 확인이 필요하다.

### 4. T130 — DOWNLOAD_FAILED / TRANSLATION_FAILED envelope

본 task에서 추가된 `tests/integration/test_failure_envelope.py` 는 워커 단계 실패를
`JobsService.mark_failed` 직접 호출로 시뮬레이션한다. 실제 yt-dlp / Anthropic API
호출이 실패하는 경우의 envelope은 본 시뮬레이션과 일치한다는 가정에 의존하므로,
실 환경에서 의도적으로 실패를 유발하여 (예: 권한 없는 영상, API 키 무효) envelope이
동일한지 1회 확인하는 것을 권장한다.

---

## 검증 결과 기록 (사용자가 채워 넣음)

| 일시 | 검증자 | 영상 URL | 결과 | 비고 |
|---|---|---|---|---|
|  |  |  |  |  |

문제가 발견되면 본 문서 하단에 follow-up task를 추가하고 tasks.md 에도 반영한다.
