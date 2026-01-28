#!/bin/bash
# Test with multiple Python versions using uv
# Usage: ./scripts/test_python_versions.sh [versions...]
# Example: ./scripts/test_python_versions.sh 3.10 3.11 3.12 3.13

set -e

# Default Python versions to test
PYTHON_VERSIONS="${@:-3.10 3.11 3.12 3.13}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "Testing with Python versions: $PYTHON_VERSIONS"
echo "======================================"

FAILED_VERSIONS=""
PASSED_VERSIONS=""

for version in $PYTHON_VERSIONS; do
    echo ""
    echo "Testing with Python $version..."
    echo "--------------------------------------"

    # Create virtual environment with specific Python version
    VENV_DIR=".venv-test-$version"

    # Remove existing test venv if it exists
    rm -rf "$VENV_DIR"

    # Create venv with specific Python version
    if ! uv venv "$VENV_DIR" --python "$version" 2>/dev/null; then
        echo "  [SKIP] Python $version not available"
        continue
    fi

    # Install dependencies
    if ! uv pip install --python "$VENV_DIR/bin/python" -e ".[dev]" -q 2>/dev/null; then
        echo "  [FAIL] Failed to install dependencies for Python $version"
        FAILED_VERSIONS="$FAILED_VERSIONS $version"
        rm -rf "$VENV_DIR"
        continue
    fi

    # Run tests
    echo "  Running tests..."
    if "$VENV_DIR/bin/python" -m pytest tests/ -v --tb=short 2>&1 | tail -5; then
        PASSED_VERSIONS="$PASSED_VERSIONS $version"
        echo "  [PASS] Python $version"
    else
        FAILED_VERSIONS="$FAILED_VERSIONS $version"
        echo "  [FAIL] Python $version"
    fi

    # Cleanup test venv
    rm -rf "$VENV_DIR"
done

echo ""
echo "======================================"
echo "Summary:"
if [ -n "$PASSED_VERSIONS" ]; then
    echo "  Passed:$PASSED_VERSIONS"
fi
if [ -n "$FAILED_VERSIONS" ]; then
    echo "  Failed:$FAILED_VERSIONS"
    exit 1
fi
echo "All tested versions passed!"
