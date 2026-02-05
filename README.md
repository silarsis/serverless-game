# Serverless Game

A toy game world built with serverless architecture using AWS Lambda, DynamoDB, and SNS.

## Architecture

The game uses an **aspect-oriented** design rather than traditional object hierarchy. Each aspect is a Lambda function that listens to events on an SNS topic:

```yaml
event:
  aspect: location
  action: move
  uuid: <mob uuid>
  data:
    from_loc: <current location uuid>
    to_loc: <new location uuid>
```

### Key Components

- **Aspects**: Lambda functions that handle specific concerns (location, land, etc.)
- **Event Bus**: SNS topic for event-driven communication
- **State Storage**: DynamoDB tables per aspect
- **Message Delayer**: Step Functions for delayed event delivery

## Prerequisites

- Python 3.11+
- Node.js 18+
- Docker and docker-compose (for local development)
- AWS CLI (configured with credentials - for cloud deployment only)
- Serverless Framework v3 (for cloud deployment only)

## Quick Start

### Option 1: Local Development (Recommended)

Run the entire game locally using LocalStack without needing AWS credentials:

```bash
# Clone the repository
git clone <repo-url>
cd serverless-game

# Setup local environment (installs dependencies, starts LocalStack)
./scripts/local-setup.sh

# Run the interactive local game
python scripts/local-runner.py --command interactive
```

### Option 2: Cloud Deployment (requires AWS credentials)

```bash
# Deploy infrastructure
cd infra
serverless deploy --stage prod

# Deploy backend
cd ../backend
serverless deploy --stage prod

# Deploy frontend
cd ../frontend
serverless client deploy --stage prod
```

## Local Development

### Prerequisites

- Docker and docker-compose installed
- Python 3.11+ with pip
- AWS CLI (optional, for interacting with LocalStack)

### Setup

Run the automated setup script:

```bash
./scripts/local-setup.sh
```

This will:
1. Create a Python virtual environment
2. Install all dependencies
3. Copy `.env.local` to `.env`
4. Start LocalStack in Docker
5. Initialize all AWS resources (DynamoDB tables, SNS topic, Step Functions)

### Running the Game Locally

#### Interactive Mode

```bash
python scripts/local-runner.py --command interactive
```

Available commands in interactive mode:
- `create_land_creator` - Create a new LandCreator entity at the origin
- `tick <uuid>` - Send a tick event to a LandCreator (explores the world)
- `explore [n]` - Run n exploration ticks (default: 5)
- `event <json>` - Send a custom event
- `quit` - Exit the game

#### Quick Exploration

```bash
# Create a LandCreator and run 10 exploration ticks
python scripts/local-runner.py --command explore --ticks 10
```

### Local Testing

Run tests against LocalStack:

```bash
./scripts/local-test.sh
```

Or run tests manually:

```bash
cd backend
source ../venv/bin/activate
pytest
```

### LocalStack Configuration

The local development environment uses these default settings (from `.env.local`):

| Variable | Local Value | Description |
|----------|-------------|-------------|
| `AWS_ACCESS_KEY_ID` | `test` | Dummy value for LocalStack |
| `AWS_SECRET_ACCESS_KEY` | `test` | Dummy value for LocalStack |
| `AWS_DEFAULT_REGION` | `ap-southeast-1` | AWS region |
| `LOCALSTACK_ENDPOINT` | `http://localhost:4566` | LocalStack API endpoint |
| `THING_TABLE` | `thing-table-local` | DynamoDB table name |
| `LOCATION_TABLE` | `location-table-local` | DynamoDB table name |
| `LAND_TABLE` | `land-table-local` | DynamoDB table name |
| `THING_TOPIC_ARN` | `arn:aws:sns:ap-southeast-1:000000000000:thing-topic-local` | SNS topic ARN |
| `MESSAGE_DELAYER_ARN` | `arn:aws:states:ap-southeast-1:000000000000:stateMachine:message-delayer-local` | Step Functions ARN |

### Interacting with LocalStack

You can use the AWS CLI with LocalStack:

```bash
# List DynamoDB tables
aws --endpoint-url=http://localhost:4566 dynamodb list-tables

# Scan the land table
aws --endpoint-url=http://localhost:4566 dynamodb scan --table-name land-table-local

# List SNS topics
aws --endpoint-url=http://localhost:4566 sns list-topics
```

### Useful Commands

```bash
# Start LocalStack
docker-compose up -d

# View LocalStack logs
docker-compose logs -f localstack

# Stop LocalStack
docker-compose down

# Remove LocalStack data (reset everything)
docker-compose down -v
rm -rf .localstack

# Re-initialize resources after restart
./scripts/localstack-init.sh
```

