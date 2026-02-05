"""Provides a generic Lambda handler for processing SNS-driven events.

This module defines a function that returns AWS Lambda-compatible handlers.
These invoke actions on provided classes based on inbound SNS event payloads.
"""

import json
import logging

logging.getLogger().setLevel(logging.INFO)

# # LightStep recommended tracing
# TODO: Commented out until I sort out the compilation requirements
# from ddtrace import tracer
# from ddtrace.propagation.b3 import B3HTTPPropagator
# tracer.configure(http_propagator=B3HTTPPropagator)


def lambdaHandler(objectClass):
    """Return a Lambda-compatible handler that dispatches SNS records to the given object class.

    Args:
        objectClass: The class with an `_action` method to handle SNS messages.

    Returns:
        function: Handler suitable for AWS Lambda SNS events.
    """
    def handler(event: dict, context: dict):
        """Process an AWS Lambda event and invoke action on objectClass for each SNS message."""
        logging.info(json.dumps(event, indent=2))
        for e in event["Records"]:
            objectClass._action(
                json.loads(
                    e["Sns"]["Message"]
                )
            )

    return handler
