# serverless-game

Toy game world with events and lambdas

## Design Thoughts

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
of which only care about their own concerns. They're tied together by uuid. This
saves from collisions between aspects on data names.

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

The above raises a series of challenges if it's done for all inter-object communications:

* How do we do aggregation?
* How do we manipulate return values in the chain so we can map from call to call?
* How do we make the coding not too horrific for callbacks?

So, in the meantime we've also got an ability to instantiate other objects and
aspects locally. Once I've figured out solutions for the above, I may come back and
convert everything to callback, not sure. At least, there needs to be events when
things change.

(Thought: could I do callbacks as yields?)

## Example Event Streams

### Create a mob

```yaml
event:
  aspect: mob
  action: create
```

Creates a mob in the given location. Presumably there will be more details in
the create later, once we have more details to give. For now, this is enough.

This will cause the following sequence of events:

```yaml
event:
  aspect: mob
  action: created
  uuid: <uuid of the new entity>
```

TODO: This is horrible. Synchronous events probably need something other than
the event bus. Think more.

```yaml
event:
  aspect: location
  action: arrive
  uuid: <mob uuid>
  destination: <location uuid>
```

```yaml
event:
  aspect: movement
  action: arrive
  uuid: <mob uuid>
  destination: <location uuid>
```

### "Say" something

This one is interesting. The actor says something - the event with the speech
is thrown out for anyone to listen to, but how do you know what can hear it?

```yaml
event:
  aspect: sound
  action: say
  uuid: <mob uuid>
  location: <location uuid>
  speech: <str>
```

## Relationships

### Location

The Location aspect has it's own table, and stores "locations" (a list of
IDs for other objects it is in) and "contents" (a list of IDs for objects
that are in it). Moving requires unpicking both sides of that relationship.
This is done for speed, although I may be able to index the table better and
drop one side of the data.

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
  uui: <uuid of location player is in>
  aspect: location
  action: list_contained
  callback_data:
    aspect: location
    action: pretty_print
    uuid: <uuid of player>
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

Note you can embed arbitrarily deep callbacks in the callback structure.

Note also there's a 32Kb limit on packet size because it may go through
step functions for delayed messages.

## Setup

To set this up on a fresh machine for local development, do the following:

* Check out the code
* Install nvm-windows from https://github.com/coreybutler/nvm-windows
* Run `nvm on` and `nvm install latest` in the frontend directory
* As admin, run `nvm use latest` in the frontend directory
* Run `npx npm-check-updates -u` and `npm install` in the frontend directory