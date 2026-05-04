#!/bin/bash
# ===========================================================================
# AgenticAML Code Review Pipeline
# ===========================================================================
# Automated quality, security, and concurrency checks for enterprise-grade
# AML software. Run this after every coding agent build or significant change.
#
# Usage: ./scripts/review-pipeline.sh [--fix] [--load-test]
#   --fix        Auto-fix linting issues where safe
#   --load-test  Run concurrent HTTP load tests (requires running server)
#
# Exit codes:
#   0 = All checks passed
#   1 = Issues found (review output)
# ===========================================================================

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$PROJECT_DIR/src"
TESTS_DIR="$PROJECT_DIR/tests"
FRONTEND_DIR="$PROJECT_DIR/frontend"
RESULTS_DIR="$PROJECT_DIR/review-results"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

# Parse flags
FIX_MODE=false
LOAD_TEST=false
for arg in "$@"; do
    case $arg in
        --fix) FIX_MODE=true ;;
        --load-test) LOAD_TEST=true ;;
    esac
done

mkdir -p "$RESULTS_DIR"

echo "=========================================="
echo "  AgenticAML Review Pipeline"
echo "  $(date)"
echo "=========================================="
echo ""

ISSUES=0

# ---------------------------------------------------------------------------
# Step 1: Ruff (Linting + Async checks)
# ---------------------------------------------------------------------------
echo "--- Step 1: Ruff Lint (async, style, imports) ---"
if $FIX_MODE; then
    ruff check "$SRC_DIR" --fix --output-format=concise 2>&1 | tee "$RESULTS_DIR/ruff-$TIMESTAMP.txt" || true
else
    ruff check "$SRC_DIR" --output-format=concise 2>&1 | tee "$RESULTS_DIR/ruff-$TIMESTAMP.txt" || true
fi
RUFF_ISSUES=$(ruff check "$SRC_DIR" --output-format=json 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
echo "Ruff issues: $RUFF_ISSUES"
ISSUES=$((ISSUES + RUFF_ISSUES))
echo ""

# ---------------------------------------------------------------------------
# Step 2: Mypy (Type checking)
# ---------------------------------------------------------------------------
echo "--- Step 2: Mypy Type Check ---"
# Use relaxed mode since we may not have all stubs; focus on catching
# missing awaits and wrong return types in async code.
mypy "$SRC_DIR" \
    --ignore-missing-imports \
    --no-strict-optional \
    --warn-unused-ignores \
    --warn-return-any \
    --check-untyped-defs \
    2>&1 | tee "$RESULTS_DIR/mypy-$TIMESTAMP.txt" || true
MYPY_ISSUES=$(grep -c "error:" "$RESULTS_DIR/mypy-$TIMESTAMP.txt" 2>/dev/null || echo "0")
echo "Mypy errors: $MYPY_ISSUES"
ISSUES=$((ISSUES + MYPY_ISSUES))
echo ""

# ---------------------------------------------------------------------------
# Step 3: Bandit (Security scan)
# ---------------------------------------------------------------------------
echo "--- Step 3: Bandit Security Scan ---"
# Focus on high and medium severity. Skip low-confidence noise.
bandit -r "$SRC_DIR" \
    --severity-level medium \
    --confidence-level medium \
    -f txt \
    2>&1 | tee "$RESULTS_DIR/bandit-$TIMESTAMP.txt" || true
BANDIT_ISSUES=$(bandit -r "$SRC_DIR" --severity-level medium --confidence-level medium -f json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('results',[])))" 2>/dev/null || echo "0")
echo "Bandit issues: $BANDIT_ISSUES"
ISSUES=$((ISSUES + BANDIT_ISSUES))
echo ""

# ---------------------------------------------------------------------------
# Step 4: Semgrep (Pattern-based analysis)
# ---------------------------------------------------------------------------
echo "--- Step 4: Semgrep Async & Security Patterns ---"
# Use auto config for Python async and security rules.
semgrep scan "$SRC_DIR" \
    --config auto \
    --severity ERROR \
    --severity WARNING \
    --no-git-ignore \
    --timeout 60 \
    2>&1 | tee "$RESULTS_DIR/semgrep-$TIMESTAMP.txt" || true
SEMGREP_ISSUES=$(grep -c "findings" "$RESULTS_DIR/semgrep-$TIMESTAMP.txt" 2>/dev/null || echo "0")
echo ""

