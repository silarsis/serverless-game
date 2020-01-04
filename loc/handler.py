import json


def ingest_event(ev: dict):
    ev['Sns']['Message']


def lambda_handler(event: dict, context):
    print("Received event: " + json.dumps(event, indent=2))
    # Extract the area uuid from the message
    # Load the data for that area
    # Determine what effect the event will have
    # Execute the effect - save the data or throw more events
    return [ ingest_event(e) for e in event['Records'] ]