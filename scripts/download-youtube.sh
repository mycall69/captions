#!/usr/bin/env bash
set -euo pipefail

# download-youtube.sh — YouTube 영상 또는 플레이리스트 URL 에서 영상 + ja/ko 자막을
# srt 형식으로 현재 디렉터리에 다운로드한다.
#
# 사용: ./scripts/download-youtube.sh <youtube-url>
#   - 영상 URL: 해당 영상 1개 다운로드
#   - 플레이리스트 URL(watch?v=...&list=... 포함): 플레이리스트의 모든 영상 다운로드
#
# 동작:
#   - 영상: mp4 컨테이너 강제 (필요 시 ffmpeg 로 remux), 자막은 함께 받지 않음
#   - 자막: 언어별 (ja → 대기 → ko) 분리 호출. 각 호출 안에서 --write-sub + --write-auto-sub
#   - 자막 형식: srt 우선, vtt 만 제공되면 ffmpeg 로 srt 변환 (--convert-subs srt)
#   - 파일명: 다운로드/muxing 은 안정적인 <video_id> 로 진행하고, 완전 성공 시
#             <video_id>.muxed.mp4 → <영상 제목>.muxed.mp4 로 rename
#   - 정리: muxed.mp4 생성이 성공하면 원본 mp4·srt 는 삭제하고 <제목>.muxed.mp4 만 남긴다
#           (muxing 실패 시엔 원본 보존. 부분 실패 시엔 재실행 이어받기 위해 원본 유지)
#   - 429 대응: 자막 호출별로 bash 레이어 retry (점진적 backoff: 15s/30s/45s/60s/75s)
#   - 플레이리스트: 영상 사이에 10초 딜레이를 두어 서버 접근 제한(rate limit) 회피
#   - 멱등성: 이미 같은 파일이 있으면 해당 단계/영상 skip
#
# 환경변수:
#   YT_DLP_COOKIES_BROWSER  — YouTube anti-bot 게이트("Sign in to confirm you're
#                              not a bot") 우회용. 기본값: firefox.
#                              다른 브라우저: chrome, safari, edge, brave 등.
#                              완전 비활성화: YT_DLP_COOKIES_BROWSER=none 으로 지정.
#   YT_DLP_PLAYER_CLIENT    — yt-dlp player_client override. 기본값은 쿠키 사용 여부에 따라 결정.
#   YT_DLP_ITEM_DELAY       — 플레이리스트 영상 간 딜레이(초). 기본값 10.
#   BGUTIL_POT_SERVER_HOME  — bgutil PO Token provider 의 server 경로.
#                              기본값: ~/.local/share/bgutil-ytdlp-pot-provider/server
#   BGUTIL_POT_AUTO_INSTALL — PO Token provider 미설치 시 자동 설치 on/off. 기본 1(on), 0 이면 끔.
#
# 자막용 PO Token (자동 설치 내장):
#   YouTube 가 (자동)자막 접근에 PO Token 을 요구하므로 provider 가 필요하다. provider 는
#   (1) '실행되는 yt-dlp' 에 설치된 플러그인 + (2) 빌드된 provider server, 둘 다 있어야 동작한다.
#   둘 중 하나라도 없으면 이 스크립트가 최초 1회 자동 설치한다 — 실행되는 yt-dlp 인터프리터에
#   플러그인 설치 + provider server clone·빌드 (git/node(npm) 필요, 수십 초 소요).
#   끄려면 BGUTIL_POT_AUTO_INSTALL=0. 설치 실패 시 영상은 받아지되 자막은 실패한다.

