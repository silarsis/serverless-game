# serverless-game

Toy game world with events and lambdas

Design Thoughts:

Rather than an object hierarchy, I want to use mixins. However, I think the
mixins should be lambdas in their own right. So, the idea is that an event
is sent to the bus:

```yaml
event:
  mixin: location
  action: leave
  actor_uuid: <mob uuid>
  leaving_uuid: <location uuid>
  direction: north
```

The actor_uuid is used to determine which object is being moved, in this case.

The mixins listen to the bus directly, using filters on the SNS subscribe.
When a message is received, the entity is loaded from DynamoDB and a check
is made to see if that entity has that mixin. If it does, then the action
is triggered.

This way, mixins can be added and removed easily - add a lambda and SNS
subscription, and add the mixin to the appropriate objects in DynamoDB
(or, technically, a mixin could ignore the and just fire anyway).

This also allows for a mixin to fire on an action regardless of the mixin.
For example, we might implement "look" as an event with an action of "look",
that every mixin can respond to:

```yaml
event:
  mixin: player
  action: look
  actor_uuid: <mob uuid>
```

This is a generic "look around". Theoretically, a whole bunch of mixins could
respond to this, by filtering for the action and not the mixin. This would
cause a slew of events in response, which theoretically something would be
listening for and collating to send back.

## Interactions

Interactions between entities should take one of three forms:

* Command event thrown - entity A throws an event that should result in
  some change of state of the entity.
* Information event thrown - entity A throws an event that other entities
  may observe, but probably don't act on.
* Synchronous - entity A calls another lambda directly to trigger an action
  and get a response.

Command and Information are perilously close, as an information event can
trigger a command event easily. Synchronous vs. non-synchronous may or may not
be important - the use case I'm thinking of is a "create, then place" sequence,
where something needs to create an entity, get the uuid for the newly created
entity, then place that entity somewhere. Alternately, we could send an event
to create that carries extra information for the subsequent event - kind of an
event-based webhook.

## Example Event Streams

### Create a mob

```yaml
event:
  mixin: entity
  action: create
  mixins:
    - mob
  request_uuid: <uuid of this request>
```

Creates a mob in the given location. Presumably there'll be more details in
the create later, once we have more details to give. For now, this is enough.

This will cause the following sequence of events:

```yaml
event:
  mixin: entity
  action: created
  request_uuid: <uuid of the request>
  new_uuid: <uuid of the new entity>
```

TODO: This is horrible. Synchronous events probably need something other than
the event bus. Think more.

```yaml
event:
  mixin: location
  action: arrive
  actor_uuid: <mob uuid>
  target_uuid: <location uuid>
```

```yaml
event:
  mixin: movement
  action: arrive
  actor_uuid: <mob uuid>
  target_uuid: <location uuid>
```

### Mob moving to a new location

```yaml
event:
  mixin: movement
  action: leave
  actor_uuid: <mob uuid>
  direction: <str>
event:
  mixin: movement
  action: arrive
  actor_uuid: <mob uuid>
  target_uuid: <new location uuid>
```

### "Say" something

This one is interesting. The actor says something - the event with the speech
is thrown out for anyone to listen to, but how do you know what can hear it?
The mixin will

```yaml
event:
  mixin: sound
  action: say
  actor_uuid: <mob uuid>
  location_uuid: <location uuid>
  speech: <str>
```

## Relationships

### Location

An entity can be "in" a location. A location can "contain" entities. Note that
a location is just an entity that can hold other entities (it has the "location"
mixin).

Do we store both of these - entity with a link to location, and location with
a link to entities?

Or do we store the relationships somewhere - a list of "entities inside other
entities" - somehow?

I'm actually inclined to say the "location" mixin has it's own dynamodb table
containing (entity, contains) tuples - one for each direct relationship.

## Concepts / required mixins

* Location
* Appearance (needs location to find what's visible)
* Sound (needs location to find what's audible)

## Callbacks

Say a thing wants to call a mixin, and do something with the results.
To do this on the event bus, we really want to generate an event with
a call to the mixin and all the data, plus callback details and data.
Also need to include a transaction id. So if, for instance, we have a
"loggedin" mixin that handles pretty printing what's going on to an actual
user, and it wants to "look". It might send an event:

```yaml
event:
  tid: <uuid of transaction>
  target_uuid: <uuid of location player is in>
  mixin: location
  action: list_contained
  callback: pretty_print
  callback_data:
    user: derrick
```

This will call the "list_contained" action, and it will send an event that
has all the data it's meant to provide, plus the callback data, plus retaining
the transaction id (tid).

The loggedin mixin will implement a "pretty_print" action that takes that data
and presents it back to the user (presume the "user" in callback_data is a key
to find that user's websocket).

For this to work, we need a series of convenience methods on the underlying
objects, for returning data in a consistent way, for packaging up callback data.
We also introduce a callback style of coding to our mixins, unfortunately.