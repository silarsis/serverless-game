# serverless-game

Toy game world with events and lambdas

Design Thoughts:

Rather than an object hierarchy, I want to use mixins. However, I think the
mixins should be lambdas in their own right. So, the idea is that an event
is sent to the bus:

```yaml
event:
  action: location.leave
  source_uuid: <mob uuid>
  target_uuid: <uuid of location being left>
  direction: north
```

The target_uuid is used to determine which object is responsible for processing
the action.

The object checks it's list of mixins, and if there is a movement mixin,
it calls that lambda with the event. If there is not, then the event is
probably dropped on the ground (TODO: Think about this)

The idea here is that you should be able to dynamically add and remove
mixins to objects. The object itself is responsible for gatekeeping the
operation, but the mixin will do the heavy lifting.