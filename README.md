# serverless-game

Toy game world with events and lambdas

Design Thoughts:

Rather than an object hierarchy, I want to use aspects. However, I think the
aspects should be lambdas in their own right. So, the idea is that an event
is sent to the bus:

```yaml
event:
  aspect: location
  action: move
  uuid: <mob uuid>
  data:
    from_loc: <current location uuid>
    to_loc: <new location uuid>
```

The aspects listen to the bus directly, using filters on the SNS subscribe.
When a message is received, the entity is loaded from DynamoDB and the action
is triggered.

Each aspect will have it's own table of data - so all the data and methods for
a given object are actually spread across multiple databases and aspects, all
of which only care about their own concerns.

This way, aspects can be added and removed easily - add a lambda and SNS
subscription, and add the aspect to the appropriate objects in DynamoDB
(or, technically, a aspect could ignore that and just fire anyway).

## Interactions

Interactions can be classified in multiple ways: with or without return value,
information vs command, and targeted vs. non-targeted.

Interactions without return values are just events - there is a helper on the
base class that supports throwing events onto the bus, while also tracking a
transaction ID and making default values right (`_sendEvent`). This applies
to both information and command events, and targeted or not.

Commands or information with a response value are supported via a callback
mechanism. There is a class (`Call`) that provides this functionality.

So, if you want to change another entity, you throw an event that triggers
an action on that entity. If you have changed your own state, you throw
an event to indicate that, in case other entities want to do something about
it. If you want to get information about another entity, you throw an event
that triggers an action on that entity and also provides a callback for the
method to go to once that data is there.

How do we do aggregates? I think it'll probably require aggregation objects,
but let's chase that through and see as we build it.

## Example Event Streams

### Create a mob

```yaml
event:
  aspect: entity
  action: create
  aspects:
    - mob
  request_uuid: <uuid of this request>
```

Creates a mob in the given location. Presumably there will be more details in
the create later, once we have more details to give. For now, this is enough.

This will cause the following sequence of events:

```yaml
event:
  aspect: entity
  action: created
  request_uuid: <uuid of the request>
  new_uuid: <uuid of the new entity>
```

TODO: This is horrible. Synchronous events probably need something other than
the event bus. Think more.

```yaml
event:
  aspect: location
  action: arrive
  actor_uuid: <mob uuid>
  target_uuid: <location uuid>
```

```yaml
event:
  aspect: movement
  action: arrive
  actor_uuid: <mob uuid>
  target_uuid: <location uuid>
```

### Mob moving to a new location

```yaml
event:
  aspect: movement
  action: leave
  actor_uuid: <mob uuid>
  direction: <str>
event:
  aspect: movement
  action: arrive
  actor_uuid: <mob uuid>
  target_uuid: <new location uuid>
```

### "Say" something

This one is interesting. The actor says something - the event with the speech
is thrown out for anyone to listen to, but how do you know what can hear it?
The aspect will

```yaml
event:
  aspect: sound
  action: say
  actor_uuid: <mob uuid>
  location_uuid: <location uuid>
  speech: <str>
```

## Relationships

### Location

An entity can be "in" a location. A location can "contain" entities. Note that
a location is just an entity that can hold other entities (it has the "location"
aspect).

Do we store both of these - entity with a link to location, and location with
a link to entities?

Or do we store the relationships somewhere - a list of "entities inside other
entities" - somehow?

I'm actually inclined to say the "location" aspect has it's own dynamodb table
containing (entity, contains) tuples - one for each direct relationship.

## Concepts / required aspects

* Location
* Appearance (needs location to find what's visible)
* Sound (needs location to find what's audible)

## Callbacks

Say a thing wants to call a aspect, and do something with the results.
To do this on the event bus, we really want to generate an event with
a call to the aspect and all the data, plus callback details and data.
Also need to include a transaction id. So if, for instance, we have a
"loggedin" aspect that handles pretty printing what's going on to an actual
user, and it wants to "look". It might send an event:

```yaml
event:
  tid: <uuid of transaction>
  target_uuid: <uuid of location player is in>
  aspect: location
  action: list_contained
  callback_data:
    aspect: location
    action: pretty_print
    actor_uuid: <uuid of player>
    user: derrick
```

This will call the "list_contained" action, and it will send an event that
has all the data it's meant to provide, plus the callback data, plus retaining
the transaction id (tid).

The loggedin aspect will implement a "pretty_print" action that takes that data
and presents it back to the user (presume the "user" in callback_data is some data
already calculated and needing to be in the return).

For this to work, we need a series of convenience methods on the underlying
objects, for returning data in a consistent way, for packaging up callback data.
We also introduce a callback style of coding to our aspects, unfortunately.

# Event Structure

```yaml
event:
  tid: str transaction ID, mandatory
  aspect: str name of action, mandatory
  action: str name of action, mandatory
  uuid: str name of "self", mandatory
  data: {} optional
  callback: optional
    aspect: str
    action: str
    uuid: str
    data: {}

```
