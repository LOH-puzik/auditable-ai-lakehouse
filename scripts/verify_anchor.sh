#!/usr/bin/env bash
# Verify that an anchored Merkle batch matches its on-chain root.
# Usage: scripts/verify_anchor.sh <BATCH_ID>

set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <BATCH_ID>" >&2
  exit 1
fi

exec uv run verify-anchor --batch-id "$1"
