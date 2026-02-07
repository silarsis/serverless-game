#!/usr/bin/env python3
"""
Local runner for serverless-game

This script simulates the AWS Lambda + SNS infrastructure locally.
It loads environment variables from .env.local, connects to LocalStack,
and processes game events directly through the aspect handlers.

Usage:
    python scripts/local-runner.py
    python scripts/local-runner.py --command "create_land_creator"
    python scripts/local-runner.py --command "tick"
    python scripts/local-runner.py --interactive
"""

import argparse
import json
import logging
import os
import sys
import uuid
from typing import Any, Dict, Optional

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import boto3
from dotenv import load_dotenv

from aspects import land, landCreator, location, thing  # noqa: F401
from aspects.handler import lambdaHandler  # noqa: F401

try:
    from aspects import communication, inventory, npc  # noqa: F401
except ImportError:
    communication = inventory = npc = None

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def setup_localstack_clients(endpoint_url: str = "http://localhost:4566"):
    """Configure boto3 to use LocalStack endpoints."""
    os.environ["AWS_ACCESS_KEY_ID"] = os.environ.get("AWS_ACCESS_KEY_ID", "test")
    os.environ["AWS_SECRET_ACCESS_KEY"] = os.environ.get(
        "AWS_SECRET_ACCESS_KEY", "test"
    )
    os.environ["AWS_DEFAULT_REGION"] = os.environ.get(
        "AWS_DEFAULT_REGION", "ap-southeast-1"
    )

    # Create clients with LocalStack endpoint
    session = boto3.Session()

    dynamodb = session.resource(
        "dynamodb", endpoint_url=endpoint_url, region_name="ap-southeast-1"
    )

    sns = session.resource(
        "sns", endpoint_url=endpoint_url, region_name="ap-southeast-1"
    )

    stepfunctions = session.client(
        "stepfunctions", endpoint_url=endpoint_url, region_name="ap-southeast-1"
    )

    return dynamodb, sns, stepfunctions


