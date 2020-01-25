import json
import logging

# LightStep recommended tracing
from os import environ
environ['DD_TRACE_AGENT_URL'] = 'https://ingest.lightstep.com:443'
environ['DD_TRACE_GLOBAL_TAGS'] = "lightstep.service_name:serverless-game,lightstep.access_token:737Tm/TRGAsgjTifoyTpiX5QctzQf2RYApmjdoLBQxA4XZJMYZtN5J1vVIYEVAX22qx+PRyR11/0unVvoU73d5SQZRh76oik82pBJejc"
from ddtrace import tracer
from ddtrace.propagation.b3 import B3HTTPPropagator
tracer.configure(http_propagator=B3HTTPPropagator)


def lambdaHandler(objectClass):
    def handler(event: dict, context: dict):
        logging.debug(json.dumps(event, indent=2))
        for e in event['Records']:
            objectClass._action(e['Sns']['Message'])
    return handler