if [[ $# -lt 1 ]]; then
  echo "Usage: $(basename "$0") <youtube-url>" >&2
  exit 1
fi

URL="$1"

if ! command -v yt-dlp >/dev/null 2>&1; then
  echo "ERROR: yt-dlp 가 필요합니다. 'brew install yt-dlp' 후 다시 실행하세요." >&2
  exit 1
fi

# --convert-subs srt 가 vtt → srt 변환에 ffmpeg 를 사용한다.
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ERROR: ffmpeg 가 필요합니다 (자동 자막 srt 변환). 'brew install ffmpeg' 후 다시 실행하세요." >&2
  exit 1
fi

# 기본 firefox — Anthropic/captions 운영 컨벤션과 일치. 명시적 비활성화는 'none'.
YT_DLP_COOKIES_BROWSER="${YT_DLP_COOKIES_BROWSER:-firefox}"

declare -a COOKIES_ARGS=()
if [[ "${YT_DLP_COOKIES_BROWSER}" != "none" ]]; then
  COOKIES_ARGS+=(--cookies-from-browser "${YT_DLP_COOKIES_BROWSER}")
  echo "ℹ️  브라우저 쿠키 사용: ${YT_DLP_COOKIES_BROWSER}"
fi

# YouTube SABR 강제로 web 클라이언트 포맷이 fragment 403 으로 떨어지는 케이스 회피.
# tv / web_safari / android_vr 는 SABR 영향이 적은 것으로 보고됨 (yt-dlp #12482).
# 단, android_vr 는 쿠키 인증을 지원하지 않아 쿠키 사용 시 항상 skip 경고가 발생하므로
# 쿠키를 쓰는 기본 시나리오에서는 후보에서 제외한다. 쿠키 미사용 환경에서는
# SABR fallback 후보로 유지.
# 환경변수로 override 가능: YT_DLP_PLAYER_CLIENT=default 로 두면 yt-dlp 기본값 사용.
if [[ -z "${YT_DLP_PLAYER_CLIENT:-}" ]]; then
  if [[ "${YT_DLP_COOKIES_BROWSER}" != "none" ]]; then
    YT_DLP_PLAYER_CLIENT="tv,web_safari"
  else
    YT_DLP_PLAYER_CLIENT="tv,web_safari,android_vr"
  fi
fi
declare -a EXTRACTOR_ARGS=()
if [[ "${YT_DLP_PLAYER_CLIENT}" != "default" ]]; then
  EXTRACTOR_ARGS+=(--extractor-args "youtube:player_client=${YT_DLP_PLAYER_CLIENT}")
  echo "ℹ️  player_client=${YT_DLP_PLAYER_CLIENT}"
fi

# YouTube 가 (자동)자막 접근에 PO Token 을 요구하므로 bgutil PO Token provider(script 모드)를
# 사용한다. 이게 동작하려면 두 가지가 모두 필요하다:
#   (1) '실행되는 yt-dlp' 의 파이썬 환경에 플러그인(bgutil-ytdlp-pot-provider) 이 설치돼 있고
#   (2) BGUTIL_POT_SERVER_HOME 에 provider server 빌드 산출물(build/generate_once.js) 이 있을 것
# 하나라도 없으면 ensure_pot_provider 가 최초 1회 자동 설치한다(끄려면 BGUTIL_POT_AUTO_INSTALL=0).
BGUTIL_POT_SERVER_HOME="${BGUTIL_POT_SERVER_HOME:-$HOME/.local/share/bgutil-ytdlp-pot-provider/server}"

# 실행되는 yt-dlp 가 쓰는 파이썬 인터프리터를 shebang 에서 추출한다(플러그인 설치/확인 대상).
# 판별 불가(standalone 바이너리 등)면 빈 문자열.
ytdlp_python() {
  local bin line first rest
  bin="$(command -v yt-dlp 2>/dev/null)" || return 0
  IFS= read -r line < "${bin}" 2>/dev/null || return 0
  case "${line}" in
    '#!'*) line="${line#\#!}" ;;
    *)     return 0 ;;
  esac
  first="${line%% *}"
  rest="${line#"${first}"}"; rest="${rest# }"
  if [[ "${first}" == */env ]]; then
    command -v "${rest%% *}" 2>/dev/null || true      # '#!/usr/bin/env python3' 형태
  elif [[ -x "${first}" ]]; then
    printf '%s\n' "${first}"                           # 직접 경로 형태
  fi
}
POT_PYBIN="$(ytdlp_python)"

