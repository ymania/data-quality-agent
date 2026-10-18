#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
bash ./start-docker.sh "$@"
result=$?
if ((result != 0)); then read -r -p 'Press Enter to close...' ignored; fi
exit "$result"
