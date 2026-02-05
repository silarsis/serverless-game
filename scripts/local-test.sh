#!/bin/bash
# Run tests against LocalStack

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=========================================="
echo "Serverless Game - Local Testing"
echo "=========================================="
echo ""

# Check if LocalStack is running
if ! curl -s http://localhost:4566/_localstack/health > /dev/null 2>&1; then
    echo "ERROR: LocalStack is not running. Please run ./scripts/local-setup.sh first."
    exit 1
fi

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "ERROR: Virtual environment not found. Please run ./scripts/local-setup.sh first."
    exit 1
fi

# Set environment for LocalStack
export $(grep -v '^#' .env.local | xargs)

echo "Running tests..."
echo ""

cd backend

# Run pytest with LocalStack environment
pytest -v

echo ""
echo "=========================================="
echo "Tests complete!"
echo "=========================================="