# ---------------------------------------------------------------------------
# Step 5: Pytest with asyncio debug mode
# ---------------------------------------------------------------------------
echo "--- Step 5: Pytest (asyncio debug mode) ---"
if [ -d "$TESTS_DIR" ]; then
    cd "$PROJECT_DIR"
    # Activate venv if it exists
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    fi
    PYTHONASYNCIODEBUG=1 python -m pytest "$TESTS_DIR" -v --tb=short \
        2>&1 | tee "$RESULTS_DIR/pytest-$TIMESTAMP.txt" || true
    PYTEST_FAILURES=$(grep -c "FAILED" "$RESULTS_DIR/pytest-$TIMESTAMP.txt" 2>/dev/null || echo "0")
    echo "Pytest failures: $PYTEST_FAILURES"
    ISSUES=$((ISSUES + PYTEST_FAILURES))
else
    echo "No tests directory found, skipping."
fi
echo ""

# ---------------------------------------------------------------------------
# Step 6: Frontend build check
# ---------------------------------------------------------------------------
echo "--- Step 6: Frontend Build Check ---"
if [ -d "$FRONTEND_DIR" ]; then
    cd "$FRONTEND_DIR"
    npm run build 2>&1 | tee "$RESULTS_DIR/frontend-build-$TIMESTAMP.txt" || true
    if grep -q "error" "$RESULTS_DIR/frontend-build-$TIMESTAMP.txt" 2>/dev/null; then
        echo "Frontend build has errors!"
        ISSUES=$((ISSUES + 1))
    else
        echo "Frontend build: OK"
    fi
else
    echo "No frontend directory found, skipping."
fi
echo ""

# ---------------------------------------------------------------------------
# Step 7: Load test (optional, requires running server)
# ---------------------------------------------------------------------------
if $LOAD_TEST; then
    echo "--- Step 7: Concurrent Load Test ---"
    BASE_URL="${API_URL:-http://localhost:8003}"

    echo "Testing GET /transactions (50 concurrent, 200 total)..."
    hey -n 200 -c 50 "$BASE_URL/transactions" 2>&1 | tee "$RESULTS_DIR/loadtest-transactions-$TIMESTAMP.txt" || true

    echo ""
    echo "Testing GET /alerts (50 concurrent, 200 total)..."
    hey -n 200 -c 50 "$BASE_URL/alerts" 2>&1 | tee "$RESULTS_DIR/loadtest-alerts-$TIMESTAMP.txt" || true

    echo ""
    echo "Testing GET /governance/audit-trail (50 concurrent, 200 total)..."
    hey -n 200 -c 50 "$BASE_URL/governance/audit-trail" 2>&1 | tee "$RESULTS_DIR/loadtest-audit-$TIMESTAMP.txt" || true

    echo ""
    echo "Testing POST /transactions/screen (20 concurrent, 100 total)..."
    hey -n 100 -c 20 -m POST \
        -H "Content-Type: application/json" \
        -d '{"customer_id":"test","amount":5000000,"currency":"NGN","transaction_type":"transfer","channel":"mobile_app","counterparty_name":"Test Corp","direction":"outbound"}' \
        "$BASE_URL/transactions/screen" \
        2>&1 | tee "$RESULTS_DIR/loadtest-screen-$TIMESTAMP.txt" || true

    # Check for errors in load test results
    for f in "$RESULTS_DIR"/loadtest-*-$TIMESTAMP.txt; do
        ERROR_COUNT=$(grep -o "Status 5[0-9][0-9]" "$f" 2>/dev/null | wc -l || echo "0")
        if [ "$ERROR_COUNT" -gt "0" ]; then
            echo "WARN: $(basename $f) had $ERROR_COUNT server errors under load"
            ISSUES=$((ISSUES + 1))
        fi
    done
    echo ""
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "=========================================="
echo "  REVIEW SUMMARY"
echo "=========================================="
echo "  Ruff lint issues:    $RUFF_ISSUES"
echo "  Mypy type errors:    $MYPY_ISSUES"
echo "  Bandit security:     $BANDIT_ISSUES"
echo "  Pytest failures:     ${PYTEST_FAILURES:-N/A}"
echo "  Total issues:        $ISSUES"
echo "  Results saved to:    $RESULTS_DIR/"
echo "=========================================="

if [ "$ISSUES" -gt "0" ]; then
    echo "RESULT: Issues found. Review the output above."
    exit 1
else
    echo "RESULT: All checks passed!"
    exit 0
fi
