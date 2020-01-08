
Events
======

Create a new location: (This is now incorrect because mixins)

```yaml
event:
  action: create
  type: Overground
  target_uuid: <uuid of existing location>
  direction: <string direction from target_uuid to add new location>
```

Move a mob to a new location:

```yaml
event:
  action: location.leave
  source_uuid: <mob uuid>
  target_uuid: <uuid of location being left>
  direction: north
event2:
  action: location.arrive
  source_uuid: <mob uuid>
  target_uuid: <uuid of location being entered>
  direction: south
```
