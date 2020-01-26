import json
import logging

# # LightStep recommended tracing
# TODO: Commented out until I sort out the compilation requirements
# from ddtrace import tracer
# from ddtrace.propagation.b3 import B3HTTPPropagator
# tracer.configure(http_propagator=B3HTTPPropagator)


def lambdaHandler(objectClass):
    def handler(event: dict, context: dict):
        logging.debug(json.dumps(event, indent=2))
        for e in event['Records']:
            objectClass._action(e['Sns']['Message'])
    return handler
