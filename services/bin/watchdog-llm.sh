#!/bin/zsh
# xz-llm watchdog: restart com.xz.llm if it is down, erroring, or too slow.
# mlx_lm.server drifts after long uptime (stuck single core / 502 / ~10s per call).
LOG=/Volumes/S/AI-Runtimes/xz/logs/watchdog.log
MODEL=/Volumes/S/AI-Runtimes/xz/models/Qwen2.5-3B-Instruct-4bit
UID_N=$(id -u)
THRESHOLD=6   # seconds; normal is 0.5-1.5s
r=$(curl -s -o /dev/null -w "%{http_code} %{time_total}" --max-time 10 \
  -X POST http://127.0.0.1:8890/v1/chat/completions -H "Content-Type: application/json" \
  -d "{\"model\":\"$MODEL\",\"max_tokens\":8,\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}]}" 2>/dev/null)
code=${r%% *}; secs=${r##* }
now=$(date "+%Y-%m-%d %H:%M:%S")
if [ "$code" != "200" ]; then
  echo "$now LLM bad http=$code -> restart com.xz.llm" >> $LOG
  launchctl kickstart -k gui/$UID_N/com.xz.llm
elif [ "${secs%%.*}" -ge $THRESHOLD ]; then
  echo "$now LLM slow ${secs}s -> restart com.xz.llm" >> $LOG
  launchctl kickstart -k gui/$UID_N/com.xz.llm
fi
