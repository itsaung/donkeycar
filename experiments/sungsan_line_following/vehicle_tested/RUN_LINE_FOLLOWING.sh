#!/bin/bash
set -euo pipefail

SNAPSHOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SNAPSHOT_DIR"
source /home/sungsan/env/bin/activate

exec python line_following_drive_sungsan.py drive \
  --myconfig=myconfig_line_following_sungsan.py \
  --log=INFO
