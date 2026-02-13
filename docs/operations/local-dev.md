# Local Development Guide

*How to run and develop the serverless game locally without AWS credentials.*

## Prerequisites

- **Docker and docker-compose** - For LocalStack AWS emulation
- **Python 3.11+** - Backend development
- **Node.js 18+** - Frontend development (optional for backend work)
- **AWS CLI** - Optional, for debugging LocalStack

## Quick Start

### 1. Automated Setup

```bash
# Clone and enter repository
git clone <repo-url>
cd serverless-game

# Run setup script
./scripts/local-setup.sh
```

This script will:
1. Create Python virtual environment (`venv/`)
2. Install backend dependencies
3. Copy `.env.local` to `.env`
4. Start LocalStack in Docker
5. Create DynamoDB tables, SNS topic, Step Functions

### 2. Verify Setup

```bash
# Check LocalStack is running
docker-compose ps

# Should show: localstack, lambda, stepfunctions-local running
```

### 3. Run Interactive Game

```bash
python scripts/local-runner.py --command interactive
```

**Available commands:**
- `create_land_creator` - Spawn a LandCreator entity at origin
- `tick <uuid>` - Send tick event to entity (explores world)
- `explore [n]` - Run n exploration ticks (default: 5)
- `event <json>` - Send custom event
- `quit` - Exit

## Development Workflows

### Backend Aspect Development

```bash
# 1. Edit your aspect
vim backend/aspects/my_aspect.py

# 2. Run tests
cd backend
source ../venv/bin/activate
pytest tests/test_my_aspect.py -v

# 3. Test manually
python ../scripts/local-runner.py --command interactive
# (use 'event' command to trigger your aspect)
```

### Testing Specific Aspects

```bash
# Send specific event to test aspect
cd backend
source ../venv/bin/activate
python -c "
from lib.event_bus import EventBus
bus = EventBus()
bus.publish({
    'aspect': 'location',
    'action': 'move',
    'uuid': 'test-123',
    'data': {'to_loc': 'loc-456'}
})
"
```

### Debugging with LocalStack

```bash
# List DynamoDB tables
aws --endpoint-url=http://localhost:4566 dynamodb list-tables

# Scan a table
aws --endpoint-url=http://localhost:4566 dynamodb scan --table-name location_table

# View SNS topics
aws --endpoint-url=http://localhost:4566 sns list-topics

# View CloudWatch logs (if configured)
docker-compose logs -f localstack
```

### WebSocket Testing

```bash
# Install wscat
npm install -g wscat

# Connect to local WebSocket
wscat -c ws://localhost:3001

# Send message
> {"action": "subscribe", "entity": "mob-123"}
```

## Common Issues

### LocalStack Won't Start

```bash
# Check Docker is running
docker ps

# Rebuild containers
docker-compose down
docker-compose up -d

# Check logs
docker-compose logs localstack
```

### Tests Fail with Connection Error

```bash
# Ensure LocalStack is running
docker-compose ps

# Restart LocalStack
docker-compose restart localstack

# Re-run setup
./scripts/local-setup.sh
```

### DynamoDB Table Not Found

```bash
# Re-initialize tables
docker-compose exec localstack bash
awslocal dynamodb create-table --cli-input-json file:///tmp/create-tables.json
```

### Import Errors

```bash
# Ensure virtual environment is active
source venv/bin/activate

# Reinstall dependencies
pip install -r backend/requirements.txt
```

## Architecture in Local Dev

```
┌─────────────────────────────────────────┐
│           Your Machine                │
│                                         │
│  ┌──────────┐      ┌──────────────┐   │
│  │ Python   │──────│   LocalStack   │   │
│  │ Scripts  │      │   (Docker)     │   │
│  │ / Tests  │      │                │   │
│  └──────────┘      │  ┌──────────┐  │   │
│                    │  │ DynamoDB │  │   │
│  ┌──────────┐      │  │   SNS    │  │   │
│  │ Frontend │──────│  │ Lambda   │  │   │
│  │ (dev)    │      │  │   etc.   │  │   │
│  └──────────┘      │  └──────────┘  │   │
│                    └──────────────┘   │
└─────────────────────────────────────────┘
```

## Configuration Files

| File | Purpose |
|------|---------|
| `.env.local` | Template environment variables |
| `.env` | Your local config (gitignored) |
| `docker-compose.yml` | LocalStack services |
| `backend/.env` | Backend-specific config |

## Useful Commands

```bash
# Full reset (nuclear option)
docker-compose down -v
./scripts/local-setup.sh

# View LocalStack logs
docker-compose logs -f localstack

# Stop all services
docker-compose down

# Quick test run
./scripts/local-test.sh

# Run specific test
cd backend && pytest tests/test_location_aspect.py::test_move -v
```

## Cloud Deployment (Not Local)

For actual AWS deployment, see `deployment.md`. Local development intentionally uses LocalStack to avoid:
- AWS credential requirements
- Cloud costs during development
- Deployment latency for testing

## Next Steps

After local development:
1. Read `../context/onboarding.md` for code structure
2. Check `../quality/assessment.md` for what needs work
3. Pick a feature from `../design/catalog.md` to implement

---

*LocalStack enables rapid iteration without cloud costs or credentials.*
*Last updated: 2026-02-12 (extracted from root README.md)*
