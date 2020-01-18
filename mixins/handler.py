import json
import logging


def lambdaHandler(objectClass):
    def handler(event: dict, context: dict):
        logging.debug(json.dumps(event, indent=2))
        for e in event['Records']:
            objectClass._action(e['Sns']['Message'])
    return handler
