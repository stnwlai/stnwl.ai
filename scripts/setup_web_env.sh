#!/usr/bin/env bash
# Bootstrap a web/cloud session: pick a supported interpreter and run the gate.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PY=""
for candidate in python3.13 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
            PY="$candidate"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    echo "setup_web_env: need Python 3.12 or later on PATH" >&2
    exit 1
fi

echo "setup_web_env: repo $REPO_ROOT"
echo "setup_web_env: interpreter $("$PY" --version)"

export PYTHONPATH=src

"$PY" -m unittest discover -s tests -p "test_*.py"
"$PY" -m stonewall build --output build/reference
"$PY" -m stonewall verify --output build/reference
"$PY" scripts/check_public_boundary.py

echo "setup_web_env: ready"
