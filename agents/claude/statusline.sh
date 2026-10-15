#!/bin/bash
# Claude Code status line
# Left:  dir | git branch/status | context usage bar | model (effort)
# Right (flush to terminal edge): cost | 5h/7d rate limits

# Force a UTF-8 locale so ${#var} counts characters, not bytes -- required
# for correct right-alignment math since the left segment contains
# multibyte glyphs (➜ █ ░ ✗ ↓ ↑). macOS ships en_US.UTF-8; minimal Linux
# installs often only have C.UTF-8, so pick the first one that exists.
if [ -z "$LC_ALL" ]; then
  available=$(locale -a 2>/dev/null)
  for loc in en_US.UTF-8 C.UTF-8; do
    if grep -qix "${loc/UTF-8/utf-?8}" <<< "$available"; then export LC_ALL=$loc; break; fi
  done
fi

input=$(cat)

left=""

cwd=$(echo "$input" | jq -r '.workspace.current_dir')
dir=$(basename "$cwd")
left="${left}$(printf "\033[1;32m➜\033[0m \033[36m%s\033[0m" "$dir")"

if git -C "$cwd" --no-optional-locks rev-parse --git-dir >/dev/null 2>&1; then
  branch=$(git -C "$cwd" --no-optional-locks symbolic-ref --short HEAD 2>/dev/null || git -C "$cwd" --no-optional-locks rev-parse --short HEAD 2>/dev/null)
  [ -n "$branch" ] && left="${left}$(printf " \033[1;34mgit:(\033[31m%s\033[1;34m)" "$branch")"
  if ! git -C "$cwd" --no-optional-locks diff --quiet 2>/dev/null || ! git -C "$cwd" --no-optional-locks diff --cached --quiet 2>/dev/null; then
    left="${left}$(printf "\033[33m✗\033[0m")"
  else
    left="${left}$(printf "\033[0m")"
  fi
fi

used_pct=$(echo "$input" | jq -r '.context_window.used_percentage // empty')
if [ -n "$used_pct" ]; then
  used_int=$(printf "%.0f" "$used_pct")
  bar_width=10
  filled=$(( (used_int * bar_width) / 100 ))
  empty=$(( bar_width - filled ))
  if [ "$used_int" -ge 90 ]; then color="\033[31m"; elif [ "$used_int" -ge 70 ]; then color="\033[33m"; else color="\033[32m"; fi
  bar=""
  i=0
  while [ $i -lt $filled ]; do bar="${bar}█"; i=$((i+1)); done
  i=0
  while [ $i -lt $empty ]; do bar="${bar}░"; i=$((i+1)); done
  total_input=$(echo "$input" | jq -r '.context_window.total_input_tokens // 0')
  ctx_size=$(echo "$input" | jq -r '.context_window.context_window_size // 0')
  total_in_k=$(( total_input / 1000 ))
  if [ "$ctx_size" -eq 1000000 ]; then ctx_size_str="1M"; else ctx_size_str="$(( ctx_size / 1000 ))k"; fi

  # Per-turn breakdown from current_usage. The payload has no cached-output
  # field; cache_creation_input_tokens is shown as "C".
  read -r cu_out cu_cout cu_cin cu_raw < <(echo "$input" | jq -r '.context_window.current_usage | [(.output_tokens // 0), (.cache_creation_input_tokens // 0), (.cache_read_input_tokens // 0), (.input_tokens // 0)] | @tsv')
  cu_in=$(( cu_raw + cu_cin + cu_cout ))
  # Nk with one decimal under 10k so small values don't render as 0k
  fmt_k() {
    local n=$1 t
    if [ "$n" -ge 10000 ]; then printf '%dk' $(( n / 1000 ))
    elif [ "$n" -ge 9950 ]; then printf '10k'
    else t=$(( (n + 50) / 100 )); printf '%d.%dk' $(( t / 10 )) $(( t % 10 )); fi
  }
  dot=$(printf ' \033[90m·\033[0m ')
  breakdown=$(printf "\033[36m↓ %s\033[0m${dot}\033[35mC%s\033[0m${dot}\033[34mR%s\033[0m${dot}\033[37m↑ %s\033[0m" "$(fmt_k "$cu_out")" "$(fmt_k "$cu_cout")" "$(fmt_k "$cu_cin")" "$(fmt_k "$cu_in")")

  # Estimated TTFT / TPS from transcript timestamps (the status-line payload has
  # no timing data). "-" stands in for "no assistant entry yet" so `read` does
  # not collapse empty tab-separated fields.
  # ts_ms: 2026-10-09T16:04:45.975Z -> epoch milliseconds. BSD `date -j`
  # cannot parse fractional seconds, so convert whole seconds and add ms back.
  # GNU date (Linux) takes -d; BSD date (macOS) takes -j -f.
  if date -u -d "1970-01-01T00:00:00Z" +%s >/dev/null 2>&1; then gnu_date=1; else gnu_date=""; fi
  ts_ms() {
    local ts=$1 frac=0 base=$1 secs
    if [[ "$ts" == *.*Z ]]; then
      base="${ts%%.*}Z"; frac="${ts#*.}"; frac="${frac%Z}000"; frac="${frac:0:3}"
    fi
    if [ -n "$gnu_date" ]; then
      secs=$(date -u -d "$base" +%s 2>/dev/null) || return 1
    else
      secs=$(date -j -u -f "%Y-%m-%dT%H:%M:%SZ" "$base" +%s 2>/dev/null) || return 1
    fi
    echo $(( secs * 1000 + 10#$frac ))
  }
  perf_jq='
    [inputs | fromjson? | select(type == "object" and .timestamp != null)] as $e
    | ([$e | to_entries[]
        | select(.value.type == "user" and .value.isMeta != true
                 and ((.value.message.content | type) == "string"))
        | .key] | last) as $i
    | if $i == null then empty else
        [$e[$i + 1:][] | select(.type == "assistant") | .timestamp] as $a
        | ([$e[$i + 1:][] | select(.type == "assistant" and .message.usage != null)
            | {r: .requestId, o: (.message.usage.output_tokens // 0)}]
           | group_by(.r) | map(.[-1].o) | add // 0) as $out
        | [$e[$i].timestamp, ($a[0] // "-"), ($a[-1] // "-"), $out] | @tsv
      end'
  perf=""
  tp=$(echo "$input" | jq -r '.transcript_path // empty')
  if [ -n "$tp" ] && [ -r "$tp" ]; then
    read -r ts0 ts1 ts2 turn_out < <(tail -n 500 "$tp" | jq -nrR "$perf_jq" 2>/dev/null)
    t0=""; [ -n "$ts0" ] && t0=$(ts_ms "$ts0")
    if [ -n "$t0" ]; then
      ttft_str="—"; tps_str="—"
      if [ "$ts1" != "-" ] && [ -n "$ts1" ]; then
        t1=$(ts_ms "$ts1"); t2=$(ts_ms "$ts2")
        if [ -n "$t1" ] && [ "$t1" -ge "$t0" ]; then
          tenths=$(( (t1 - t0 + 50) / 100 ))
          ttft_str=$(printf '%d.%ds' $(( tenths / 10 )) $(( tenths % 10 )))
        fi
        if [ -n "$t1" ] && [ -n "$t2" ] && [ $(( t2 - t1 )) -gt 0 ]; then
          tps_str="$(( (turn_out * 1000 + (t2 - t1) / 2) / (t2 - t1) )) tok/s"
        fi
      fi
      perf=$(printf "\033[38;5;208m~ttft %s\033[0m${dot}\033[38;5;208m~%s\033[0m" "$ttft_str" "$tps_str")
      breakdown="${breakdown}${dot}${perf}"
    fi
  fi

  # Thinking tokens from transcript usage.output_tokens_details. Each API request
  # is written as several entries, so take one value per requestId. The turn
  # figure covers requests since the last human message; the session figure
  # covers the whole transcript.
  think_turn=""; think_session=""
  if [ -n "$tp" ] && [ -r "$tp" ]; then
    think_turn_n=$(tail -n 500 "$tp" | jq -nrR '
      [inputs | fromjson? | select(type == "object")] as $e
      | ([$e | to_entries[]
          | select(.value.type == "user" and .value.isMeta != true
                   and ((.value.message.content | type) == "string"))
          | .key] | last) as $i
      | if $i == null then 0 else
          [$e[$i + 1:][] | select(.type == "assistant" and .message.usage != null)
           | {r: .requestId, t: (.message.usage.output_tokens_details.thinking_tokens // 0)}]
          | group_by(.r) | map(.[-1].t) | add // 0
        end' 2>/dev/null)
    think_session_n=$(jq -rs '
      [.[] | select(type == "object" and .type == "assistant" and .message.usage != null)
       | {r: .requestId, t: (.message.usage.output_tokens_details.thinking_tokens // 0)}]
      | group_by(.r) | map(.[-1].t) | add // 0' "$tp" 2>/dev/null)
    [ -n "$think_turn_n" ] && think_turn=$(fmt_k "$think_turn_n")
    [ -n "$think_session_n" ] && think_session=$(fmt_k "$think_session_n")
  fi
  if [ -n "$think_session" ]; then
    think_seg=$(printf "\033[38;5;141m󱍞 %s %s\033[0m" "${think_turn:-—}" "$think_session")
    breakdown="${breakdown}${dot}${think_seg}"
  fi
  left="${left}$(printf " \033[90m|\033[0m ${color}%s %d%%\033[0m %dk/%s %s" "$bar" "$used_int" "$total_in_k" "$ctx_size_str" "$breakdown")"
fi

model=$(echo "$input" | jq -r '.model.display_name // empty')
effort=$(echo "$input" | jq -r '.effort.level // empty')
if [ -n "$model" ]; then
  if [ -n "$effort" ]; then
    left="${left}$(printf " \033[90m|\033[0m \033[35m%s\033[0m \033[90m(%s)\033[0m" "$model" "$effort")"
  else
    left="${left}$(printf " \033[90m|\033[0m \033[35m%s\033[0m" "$model")"
  fi
fi

# ---- Right-aligned block: total session cost + Claude.ai rate limits ----
right=""
append_right() {
  # append_right <segment>  -- joins segments with " | ", no leading space when first
  if [ -n "$right" ]; then
    right="${right}$(printf " \033[90m|\033[0m ")${1}"
  else
    right="$1"
  fi
}

cost=$(echo "$input" | jq -r '.cost.total_cost_usd // empty')
if [ -n "$cost" ]; then
  append_right "$(printf "\033[90m\$%.2f\033[0m" "$cost")"
fi

five_pct=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')
week_pct=$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')

if [ -n "$five_pct" ]; then
  five_int=$(printf "%.0f" "$five_pct")
  if [ "$five_int" -ge 90 ]; then fcolor="\033[31m"; elif [ "$five_int" -ge 70 ]; then fcolor="\033[33m"; else fcolor="\033[32m"; fi
  append_right "$(printf "${fcolor}5h:%d%%\033[0m" "$five_int")"
fi

if [ -n "$week_pct" ]; then
  week_int=$(printf "%.0f" "$week_pct")
  if [ "$week_int" -ge 90 ]; then wcolor="\033[31m"; elif [ "$week_int" -ge 70 ]; then wcolor="\033[33m"; else wcolor="\033[32m"; fi
  append_right "$(printf "${wcolor}7d:%d%%\033[0m" "$week_int")"
fi

# Strip ANSI escape codes to measure true visible width
esc=$(printf '\033')
strip_ansi() {
  sed "s/${esc}\[[0-9;]*m//g" <<< "$1"
}

left_visible=$(strip_ansi "$left")
right_visible=$(strip_ansi "$right")

cols=${COLUMNS:-$(tput cols 2>/dev/null)}
[ -z "$cols" ] && cols=80

# Claude Code's actual status-line render area is a few columns narrower
# than the terminal width reported by $COLUMNS/tput (it reserves some
# margin for its own chrome). Padding to the full detected width causes
# the rightmost segment to get truncated with "..". Reserve a
# conservative safety margin here. Tune via /tmp/statusline-debug.log
# (see below) if segments are still clipped or there's too much gap.
margin=4
cols=$(( cols - margin ))
[ "$cols" -lt 20 ] && cols=20

if [ -n "$right" ]; then
  pad=$(( cols - ${#left_visible} - ${#right_visible} ))
  [ "$pad" -lt 1 ] && pad=1
  printf "%b" "$left"
  printf "%*s" "$pad" ""
  printf "%b\n" "$right"
else
  printf "%b\n" "$left"
fi

# Debug log for tuning the margin above. Inspect with:
#   tail -20 /tmp/statusline-debug.log
{
  echo "$(date '+%H:%M:%S') COLUMNS=${COLUMNS:-<unset>} tput=$(tput cols 2>/dev/null) cols_used=$cols margin=$margin left_len=${#left_visible} right_len=${#right_visible} pad=${pad:-n/a}"
} >> /tmp/statusline-debug.log 2>/dev/null
