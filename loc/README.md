
Events
======

Create a new location:

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
  action: leave
  source_uuid: <mob uuid>
  target_uuid: <uuid of location being left>
event2:
  action: arrive
  source_uuid: <mob uuid>
  target_uuid: <uuid of location being entered>
```
