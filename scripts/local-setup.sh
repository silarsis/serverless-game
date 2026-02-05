#!/bin/bash
# Setup script for local development with LocalStack

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=========================================="
echo "Serverless Game - Local Development Setup"
echo "=========================================="
echo ""

# Check prerequisites
echo "Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "ERROR: docker-compose is not installed. Please install docker-compose first."
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed. Please install Python 3.11+ first."
    exit 1
fi

echo "✓ All prerequisites found"
echo ""

# Create Python virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

echo "Activating virtual environment..."
source venv/bin/activate

# Install Python dependencies
echo "Installing Python dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r backend/requirements-dev.txt
pip install --quiet python-dotenv  # For local runner

echo "✓ Python dependencies installed"
echo ""

# Copy environment file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env file from template..."
    cp .env.local .env
    echo "✓ Created .env file (you can customize this for local settings)"
else
    echo "✓ .env file already exists"
fi
echo ""

# Start LocalStack
echo "Starting LocalStack..."
docker-compose up -d

echo "Waiting for LocalStack to be ready..."
until curl -s http://localhost:4566/_localstack/health | grep -q '"dynamodb": "running"'; do
    echo "  Waiting for services to start..."
    sleep 3
done

echo "✓ LocalStack is running"
echo ""

# Initialize resources
echo "Initializing AWS resources in LocalStack..."
bash scripts/localstack-init.sh

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "LocalStack is running at: http://localhost:4566"
echo ""
echo "Next steps:"
echo "  1. Run the local game:"
echo "     python scripts/local-runner.py"
echo ""
echo "  2. Or use interactive mode:"
echo "     python scripts/local-runner.py --command interactive"
echo ""
echo "  3. Run tests against LocalStack:"
echo "     ./scripts/local-test.sh"
echo ""
echo "  4. Stop LocalStack when done:"
echo "     docker-compose down"
echo ""