def create_event(
    aspect: str,
    action: str,
    uuid: str,
    data: Optional[Dict[str, Any]] = None,
    tid: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a game event."""
    return {
        "tid": tid or str(uuid4()),
        "aspect": aspect,
        "action": action,
        "uuid": uuid,
        "data": data or {},
    }


def invoke_handler(aspect_name: str, event: Dict[str, Any]):
    """Invoke the appropriate handler for an aspect."""
    aspect_map = {
        "Location": location,
        "Land": land,
        "LandCreator": landCreator,
    }
    if communication:
        aspect_map["Communication"] = communication
    if inventory:
        aspect_map["Inventory"] = inventory
    if npc:
        aspect_map["NPC"] = npc

    module = aspect_map.get(aspect_name)
    if not module:
        logger.warning(f"No handler found for aspect: {aspect_name}")
        return

    handler_func = getattr(module, "handler", None)
    if handler_func:
        # Wrap event in SNS format as expected by lambdaHandler
        sns_event = {"Records": [{"Sns": {"Message": json.dumps(event)}}]}
        logger.info(
            f"Invoking {aspect_name} handler with action: {event.get('action')}"
        )
        handler_func(sns_event, {})
    else:
        logger.warning(f"No handler function found in module: {aspect_name}")


def process_single_event(event: Dict[str, Any]):
    """Process a single event by invoking the appropriate handler."""
    aspect = event.get("aspect")
    if aspect:
        invoke_handler(aspect, event)
    else:
        logger.error(f"Event missing 'aspect' field: {event}")


def create_land_creator():
    """Create a LandCreator entity at origin."""
    tid = str(uuid4())
    event = create_event(
        aspect="LandCreator", action="create", uuid=str(uuid4()), tid=tid
    )
    process_single_event(event)
    logger.info("Created LandCreator at origin")
    return event["uuid"]


def tick_land_creator(uuid: str):
    """Send a tick event to a LandCreator."""
    event = create_event(aspect="LandCreator", action="tick", uuid=uuid)
    process_single_event(event)
    logger.info(f"Sent tick to LandCreator {uuid}")


def explore_world(ticks: int = 5):
    """Create a LandCreator and run multiple ticks to explore the world."""
    land_creator_id = create_land_creator()

    for i in range(ticks):
        logger.info(f"=== Tick {i + 1}/{ticks} ===")
        tick_land_creator(land_creator_id)

    logger.info(f"World exploration complete after {ticks} ticks")


def interactive_mode():
    """Run an interactive shell for testing."""
    print("\n=== Serverless Game Local Runner ===")
    print("Available commands:")
    print("  create_land_creator - Create a new LandCreator entity")
    print("  tick <uuid>          - Send tick to a LandCreator")
    print("  explore [n]          - Run n ticks (default 5)")
    print("  event <json>         - Send a custom event")
    print("  quit                 - Exit")
    print()

    land_creators = []

    while True:
        try:
            cmd = input("> ").strip()

            if not cmd:
                continue

            if cmd == "quit":
                break

            if cmd == "create_land_creator":
                uuid = create_land_creator()
                land_creators.append(uuid)
                print(f"Created LandCreator: {uuid}")

            elif cmd.startswith("tick"):
                parts = cmd.split()
                if len(parts) > 1:
                    tick_land_creator(parts[1])
                elif land_creators:
                    tick_land_creator(land_creators[-1])
                else:
                    print("No LandCreator available. Use 'create_land_creator' first.")

            elif cmd.startswith("explore"):
                parts = cmd.split()
                n = int(parts[1]) if len(parts) > 1 else 5
                explore_world(n)

            elif cmd.startswith("event "):
                json_str = cmd[6:]
                try:
                    event = json.loads(json_str)
                    process_single_event(event)
                except json.JSONDecodeError as e:
                    print(f"Invalid JSON: {e}")

            else:
                print(f"Unknown command: {cmd}")

        except KeyboardInterrupt:
            print("\nUse 'quit' to exit")
        except EOFError:
            break
        except Exception as e:
            logger.error(f"Error: {e}")

    print("Goodbye!")


def main():
    parser = argparse.ArgumentParser(description="Local runner for serverless-game")
    parser.add_argument(
        "--command",
        choices=["create_land_creator", "explore", "interactive"],
        default="interactive",
        help="Command to run",
    )
    parser.add_argument(
        "--ticks", type=int, default=5, help="Number of ticks for explore command"
    )
    parser.add_argument(
        "--env-file", default=".env.local", help="Path to environment file"
    )

    args = parser.parse_args()

    # Load environment variables
    env_path = os.path.join(os.path.dirname(__file__), "..", args.env_file)
    if os.path.exists(env_path):
        load_dotenv(env_path)
        logger.info(f"Loaded environment from {args.env_file}")
    else:
        logger.warning(f"Environment file not found: {env_path}")
        # Set defaults
        os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
        os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-1")
        os.environ.setdefault("THING_TABLE", "thing-table-local")
        os.environ.setdefault("LOCATION_TABLE", "location-table-local")
        os.environ.setdefault("LAND_TABLE", "land-table-local")
        os.environ.setdefault(
            "THING_TOPIC_ARN",
            "arn:aws:sns:ap-southeast-1:000000000000:thing-topic-local",
        )
        os.environ.setdefault(
            "MESSAGE_DELAYER_ARN",
            "arn:aws:states:ap-southeast-1:000000000000:stateMachine:message-delayer-local",
        )

    # Setup LocalStack clients
    endpoint = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
    setup_localstack_clients(endpoint)

    logger.info(f"Connected to LocalStack at {endpoint}")

    # Execute command
    if args.command == "create_land_creator":
        create_land_creator()
    elif args.command == "explore":
        explore_world(args.ticks)
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
