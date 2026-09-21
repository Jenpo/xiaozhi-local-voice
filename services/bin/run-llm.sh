#!/bin/zsh
exec /Volumes/S/AI-Runtimes/xz/venvs/llm/bin/mlx_lm.server --model /Volumes/S/AI-Runtimes/xz/models/Qwen2.5-3B-Instruct-4bit --host 0.0.0.0 --port 8890 >> /Volumes/S/AI-Runtimes/xz/logs/llm.out.log 2>&1
