#!/usr/bin/env sh
set -eu

workspace="/home/agent/workspace"

if [ -f "$workspace/package.json" ]; then
  cd "$workspace"
  npm install
fi

exec sleep infinity
