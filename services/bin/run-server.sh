#!/bin/zsh
export PATH=/Volumes/S/AI-Runtimes/xz/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
cd /Volumes/S/AI-Runtimes/xz/server || exit 1
exec /Volumes/S/AI-Runtimes/xz/venvs/server/bin/python app.py >> /Volumes/S/AI-Runtimes/xz/logs/server.out.log 2>&1
