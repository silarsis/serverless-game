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
- AWS CLI (configured with credentials)
- Serverless Framework v3

## Quick Start

### 1. Install Dependencies

```bash
# Backend
cd backend
python -m pip install -r requirements-dev.txt

# Frontend
cd ../frontend
npm install
```

### 2. Run Tests

```bash
cd backend
pytest
```

### 3. Deploy (requires AWS credentials)

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

# Run all tests
pytest

# Run with coverage
pytest --cov=aspects

# Run specific test file
pytest aspects/tests/test_thing.py
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
│   ├── aspects/          # Lambda handlers (aspects)
│   │   ├── thing.py      # Base class for all game objects
│   │   ├── location.py   # Location/movement aspect
│   │   ├── land.py       # Grid-based land system
│   │   ├── landCreator.py # Auto-generates land
│   │   ├── eventLogger.py # Logs all events
│   │   ├── handler.py    # Lambda handler factory
│   │   └── tests/        # Unit tests
│   ├── serverless.yml    # Serverless framework config
│   ├── requirements.txt  # Production dependencies
│   ├── requirements-dev.txt # Development dependencies
│   └── pyproject.toml    # Tool configurations
├── frontend/             # Web frontend
├── infra/                # VPC and networking infrastructure
└── .github/workflows/    # CI/CD pipelines
```

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
