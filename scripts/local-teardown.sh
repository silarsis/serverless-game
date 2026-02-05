#!/bin/bash
# Teardown script for local development

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=========================================="
echo "Serverless Game - Local Teardown"
echo "=========================================="
echo ""

# Stop LocalStack
if docker-compose ps -q | grep -q .; then
    echo "Stopping LocalStack containers..."
    docker-compose down
    echo "✓ LocalStack stopped"
else
    echo "LocalStack is not running"
fi

# Optional: remove LocalStack data
read -p "Remove LocalStack data volumes? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Removing LocalStack data..."
    rm -rf .localstack
    echo "✓ LocalStack data removed"
fi

echo ""
echo "=========================================="
echo "Teardown complete!"
echo "=========================================="