### Teardown

To completely clean up the local environment:

```bash
./scripts/local-teardown.sh
```

## Development

### Code Quality

This project uses pre-commit hooks for code quality:

```bash
# Install pre-commit hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

### Testing

```bash
cd backend

# Run all tests (uses moto mocks by default)
pytest

# Run with coverage
pytest --cov=aspects

# Run specific test file
pytest aspects/tests/test_thing.py

# Run tests against LocalStack (uses real AWS services locally)
../scripts/local-test.sh
```

### Linting & Type Checking

```bash
cd backend

# Format code
black .
isort .

# Lint
flake8 .

# Type check
mypy aspects/
```

## CI/CD

This repository uses GitHub Actions for continuous integration and deployment:

- **Lint**: Runs black, isort, flake8, and mypy
- **Test**: Runs pytest with coverage reporting
- **Security**: Bandit security scanning
- **Deploy**: Placeholder for Serverless deployment (requires AWS secrets)

See `.github/workflows/ci.yml` for details.

## Project Structure

```
serverless-game/
├── backend/
│   ├── aspects/              # Lambda handlers (aspects)
│   │   ├── aws_client.py     # AWS client configuration (supports LocalStack)
│   │   ├── thing.py          # Base class for all game objects
│   │   ├── location.py       # Location/movement aspect
│   │   ├── land.py           # Grid-based land system
│   │   ├── landCreator.py    # Auto-generates land
│   │   ├── eventLogger.py    # Logs all events
│   │   ├── handler.py        # Lambda handler factory
│   │   └── tests/            # Unit tests
│   ├── serverless.yml        # Serverless framework config
│   ├── requirements.txt      # Production dependencies
│   ├── requirements-dev.txt  # Development dependencies
│   └── pyproject.toml        # Tool configurations
├── frontend/                 # Web frontend
├── infra/                    # VPC and networking infrastructure
├── scripts/                  # Local development scripts
│   ├── local-setup.sh        # Automated local setup
│   ├── local-teardown.sh     # Cleanup script
│   ├── local-test.sh         # Run tests against LocalStack
│   ├── localstack-init.sh    # Initialize LocalStack resources
│   └── local-runner.py       # Local game runner
├── docker-compose.yml        # LocalStack Docker configuration
├── .env.local                # Local environment template
└── .github/workflows/        # CI/CD pipelines
```

## Environment Configuration

The application supports both local (LocalStack) and cloud (AWS) environments through environment variables:

### Local Development

Set these in `.env` (copied from `.env.local`):

```bash
LOCALSTACK_ENDPOINT=http://localhost:4566
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
THING_TABLE=thing-table-local
...
```

### Cloud Deployment

Set these for production AWS deployment:

```bash
# No LOCALSTACK_ENDPOINT set (uses real AWS)
AWS_ACCESS_KEY_ID=your-real-key
AWS_SECRET_ACCESS_KEY=your-real-secret
THING_TABLE=thing-table-prod
...
```

The `aspects/aws_client.py` module automatically detects LocalStack mode based on the `LOCALSTACK_ENDPOINT` environment variable and configures boto3 clients accordingly.

## Security

### Action Validation

The `Thing._action()` method validates that:
1. Actions cannot start with `_` (private methods)
2. Actions must be decorated with `@callable`
3. Only explicitly allowed actions can be invoked via the event system

This prevents arbitrary code execution via the event bus.

## Event Structure

```yaml
event:
  tid: str              # Transaction ID (mandatory)
  aspect: str           # Aspect name (mandatory)
  action: str           # Action name (mandatory)
  uuid: str             # Entity UUID (mandatory)
  data: {}              # Optional action data
  callback:             # Optional callback
    aspect: str
    action: str
    uuid: str
    data: {}
```

**Note**: There's a 32KB limit on packet size due to Step Functions message delays.

## Aspects

### Location

Handles spatial positioning and movement:
- `create`: Initialize location
- `destroy`: Remove location (moves contents to parent)
- `add_exit`: Create an exit in a direction
- `remove_exit`: Remove an exit

### Land

Grid-based land system extending Location:
- `by_coordinates`: Get or create land at coordinates
- `by_direction`: Get land in a direction
- `add_exit`: Auto-creates land when exit destination is None

### Thing (Base Class)

All game objects inherit from Thing:
- UUID-based identification
- DynamoDB persistence
- Event system integration
- Callback mechanism for async operations

## License

MIT
