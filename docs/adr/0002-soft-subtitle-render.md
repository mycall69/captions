# ADR 0002 — Soft Subtitle 렌더링 (브라우저 오버레이 정책)

| 항목 | 내용 |
|---|---|
| **상태** | 채택됨 (Accepted) — 2026-05-28 |
| **결정자** | 프로젝트 팀 |
| **관련 헌법** | 헌법 §Architecture First — Media Pipeline (hard / soft 모두 지원) |

---

## 컨텍스트

Dual Subtitle MVP는 영상에 듀얼 자막(원문 + 번역)을 표시해야 한다. 자막을 영상에 출력하는 방식은
크게 두 가지로 나뉜다.

1. **Hard burn-in**: ffmpeg `-vf subtitles=...` 로 자막을 비디오 픽셀에 굽는다. 외부 플레이어와도
   호환되지만 매번 re-encode가 필요하다.
2. **Soft subtitle**: 영상은 원본 그대로 두고 자막은 별도 파일(SRT/VTT)로 제공한다. 플레이어가
   자막을 실시간 합성한다.

헌법은 두 방식 모두 지원해야 한다고 명시했으나, MVP의 SC-001(처리 시간) / 디스크 사용량 /
UX 토글 요구를 고려해 MVP 한정 정책을 결정해야 한다. 자세한 비교는
[research.md §7 (ffmpeg 사용 범위)](../../specs/001-dual-subtitle-mvp/research.md)에 정리되어 있다.

---

## 결정

MVP는 **브라우저 오버레이 기반 soft subtitle** 만 채택한다.

- ffmpeg는 yt-dlp 산출 mp4를 그대로 서빙하거나, 필요 시 **`-c copy` 컨테이너 remux만** 수행한다.
  자막을 영상에 굽지 않는다.
- 듀얼 자막은 **SRT / VTT 파일로 별도 산출**되어 `GET /v1/jobs/{id}/subtitles?format=...` 으로
  다운로드 가능하다 (cue 한 블록 안에 두 줄 — ADR 미래 작성 항목, research §8 참조).
- 브라우저 측 `DualSubtitleOverlay` 컴포넌트가 두 언어 cue 배열을 받아 클라이언트 측에서
  실시간으로 영상 위에 오버레이한다. 토글 / 순서 전환 (`source-first` ↔ `target-first`)은 즉시 반영된다.

---

## 이유

- **처리 시간 단축**: burn-in은 영상 길이의 1~3배에 달하는 re-encode 시간이 필요하다.
  remux만 수행하면 디스크·CPU 부담이 대폭 감소하며 SC-001(60분 영상 ≤ 15분 처리)을 안정적으로 만족한다.
- **UX 우수**: 자막 토글 / 순서 전환 / 폰트 크기 조정이 클라이언트 측에서 즉시 가능하다 (US1-3, US1-4).
- **다운로드 자유도**: 사용자는 원본 mp4와 dual SRT/VTT를 따로 받아 외부 플레이어에서도 결합 사용 가능하다.
- **보안 표면 축소**: ffmpeg에 untrusted 자막 텍스트를 inject 하는 경로가 사라져 헌법 FR-033 위반 위험이 줄어든다.
- **확장 경로 보존**: 후속 단계에서 burn-in 옵션을 워커 task로 추가하면 hybrid 출시도 가능하다.

---

## 결과

### 긍정적 결과

- 처리 파이프라인이 단순해진다 (extract → translate → 파일 산출 → remux).
- 디스크 사용량이 대폭 감소한다 (원본 mp4 1벌만 저장; 자막은 텍스트).
- 자막 토글 / 순서 전환이 영상 재생 중에도 즉시 가능하다.

### 부정적 결과 / 트레이드오프

- **외부 플레이어 호환성 부족**: 사용자가 mp4 단독을 다운로드해 YouTube 외부 플레이어에서
  재생할 경우 자막이 보이지 않는다. SRT/VTT를 별도로 로드해야 한다.
- **모바일 / TV 앱 미지원**: 브라우저 외 환경에서 듀얼 자막을 보려면 후속 단계의 burn-in 출시가 필요하다.
- **자막 스타일링 일관성**: 클라이언트 측 오버레이는 폰트/위치를 우리가 제어하지만, SRT 다운로드 시
  스타일은 외부 플레이어 정책을 따른다.

---

## 대안 검토

| 대안 | 기각 이유 |
|---|---|
| Hard burn-in via ffmpeg `-vf subtitles=...` | 처리 시간 ×3, 토글 불가, 매번 재렌더 필요 — SC-001 위협 |
| Hybrid (soft + hard 둘 다 산출) | 디스크 2배, 워커 복잡도 증가, MVP 범위 초과 |
| HTML5 `<track>` 단일 트랙 + 두 줄 cue | 브라우저별 줄바꿈 정책이 상이해 일관된 듀얼 표시 어려움 |

---

## 참고

- [research.md §7 — ffmpeg 사용 범위 (MVP는 컨테이너 변환만, soft subtitle)](../../specs/001-dual-subtitle-mvp/research.md)
- [research.md §8 — dual subtitle 파일 형식 (cue별 두 줄)](../../specs/001-dual-subtitle-mvp/research.md)
- [plan.md §Media Pipeline](../../specs/001-dual-subtitle-mvp/plan.md)
- 헌법 §II Architecture First — Layered Architecture & Media Pipeline