# 실행되는 yt-dlp env 에 플러그인이 실제로 설치돼 있는가 (네트워크 불필요).
pot_plugin_installed() {
  [[ -n "${POT_PYBIN}" ]] && "${POT_PYBIN}" -m pip show bgutil-ytdlp-pot-provider >/dev/null 2>&1
}
pot_server_built() { [[ -f "${BGUTIL_POT_SERVER_HOME}/build/generate_once.js" ]]; }

# provider 사용 준비 완료? server 산출물 필수 + (인터프리터 판별되면) 플러그인 설치까지 확인.
# 인터프리터를 못 알아내면(바이너리 등) 플러그인 검증은 건너뛰고 server 존재만으로 시도한다.
pot_ready() {
  pot_server_built || return 1
  if [[ -n "${POT_PYBIN}" ]]; then pot_plugin_installed; else return 0; fi
}

# bgutil PO Token provider 자동 설치 — (1) 실행되는 yt-dlp 에 플러그인 설치 + (2) server 빌드.
# 성공 0 / 실패 1. 호출부 `|| true` 로 흡수(→ set -e 비활성)되므로 각 단계는 명시적으로 처리.
ensure_pot_provider() {
  local server dest ver ref cloned missing

  # (1) 플러그인 — 실행되는 yt-dlp 인터프리터에 직접 설치가 가장 확실(PATH 상 다른 yt-dlp 오설치 방지).
  if ! pot_plugin_installed; then
    echo "  ▶ 플러그인 설치: bgutil-ytdlp-pot-provider (yt-dlp=$(command -v yt-dlp 2>/dev/null || echo '?'))"
    if [[ -n "${POT_PYBIN}" ]] && "${POT_PYBIN}" -m pip install -U bgutil-ytdlp-pot-provider; then
      :
    elif command -v pipx >/dev/null 2>&1 && pipx inject yt-dlp bgutil-ytdlp-pot-provider; then
      :
    else
      echo "  ✗ 플러그인 설치 실패 (python=${POT_PYBIN:-불명}). pipx 로 yt-dlp 를 설치했는지 확인: pipx install yt-dlp" >&2
      return 1
    fi
  fi

  # (2) provider server — 아직 안 빌드됐으면 clone + 빌드 (git/node(npm) 필요).
  server="${BGUTIL_POT_SERVER_HOME}"
  dest="$(dirname "${server}")"
  if ! pot_server_built; then
    missing=()
    command -v git >/dev/null 2>&1 || missing+=("git (xcode-select --install)")
    command -v npm >/dev/null 2>&1 || missing+=("node/npm (brew install node)")
    if (( ${#missing[@]} > 0 )); then
      echo "  ✗ server 빌드 불가 — 다음이 필요합니다:" >&2
      printf '      - %s\n' "${missing[@]}" >&2
      return 1
    fi

    ver=$( { [[ -n "${POT_PYBIN}" ]] && "${POT_PYBIN}" -m pip show bgutil-ytdlp-pot-provider 2>/dev/null; } | awk '/^Version:/{print $2}')
    echo "  플러그인 버전: ${ver:-unknown}"

    if [[ ! -d "${server}" ]]; then
      echo "  ▶ provider server clone → ${dest}"
      cloned=0
      for ref in "${ver}" "v${ver}" master main; do
        [[ -z "${ref}" ]] && continue
        if git clone --depth 1 --single-branch --branch "${ref}" \
             https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git "${dest}" 2>/dev/null; then
          echo "    ref: ${ref}"
          cloned=1
          break
        fi
      done
      if (( cloned == 0 )); then
        echo "  ✗ clone 실패 (${dest} 가 비어있지 않거나 네트워크 오류)" >&2
        return 1
      fi
    fi

    echo "  ▶ server 빌드 (npm ci && npx tsc) — 수십 초 소요"
    # 서브셸 격리(다운로드 대상 CWD 유지) + 각 단계 명시적 exit 로 set -e 비의존.
    if ! (
      cd "${server}" || exit 1
      if [[ -f package-lock.json ]]; then npm ci || exit 1; else npm install || exit 1; fi
      npx tsc || exit 1
    ); then
      echo "  ✗ 빌드 실패" >&2
      return 1
    fi
  fi

  if pot_ready; then
    echo "  ✅ PO Token provider 준비 완료"
    return 0
  fi
  echo "  ✗ PO Token provider 준비 실패 (플러그인/server 재확인 필요)" >&2
  return 1
}

# ── 준비 상태 판정 → 필요 시 자동 설치 → extractor-arg 연결 ──────────────────
if pot_ready; then
  :
elif [[ "${BGUTIL_POT_AUTO_INSTALL:-1}" == "1" ]]; then
  echo "ℹ️  PO Token provider 미완비 — 자동 설치를 시도합니다 (최초 1회)."
  ensure_pot_provider || true
else
  echo "ℹ️  PO Token provider 미완비 (자동 설치 꺼짐: BGUTIL_POT_AUTO_INSTALL=0)." >&2
fi

if pot_ready; then
  EXTRACTOR_ARGS+=(--extractor-args "youtubepot-bgutilscript:server_home=${BGUTIL_POT_SERVER_HOME}")
  echo "ℹ️  PO Token provider(script): ${BGUTIL_POT_SERVER_HOME}"
else
  echo "⚠️  PO Token provider 사용 불가 — 자막 다운로드가 실패할 수 있습니다." >&2
  if ! pot_plugin_installed; then
    echo "    · 플러그인이 '실행되는 yt-dlp' 에 없음: yt-dlp=$(command -v yt-dlp 2>/dev/null || echo '?') python=${POT_PYBIN:-불명}" >&2
    echo "      → ${POT_PYBIN:-<yt-dlp의 python>} -m pip install -U bgutil-ytdlp-pot-provider" >&2
  fi
  if ! pot_server_built; then
    echo "    · provider server 미빌드: ${BGUTIL_POT_SERVER_HOME}" >&2
  fi
fi

# 플레이리스트 영상 간 딜레이(초).
ITEM_DELAY="${YT_DLP_ITEM_DELAY:-10}"

OUTPUT_TEMPLATE="%(id)s.%(ext)s"

# 파일명에 쓸 수 없는/혼란을 주는 문자를 안전하게 치환한다.
# macOS(APFS)는 '/' 만 금지하지만 Finder 가 ':' 를 '/' 로 표시하므로 함께 치환하고,
# 셸/타 플랫폼에서 문제되는 문자(\ ? * < > | ")는 제거한다. 길이는 150자로 제한.
sanitize_filename() {
  local s="$1"
  s="${s//\//-}"                                   # '/' → '-'
  s="${s//:/-}"                                    # ':' → '-'
  s=$(printf '%s' "$s" | tr -d '\\?*<>|"')
  # 연속 공백 축약 + 앞뒤 공백/점 제거
  s=$(printf '%s' "$s" | sed 's/[[:space:]]\{1,\}/ /g; s/^[[:space:] .]*//; s/[[:space:] .]*$//')
  s="${s:0:150}"
  s=$(printf '%s' "$s" | sed 's/[[:space:] .]*$//') # 150자 컷 이후 꼬리 공백/점 재정리
  printf '%s' "$s"
}

# ── 자막 다운로드 함수 (언어별, 점진적 backoff retry) ────────────────────────
# process_one 의 지역변수 VIDEO_ID / URL 을 bash 동적 스코프로 참조한다.
download_sub() {
  local lang="$1"
  local target="${VIDEO_ID}.${lang}.srt"

  if [[ -f "${target}" ]]; then
    echo "ℹ️  ${target} 이미 존재 — skip"
    return 0
  fi

  local attempt=0
  local max_attempts=5
  local out
  while (( attempt < max_attempts )); do
    attempt=$((attempt + 1))
    echo "  → 시도 ${attempt}/${max_attempts}: ${lang}"
    # 출력을 캡처해 실패 원인을 분류한다(비일시적 실패는 재시도하지 않음).
    # `|| true` 로 yt-dlp 실패가 set -e 를 트리거하지 않게 막고, 결과 파일 존재로 판정.
    out=$(yt-dlp \
      --no-playlist \
      --skip-download \
      --write-sub \
      --write-auto-sub \
      --sub-langs "${lang}" \
      --sub-format "srt/best" \
      --convert-subs srt \
      "${COOKIES_ARGS[@]+"${COOKIES_ARGS[@]}"}" \
      "${EXTRACTOR_ARGS[@]+"${EXTRACTOR_ARGS[@]}"}" \
      -o "${OUTPUT_TEMPLATE}" \
      "${URL}" 2>&1) || true
    printf '%s\n' "${out}" | sed 's/^/    /'

    if [[ -f "${target}" ]]; then
      echo "  ✓ ${target} 완료"
      return 0
    fi

    # 비일시적 실패 — 재시도해도 소용 없음:
    #  (1) 해당 언어 자막이 아예 없음
    if printf '%s' "${out}" | grep -qiE "no subtitles for the requested languages"; then
      echo "  ⚠️  ${lang} 자막이 존재하지 않음 — 재시도 생략" >&2
      return 1
    fi
    #  (2) PO Token 미획득(provider 미설치/미빌드) → 자막 API 접근 불가
    if printf '%s' "${out}" | grep -qiE "a PO token was not provided"; then
      echo "  ⚠️  PO Token 미획득 — bgutil PO Token provider 설치/빌드 확인 필요(재시도 생략)." >&2
      echo "      설치: pipx inject yt-dlp bgutil-ytdlp-pot-provider (+ server 빌드)" >&2
      return 1
    fi

    # 그 외(HTTP 429 / 네트워크 등 일시적 오류)만 backoff 재시도
    if (( attempt < max_attempts )); then
      local sleep_sec=$((attempt * 15))
      echo "  ⏳ 일시적 오류(429 등) 가능 — ${sleep_sec}초 대기 후 재시도" >&2
      sleep "${sleep_sec}"
    fi
  done

  echo "  ⚠️  ${target} 다운로드 실패 (${max_attempts}회 시도)." >&2
  return 1
}

# ── mp4 컨테이너에 자막 트랙 muxing ──────────────────────────────────────────
# 무비스트 같은 macOS 플레이어가 자동으로 자막을 인식하려면 같은 basename 의
# 단일 .srt 파일이 필요한데, ".ja.srt"/".ko.srt" 처럼 닷이 두 개면 인식 못 하는
# 경우가 있다. ffmpeg 로 mov_text 형식 자막 트랙을 mp4 컨테이너에 직접
# 내장하면 한 파일로 ja/ko 트랙을 가지며 모든 플레이어가 자동 인식한다.
# `-c copy` 라 영상/음성 재인코딩 없이 컨테이너만 재구성 (수 초~수십 초).
mux_subtitles_into_mp4() {
  local video="${VIDEO_ID}.mp4"
  local out="${VIDEO_ID}.muxed.mp4"

  if [[ ! -f "${video}" ]]; then
    echo "⚠️  ${video} 없음 — muxing skip" >&2
    return 1
  fi
  if [[ -f "${out}" ]]; then
    echo "ℹ️  ${out} 이미 존재 — muxing skip"
    return 0
  fi

  declare -a srt_inputs=()
  declare -a maps=(-map 0)
  declare -a metadata_args=()
  local sub_idx=0

  for lang in ja ko; do
    local srt="${VIDEO_ID}.${lang}.srt"
    if [[ ! -f "${srt}" ]]; then
      continue
    fi
    srt_inputs+=(-i "${srt}")
    # input index = (srt_inputs 길이 / 2) — '-i path' pair 누적이므로.
    local input_idx=$(( ${#srt_inputs[@]} / 2 ))
    maps+=(-map "${input_idx}:0")
    local lang3 title
    case "${lang}" in
      ja) lang3=jpn; title="日本語" ;;
      ko) lang3=kor; title="한국어" ;;
      *)  lang3="${lang}"; title="${lang}" ;;
    esac
    metadata_args+=(-metadata:s:s:${sub_idx} "language=${lang3}")
    metadata_args+=(-metadata:s:s:${sub_idx} "title=${title}")
    sub_idx=$((sub_idx + 1))
  done

  if (( sub_idx == 0 )); then
    echo "ℹ️  자막 파일 없음 — muxing skip"
    return 0
  fi

  echo "🎬 ffmpeg muxing (${sub_idx} 자막 트랙) → ${out}"
  if ffmpeg -y -loglevel warning \
       -i "${video}" \
       "${srt_inputs[@]}" \
       "${maps[@]}" \
       -c copy -c:s mov_text \
       "${metadata_args[@]}" \
       "${out}"; then
    echo "  ✓ ${out} 생성 완료"
    return 0
  else
    echo "  ✗ ffmpeg muxing 실패" >&2
    rm -f "${out}"  # 부분 생성된 파일 정리
    return 1
  fi
}

# ── video_id 기반 결과물을 제목 기반 이름으로 일괄 rename ─────────────────────
# <video_id>.mp4 / <video_id>.muxed.mp4 / <video_id>.ja.srt / <video_id>.ko.srt 등
# 접두사 video_id 를 SAFE_TITLE 로 치환. 대상 파일이 이미 있으면 덮어쓰지 않고 skip.
rename_outputs_to_title() {
  if [[ "${SAFE_TITLE}" == "${VIDEO_ID}" ]]; then
    return 0   # 제목이 비었거나 video_id 와 동일 — rename 불필요
  fi
  local src suffix dst
  for src in "${VIDEO_ID}".*; do
    [[ -e "${src}" ]] || continue                  # glob 매치 없음 방지
    suffix="${src#"${VIDEO_ID}"}"                  # 예: ".mp4", ".ja.srt", ".muxed.mp4"
    dst="${SAFE_TITLE}${suffix}"
    if [[ -e "${dst}" ]]; then
      echo "ℹ️  \"${dst}\" 이미 존재 — \"${src}\" rename skip"
      continue
    fi
    mv -- "${src}" "${dst}"
    echo "  ✎ ${src} → ${dst}"
  done
  return 0
}

# ── 단일 영상 처리 ───────────────────────────────────────────────────────────
# 인자: $1=video_id (열거 단계에서 확보), $2=영상 watch URL
# 반환: 0=완전 성공(또는 이미 완료), 2=부분 성공(자막 일부 누락), 1=실패
process_one() {
  local VIDEO_ID="$1"
  local URL="$2"
  local VIDEO_TITLE SAFE_TITLE JA_OK KO_OK

  # 제목 조회 (실패해도 video_id 로 폴백하고 진행)
  VIDEO_TITLE=$(yt-dlp \
    --no-playlist \
    --print "%(title)s" \
    "${COOKIES_ARGS[@]+"${COOKIES_ARGS[@]}"}" \
    "${EXTRACTOR_ARGS[@]+"${EXTRACTOR_ARGS[@]}"}" \
    "${URL}" 2>/dev/null) || VIDEO_TITLE=""

  SAFE_TITLE=$(sanitize_filename "${VIDEO_TITLE}")
  if [[ -z "${SAFE_TITLE}" ]]; then
    SAFE_TITLE="${VIDEO_ID}"
  fi
  echo "📺 video_id=${VIDEO_ID}"
  echo "🏷  제목=${VIDEO_TITLE:-(제목 조회 실패)}"
  echo "📄 저장 이름=${SAFE_TITLE}"

  # 이전 실행에서 제목으로 rename 까지 끝난 경우(완전 성공) — 재다운로드 방지.
  # 부분 실패 시엔 파일이 아직 video_id 이름이라 이 조건에 걸리지 않고 이어받는다.
  # (주의: 서로 다른 영상이 같은 제목이면 잘못 skip 될 수 있음 — 제목 기반 이름의 태생적 한계.)
  # 완전 성공 후에는 원본 mp4 가 삭제되고 <제목>.muxed.mp4 만 남으므로 둘 다 확인한다.
  if [[ "${SAFE_TITLE}" != "${VIDEO_ID}" ]] \
     && { [[ -f "${SAFE_TITLE}.muxed.mp4" ]] || [[ -f "${SAFE_TITLE}.mp4" ]]; }; then
    echo "✅ 이미 완료된 작업입니다 (\"${SAFE_TITLE}.muxed.mp4\" 또는 \"${SAFE_TITLE}.mp4\") — skip."
    return 0
  fi

  # 1) 영상 다운로드 (자막 제외)
  if [[ -f "${VIDEO_ID}.mp4" ]]; then
    echo "▶ [1/4] 영상 — ${VIDEO_ID}.mp4 이미 존재, skip"
  else
    echo "▶ [1/4] 영상 다운로드"
    # mp4 강제 — captions backend (workers/tasks/download.py) 와 동일 format selector.
    # SABR client 가 mp4 stream 을 안 주면 마지막 fallback `b` 로 받은 뒤
    # --merge-output-format mp4 가 ffmpeg 로 mp4 컨테이너로 remux 한다 (재인코딩 없이 stream copy).
    if ! yt-dlp \
      --no-playlist \
      --retries 10 \
      --retry-sleep 5 \
      --fragment-retries 10 \
      --format "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b" \
      --merge-output-format mp4 \
      --no-write-subs \
      --no-write-auto-subs \
      "${COOKIES_ARGS[@]+"${COOKIES_ARGS[@]}"}" \
      "${EXTRACTOR_ARGS[@]+"${EXTRACTOR_ARGS[@]}"}" \
      -o "${OUTPUT_TEMPLATE}" \
      "${URL}"; then
      echo "  ✗ 영상 다운로드 실패 — 이 영상 건너뜀" >&2
      return 1
    fi
  fi

  # 2~3) 자막 다운로드 (ja → 대기 → ko)
  echo "▶ [2/4] 자막 ja"
  JA_OK=0
  download_sub ja && JA_OK=1 || true

  # 언어 간 cool-down — YouTube 자막 분당 한도 회복 시간 확보.
  echo "⏸  언어 간 대기 (10초)"
  sleep 10

  echo "▶ [3/4] 자막 ko"
  KO_OK=0
  download_sub ko && KO_OK=1 || true

  # 4) mp4 자막 muxing
  echo "▶ [4/4] mp4 자막 muxing"
  mux_subtitles_into_mp4 || true

  # 부분 실패 시: 재실행 이어받기를 위해 video_id 이름 유지
  if (( JA_OK == 0 || KO_OK == 0 )); then
    echo "✅ (부분) 결과:"
    ls -lh "./${VIDEO_ID}".* 2>/dev/null || true
    echo "⚠️  일부 자막 누락 — JA:${JA_OK} KO:${KO_OK} (파일명은 video_id 유지, 재실행 시 이어받기)"
    return 2
  fi

  # 완전 성공: muxed.mp4 가 생성됐으면 원본 mp4·srt 를 정리하고 muxed 만 남긴다.
  # muxed 가 없으면(ffmpeg muxing 실패 등) 원본을 지우지 않고 보존한다.
  if [[ -f "${VIDEO_ID}.muxed.mp4" ]]; then
    echo "▶ muxed.mp4 생성 확인 — 원본 mp4·srt 정리"
    rm -f "${VIDEO_ID}.mp4" "${VIDEO_ID}".*.srt
  fi

  # 제목 기반 이름으로 rename 후 요약
  echo "▶ 제목 기반 이름으로 rename"
  rename_outputs_to_title
  echo "✅ 완료:"
  ls -lh "./${SAFE_TITLE}".* 2>/dev/null || true
  if [[ -f "${SAFE_TITLE}.muxed.mp4" ]]; then
    echo "💡 무비스트/QuickTime 자막 자동 인식: \"${SAFE_TITLE}.muxed.mp4\""
  fi
  return 0
}

# ── 0) 대상 열거 (영상 1개 또는 플레이리스트 전체) ───────────────────────────
echo "▶ 대상 열거 (플레이리스트 지원)"
# --flat-playlist: 각 영상을 추출하지 않고 id 목록만 빠르게 가져온다.
# 단일 영상 URL 이면 그 영상 id 1개만 반환된다.
IDS_RAW=$(yt-dlp \
  --flat-playlist \
  --print "%(id)s" \
  "${COOKIES_ARGS[@]+"${COOKIES_ARGS[@]}"}" \
  "${EXTRACTOR_ARGS[@]+"${EXTRACTOR_ARGS[@]}"}" \
  "${URL}") || {
  echo "ERROR: 대상 열거 실패. URL 확인: ${URL}" >&2
  exit 1
}

declare -a VIDEO_IDS=()
while IFS= read -r line; do
  # 빈 줄 / 삭제된 항목(NA) 제외
  if [[ -n "${line}" && "${line}" != "NA" ]]; then
    VIDEO_IDS+=("${line}")
  fi
done <<< "${IDS_RAW}"

TOTAL=${#VIDEO_IDS[@]}
if (( TOTAL == 0 )); then
  echo "ERROR: 다운로드할 영상이 없습니다. URL 확인: ${URL}" >&2
  exit 1
fi
if (( TOTAL > 1 )); then
  echo "📋 플레이리스트 감지 — 총 ${TOTAL}개 영상 (영상 간 ${ITEM_DELAY}초 딜레이)"
fi

# ── 1) 영상별 처리 (영상 사이 ITEM_DELAY 초 딜레이) ──────────────────────────
OK_COUNT=0
PARTIAL_COUNT=0
FAIL_COUNT=0
declare -a PARTIAL_IDS=()
declare -a FAIL_IDS=()

idx=0
for vid in "${VIDEO_IDS[@]}"; do
  idx=$((idx + 1))

  if (( idx > 1 )); then
    echo ""
    echo "⏸  영상 간 대기 (${ITEM_DELAY}초) — 서버 접근 제한 회피"
    sleep "${ITEM_DELAY}"
  fi

  echo ""
  if (( TOTAL > 1 )); then
    echo "════════ [영상 ${idx}/${TOTAL}] ${vid} ════════"
  fi

  vurl="https://www.youtube.com/watch?v=${vid}"
  rc=0
  process_one "${vid}" "${vurl}" || rc=$?
  case "${rc}" in
    0) OK_COUNT=$((OK_COUNT + 1)) ;;
    2) PARTIAL_COUNT=$((PARTIAL_COUNT + 1)); PARTIAL_IDS+=("${vid}") ;;
    *) FAIL_COUNT=$((FAIL_COUNT + 1)); FAIL_IDS+=("${vid}") ;;
  esac
done

# ── 2) 전체 결과 요약 ────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════"
if (( TOTAL > 1 )); then
  echo "✅ 전체 종료 — 총 ${TOTAL} / 성공 ${OK_COUNT} / 부분 ${PARTIAL_COUNT} / 실패 ${FAIL_COUNT}"
else
  echo "✅ 종료"
fi

if (( PARTIAL_COUNT > 0 )); then
  echo "⚠️  부분 완료(자막 누락): ${PARTIAL_IDS[*]}"
  echo "    - 한도 회복 후(보통 수 분~10여 분) 같은 URL 로 재실행하면 누락분만 받고 제목으로 rename 됩니다."
fi
if (( FAIL_COUNT > 0 )); then
  echo "❌ 실패(영상 다운로드/조회 불가): ${FAIL_IDS[*]}"
fi

if (( PARTIAL_COUNT > 0 || FAIL_COUNT > 0 )); then
  exit 2
fi
