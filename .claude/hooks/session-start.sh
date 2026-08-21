#!/bin/bash
set -euo pipefail

# Only run in remote (web) environments
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

echo "=== STONEWALL — SESSION BRIEFING ==="
echo ""

# Count scripts
script_count=$(find "$PROJECT_DIR/scripts" -type f \( -name "*.py" -o -name "*.mjs" -o -name "*.ps1" \) 2>/dev/null | wc -l | tr -d ' ')
echo "  scripts/: $script_count automation scripts"

# Count tests
test_count=$(find "$PROJECT_DIR/tests" -type f \( -name "*.py" -o -name "*.mjs" \) 2>/dev/null | wc -l | tr -d ' ')
echo "  tests/: $test_count test files"

echo ""
echo "Run 'python scripts/tactical_brief.py today' for the daily brief."
echo "Run 'python scripts/verify_repo_consistency.py' for a repo status check."
echo ""
echo "Session ready."
