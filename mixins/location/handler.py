


def event_handler(event: dict, context: dict):
    print(json.dumps(event, indent=2))
    return [ingest_event(e['Sns']['Message']) for e in event['Records']]