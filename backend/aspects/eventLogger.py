"""Event logger aspect for capturing and logging events in JSON format."""

import json
import logging

logging.getLogger().setLevel(logging.INFO)


def handler(event: dict, context: dict):
    """Log the incoming event as formatted JSON for inspection or debugging.

    Args:
        event (dict): The event payload received by the handler.
        context (dict): AWS Lambda context (unused).
    """
    logging.info(json.dumps(event, indent=2))
