#!/usr/bin/env bash
# Claude Code statusline (2-line)
# 1행: 모델 · thinking · 비용(USD) · 디렉터리 · Git
# 2행: ctx · 입출력 토큰 · Rate limits (퍼센트 + 리셋 시각)
input=$(cat)

# 디버그: 실제 입력 JSON 스키마 덤프 (한 번 확인 후 라인 삭제 가능)
echo "$input" > /tmp/cc-statusline-input.json

# ─── 입력 JSON 파싱 ───
model=$(echo "$input" | jq -r '.model.display_name // .model.id // "Claude"')
cc_version=$(echo "$input" | jq -r '.version // empty')
effort=$(echo "$input" | jq -r '.effort.level // .effort // empty')
cwd=$(echo "$input" | jq -r '.workspace.current_dir // .cwd // .workspace.project_dir // empty')

ctx_pct=$(echo "$input" | jq -r '
  .context_window.used_percentage
  // .context_window.usage_percentage
  // .context.used_percentage
  // .session.context_used_percent
  // empty')
ctx_used=$(echo "$input" | jq -r '
  .context_window.total_input_tokens
  // .context_window.used_tokens
  // .context_window.current
  // .context.used
  // empty')
ctx_total=$(echo "$input" | jq -r '
  .context_window.context_window_size
  // .context_window.limit
  // .context_window.total
  // .context_window.max_tokens
  // .context.total
  // empty')
in_tokens=$(echo "$input" | jq -r '
  .context_window.total_input_tokens
  // .context_window.current_usage.input_tokens
  // .session.input_tokens
  // .usage.input_tokens
  // empty')
out_tokens=$(echo "$input" | jq -r '
  .context_window.total_output_tokens
  // .context_window.current_usage.output_tokens
  // .session.output_tokens
  // .usage.output_tokens
  // empty')
cost_usd=$(echo "$input" | jq -r '
  .cost.total_cost_usd
  // .total_cost_usd
  // .session_cost
  // .cost.usd
  // empty')
five_pct=$(echo "$input" | jq -r '
  .rate_limits.five_hour.used_percentage
  // .rate_limits."5h".used_percentage
  // empty')
week_pct=$(echo "$input" | jq -r '
  .rate_limits.seven_day.used_percentage
  // .rate_limits."7d".used_percentage
  // empty')
five_reset=$(echo "$input" | jq -r '
  .rate_limits.five_hour.resets_at
  // .rate_limits."5h".resets_at
  // empty')
week_reset=$(echo "$input" | jq -r '
  .rate_limits.seven_day.resets_at
  // .rate_limits."7d".resets_at
  // empty')

# ctx_pct가 비었지만 used/total이 있으면 계산
if [ -z "$ctx_pct" ] && [ -n "$ctx_used" ] && [ -n "$ctx_total" ]; then
  ctx_pct=$(awk -v u="$ctx_used" -v t="$ctx_total" 'BEGIN{ if(t+0>0) printf "%.2f", u*100/t }')
fi

# ─── 헬퍼 ───
# 토큰을 단위 표기로 (콤마 또는 k/M 단위 — 단위 명확화)
fmt_tokens() {
  local n=$1
  [ -z "$n" ] && { echo ""; return; }
  awk -v n="$n" 'BEGIN{
    if (n+0 >= 1e6) printf "%.2fM tok", n/1e6
    else if (n+0 >= 1e3) printf "%.1fK tok", n/1e3
    else printf "%d tok", n
  }'
}

# 컨텍스트 사용량/한도 — "94.0K/200K" 형식 (단위 K/M)
fmt_ctx_amount() {
  local used=$1 total=$2
  [ -z "$used" ] && { echo ""; return; }
  local u t
  u=$(awk -v n="$used"  'BEGIN{ if(n+0>=1e6) printf "%.2fM", n/1e6; else if(n+0>=1e3) printf "%.1fK", n/1e3; else printf "%d", n }')
  if [ -n "$total" ]; then
    t=$(awk -v n="$total" 'BEGIN{ if(n+0>=1e6) printf "%.0fM", n/1e6; else if(n+0>=1e3) printf "%.0fK", n/1e3; else printf "%d", n }')
    echo "${u}/${t} tok"
  else
    echo "${u} tok"
  fi
}

# 진행률 바 (10칸) — 임계별 색상
make_bar() {
  local pct=$1 width=10
  local filled=$(awk -v p="$pct" -v w="$width" 'BEGIN{
    f=int(p*w/100); if(f>w)f=w; if(f<0)f=0; print f
  }')
  local empty=$((width - filled))
  local color=$(awk -v p="$pct" 'BEGIN{
    if (p+0 >= 80) print "\033[1;31m"
    else if (p+0 >= 50) print "\033[1;33m"
    else print "\033[1;32m"
  }')
  local bar=""
  for ((i=0; i<filled; i++)); do bar+="█"; done
  for ((i=0; i<empty;  i++)); do bar+="░"; done
  printf "%b%s\033[0m" "$color" "$bar"
}

# Reset 시각 포맷 — 24시간 이내면 HH:MM, 그 이상이면 MM-DD HH:MM
fmt_reset() {
  local ts=$1
  [ -z "$ts" ] && { echo ""; return; }
  local now diff
  now=$(date +%s)
  diff=$((ts - now))
  if [ "$diff" -lt 0 ]; then
    echo "곧"
    return
  fi
  if [ "$diff" -lt 86400 ]; then
    date -r "$ts" +"%H:%M" 2>/dev/null
  else
    date -r "$ts" +"%m-%d %H:%M" 2>/dev/null
  fi
}

# Git 정보 — branch + ahead/dirty
git_seg() {
  local dir="$1"
  [ -z "$dir" ] && return
  cd "$dir" 2>/dev/null || return
  git rev-parse --git-dir >/dev/null 2>&1 || return
  local branch
  branch=$(git symbolic-ref --short HEAD 2>/dev/null || git rev-parse --short HEAD 2>/dev/null)
  [ -z "$branch" ] && return
  local ahead=0 dirty=0
  if git rev-parse --abbrev-ref @{upstream} >/dev/null 2>&1; then
    ahead=$(git rev-list --count @{upstream}..HEAD 2>/dev/null || echo 0)
  fi
  dirty=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  local seg=" \033[1;35m\033[0m \033[35m${branch}\033[0m"
  [ "$ahead" -gt 0 ] && seg+=" \033[32m+${ahead}\033[0m"
  [ "$dirty" -gt 0 ] && seg+=" \033[33m~${dirty}\033[0m"
  echo -n "$seg"
}

SEP="\033[2m│\033[0m"

# ============================================
# 1행: cc 버전 · 모델 · 디렉터리 · Git · 컨텍스트
# ============================================
line1=""
if [ -n "$cc_version" ]; then
  line1+="\033[2mcc\033[0m \033[2;37mv${cc_version}\033[0m ${SEP} "
fi
line1+="\033[38;5;117m[${model}]\033[0m"

# effort level — 색상은 단계별
if [ -n "$effort" ]; then
  effort_color=$(awk -v e="$effort" 'BEGIN{
    if (e == "xhigh" || e == "max" || e == "maximum") print "\033[1;31m"
    else if (e == "high") print "\033[1;33m"
    else if (e == "medium" || e == "mid") print "\033[1;36m"
    else if (e == "low" || e == "off" || e == "none") print "\033[2m"
    else print "\033[35m"
  }')
  line1+=" ${SEP} ${effort_color}⚡ ${effort}\033[0m"
fi

# 비용
if [ -n "$cost_usd" ]; then
  line1+=" ${SEP} \033[1;32m\$$(printf '%.2f' "$cost_usd") USD\033[0m"
fi

# 디렉터리
if [ -n "$cwd" ]; then
  base=$(basename "$cwd")
  line1+=" ${SEP} \033[2m\033[0m \033[37m${base}\033[0m"
fi

# Git
git_part=$(git_seg "$cwd")
[ -n "$git_part" ] && line1+=" ${SEP}${git_part}"

# ============================================
# 2행: ctx · 입출력 토큰 · 비용 · Rate limits
# ============================================
line2=""

# ctx — 바 + 퍼센트 + 사용량/한도
if [ -n "$ctx_pct" ] || [ -n "$ctx_used" ]; then
  ctx_amount=$(fmt_ctx_amount "$ctx_used" "$ctx_total")
  line2+="\033[2mctx\033[0m"
  if [ -n "$ctx_pct" ]; then
    bar=$(make_bar "$ctx_pct")
    line2+=" ${bar} \033[1m$(printf '%.0f' "$ctx_pct")%\033[0m"
  fi
  if [ -n "$ctx_amount" ]; then
    line2+=" \033[2m(\033[0;36m${ctx_amount}\033[0m\033[2m)\033[0m"
  fi
fi

# 입출력 토큰 — i 92.4K tok · o 8.1K tok
if [ -n "$in_tokens" ] || [ -n "$out_tokens" ]; then
  tok=""
  [ -n "$in_tokens"  ] && tok+="\033[33mi\033[0m \033[1;33m$(fmt_tokens "$in_tokens")\033[0m"
  if [ -n "$out_tokens" ]; then
    [ -n "$tok" ] && tok+=" \033[2m·\033[0m "
    tok+="\033[36mo\033[0m \033[1;36m$(fmt_tokens "$out_tokens")\033[0m"
  fi
  [ -n "$line2" ] && line2+=" ${SEP} "
  line2+="${tok}"
fi

# Rate limits — 5h, 7d (퍼센트 + 리셋 시각, 임계 색상)
rate_color() {
  awk -v p="$1" 'BEGIN{
    if (p+0 >= 80) print "\033[1;31m"
    else if (p+0 >= 50) print "\033[1;33m"
    else print "\033[35m"
  }'
}

if [ -n "$five_pct" ] || [ -n "$week_pct" ]; then
  rl=""
  if [ -n "$five_pct" ]; then
    c=$(rate_color "$five_pct")
    rl+="\033[2m5h\033[0m ${c}$(printf '%.0f' "$five_pct")%\033[0m"
    five_at=$(fmt_reset "$five_reset")
    [ -n "$five_at" ] && rl+=" \033[2mu${five_at}\033[0m"
  fi
  if [ -n "$week_pct" ]; then
    [ -n "$rl" ] && rl+="  "
    c=$(rate_color "$week_pct")
    rl+="\033[2m7d\033[0m ${c}$(printf '%.0f' "$week_pct")%\033[0m"
    week_at=$(fmt_reset "$week_reset")
    [ -n "$week_at" ] && rl+=" \033[2mu${week_at}\033[0m"
  fi
  [ -n "$line2" ] && line2+=" ${SEP} "
  line2+="${rl}"
fi

# ============================================
# 출력
# ============================================
if [ -n "$line2" ]; then
  printf "%b\n%b" "$line1" "$line2"
else
  printf "%b" "$line1"
fi
