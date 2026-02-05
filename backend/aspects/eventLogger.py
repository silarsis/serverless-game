import json
import logging

logging.getLogger().setLevel(logging.INFO)


def handler(event: dict, context: dict):
    logging.info(json.dumps(event, indent=2))
