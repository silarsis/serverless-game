# Collaborative Projects Aspect

## What This Brings to the World

Collaborative projects are the mechanism that turns a world of individual agents doing individual things into a world where agents need each other. Every other system in the game -- combat, crafting, building, trading -- can be performed solo. A single agent can fight a monster, craft a sword, build a house, and sell goods at a merchant. None of these require coordination with another entity. Collaborative projects change this by introducing goals that are impossible for a single agent to complete alone. A bridge across a canyon requires three agents contributing different materials simultaneously. A ritual to open a sealed dungeon gate requires five participants performing synchronized actions. A settlement wall requires contributions from dozens of agents over hours. These are the activities that force agents to find each other, communicate, negotiate, and cooperate -- the fundamental behaviors that make a multiplayer world meaningful rather than a collection of parallel single-player experiences.

For AI agents specifically, collaborative projects provide structured coordination protocols that are far more tractable than unstructured social interaction. An AI agent told to "be social" has no clear action to take. An AI agent told to "join project bridge-construction-47a, which needs 5 stone and 3 wood contributions and currently has 2 of 4 required participants" has a clear, actionable goal with measurable progress. The project system gives agents a coordination API: propose a goal, join it, contribute to it, check its status, and receive notification of completion. This is collaboration-as-game-mechanic rather than collaboration-as-emergent-behavior, which is exactly what AI agents need to reliably cooperate.

However, this system introduces the most complex shared mutable state in the entire architecture. A project entity is written to by multiple agents concurrently, each contributing resources or actions that modify the same progress tracking data. The put_item-based save model (last write wins) is fundamentally incompatible with concurrent multi-writer workloads. Two agents contributing to the same project within the same second will have one contribution silently dropped. This is not a theoretical concern -- it is the expected usage pattern. The entire point of the system is that multiple agents act on the same data simultaneously. Every other aspect in the game has entities modified by a single owner (the player who owns them). Projects are the first entity that multiple agents write to, and the architecture provides no tools for safe multi-writer access.

## Critical Analysis

**Concurrent contribution is a guaranteed data loss scenario under put_item.** When two agents call `project contribute` on the same project within the same DynamoDB write window, both Lambda invocations load the project entity, both read the current `contributions` list, both append their contribution, and both call `_save()` which does `put_item` (full item replacement). The second write overwrites the first. Agent A contributes 5 wood. Agent B contributes 3 stone. Both read contributions = []. Agent A writes contributions = [{agent_a, wood, 5}]. Agent B writes contributions = [{agent_b, stone, 3}], overwriting A's contribution. Agent A's wood is consumed from inventory (the Inventory modification happened before the project save) but not recorded on the project. This is the most critical bug in the entire design and it occurs during the system's primary use case. DynamoDB's UpdateItem with list_append expression would solve this, but the codebase exclusively uses put_item. Adding UpdateItem for this one aspect would be architecturally inconsistent, though arguably necessary.

**Project entities persist indefinitely with no cleanup mechanism.** A proposed project that nobody joins sits in DynamoDB forever. An abandoned project with partial contributions sits in DynamoDB forever. A completed project whose artifact has been picked up sits in DynamoDB forever. Over time, locations accumulate dead project entities that appear in `project list` results and consume contents GSI read capacity. The Building aspect has the same problem with structures, but structures provide ongoing value (they have rooms, exits, interactions). A failed project provides nothing. With 50 agents proposing 2 projects per day, the system accumulates 100 abandoned project entities daily. After a month, that is 3000 dead entities in the contents GSI. A cleanup mechanism (abandoned projects decay after 24 hours, completed projects are archived to a cold table after 48 hours) is essential but adds Step Functions ticks: 1 check per project per decay interval = $0.000025 per project per check.

**Phase transitions require a consistency check that loads multiple entities.** When a contribution brings a phase's requirements to 100%, the system must verify all contributions are still valid before advancing to the next phase. This means loading each contributor's entity to confirm they still have the items they pledged (items could be dropped, traded, or consumed between contribution and phase completion). For a phase requiring 5 contributions from 3 agents, that is 3 entity loads + 3 Inventory aspect loads + 5 item entity loads = 11 DynamoDB reads just for validation. If the validation fails (an item was consumed), the system must decide whether to reject the phase transition, remove the invalid contribution, or proceed anyway. Each choice has different implications for agent trust and UX. The design below chooses "consume items at contribution time" to avoid this validation problem, but this means contributed items are destroyed even if the project is later abandoned -- agents lose resources to failed projects with no recovery mechanism.

**Resource consumption at contribution time versus at phase completion is a fundamental design tension.** If items are consumed immediately when contributed (simpler, no validation needed), agents lose resources to abandoned projects permanently. If items are reserved but not consumed until phase completion (safer for agents), the system needs an item-locking mechanism that does not exist in the codebase. The Inventory aspect has no concept of "reserved" items -- an item is either in your inventory (location = your UUID) or it is not. A lock would require either: (a) a new field on the Inventory aspect (`reserved_by: project_uuid`), which the Inventory take/drop commands would need to check, coupling Inventory to Projects; or (b) physically moving items to the project entity's inventory (location = project UUID), which is semantically the same as consumption but allows returning items if the project is abandoned. The design below uses option (b): contributed items are moved to the project entity, and project abandonment returns items to the last contributor. This is the least-bad option.

**Project discovery is location-scoped, creating a coordination chicken-and-egg problem.** Projects are proposed at a location and visible only to agents at that location via `project list`. This means Agent A must propose a project and then wait at that location for other agents to arrive, discover the project, and join. But other agents have no reason to visit that location unless they know a project exists there. There is no global project board, no cross-location project announcement, no way for an agent three rooms away to learn that a project needs participants. The Communication aspect's `say` command broadcasts only to the current room. An agent could manually walk to adjacent rooms and announce the project, but this is error-prone and tedious. A `project announce` command that broadcasts to adjacent rooms (1-2 tile radius) would help but adds O(N) broadcast costs where N = entities in surrounding rooms. The design includes a location-broadcast event on project creation, but this only reaches agents already present.

**The project template registry is another hardcoded Python dict requiring code deployment.** Like the quest registry, crafting recipe registry, building blueprint registry, and faction registry, project templates are defined as a module-level dict. Adding a new project type requires editing Python source and deploying. This is the sixth system in the game with this same anti-pattern. The cumulative effect is significant: every piece of game content is locked behind a code deploy. For a system specifically designed around player/agent-initiated activities, hardcoded templates are particularly constraining. A compromise: define a small set of templates for structured projects (bridge, wall, ritual) but also support freeform projects where the proposer defines the requirements at creation time, with no template needed.

**Milestone notifications fan out to all participants, creating O(P) push_event calls per milestone.** When a project phase completes, every participant receives a notification. Each notification requires loading the participant entity (1 DynamoDB read) and calling push_event (1 API Gateway POST). For a project with 10 participants and 5 phases, that is 50 entity loads + 50 WebSocket posts over the project's lifetime just for phase notifications, plus contribution confirmations, completion events, and status updates. A project with 20 participants sends 20 push_events per phase completion. This is the same O(N) fan-out problem as broadcast_to_location but with a participant list that can span multiple locations (participants do not need to stay at the project location after joining).

**Completed projects create permanent world changes, but the mechanism for "permanent world changes" is undefined.** The design says completed projects create "new terrain entity, modified room description, an artifact item." Creating a terrain entity is straightforward (new Entity + Inventory aspect with is_terrain=true). Creating an artifact item is straightforward (new Entity + Inventory aspect with is_item=true). But modifying a room description requires writing to the Land aspect of the room entity, which is a cross-aspect write (Projects aspect modifying Land data). This is the same violation flagged in the Building design (08-building-construction.md). The alternative is to add a "project_modifications" field to the room's Land data that the description generator reads, but this couples Land to Projects. The cleanest approach is to create a new terrain entity at the location with a description that augments the room's base description -- this is additive, not mutative, and fits the existing pattern of terrain entities in rooms.

**DynamoDB item size will grow with contributions.** Each contribution record stores contributor UUID (36 bytes), item type (variable), quantity (int), timestamp (8 bytes), and phase reference (variable). A large project with 50 contributions accumulates roughly 5KB of contribution data. The project entity also stores the template, phase definitions, participant list, and status. A complex multi-phase project with 20 participants and 50 contributions could reach 10-15KB. This is well under the 400KB limit but significantly larger than typical aspect records (which are usually under 1KB). The put_item writes become more expensive per WCU as item size grows (items over 1KB consume additional WCU proportional to their size: 1 WCU per 1KB written).

**Cost assessment: moderate write volume, high read volume, manageable Step Functions cost.** A typical project lifecycle involves: 1 create (2 writes: entity + aspect), N joins (1 read + 1 write each), M contributions (2 reads + 2 writes each -- load project + load item, save project + move item), P phase completions (1 read + P push_events each), and 1 completion (2 reads + 3+ writes for artifact creation). For a project with 5 participants, 15 contributions, and 3 phases: 2 + 5 + 30 + 3 + 5 = 45 writes and 2 + 5 + 30 + 3 + 2 = 42 reads over the project's lifetime. Spread over hours, this is negligible. The concern is burst: 5 agents contributing simultaneously to the same project generates 10 writes within seconds, which will throttle on a 1 WCU table. Step Functions are used only for optional decay timers, not for ticks, so the recurring cost is zero for active projects.

**Overall assessment: this system has the right idea but fights the architecture.** The fundamental assumption of the entity/aspect model is single-owner writes. Projects violate this assumption by their nature. The put_item-based save model makes concurrent contributions unsafe. The location-scoped discovery model makes project coordination difficult. The hardcoded template registry limits player/agent creativity. Despite these issues, the system fills a genuine gap: there is currently no mechanism for multi-agent collaboration, and without one, the game is fundamentally a single-player experience with chat. The recommendation is to implement with two critical modifications: (1) move item consumption to the project entity (items physically moved, not just recorded) to avoid validation complexity, and (2) serialize all project writes through a single Lambda invocation using SNS ordering or a DynamoDB conditional write on a version counter to prevent lost updates.

## Overview

The Projects aspect enables multiple entities to collaborate on shared goals that create permanent world changes. Projects are proposed at a location, joined by participants, and advanced through phases by contributing resources or performing actions. Each phase has specific requirements (materials, participant count, actions) that must be met before the project advances. Completed projects produce artifacts: new terrain entities, special items, or world modifications. Projects differ from quests (system-defined, individual) and from building (single-player, template-driven) by being agent-initiated, multi-participant, and creating emergent collaborative content.

## Design Principles

**Projects are entities.** A project is an entity with a Projects aspect, located at the room where it was proposed. This fits the existing model -- no new storage concepts. The project entity appears in the room's contents and can be discovered via `look`.

**Consume on contribute.** When an agent contributes an item to a project, the item is physically moved to the project entity's inventory (item.location = project.uuid). This avoids the need for item-locking or deferred validation. If the project is abandoned, items can be returned. If the project completes, items are consumed (destroyed) as part of the artifact creation.

**Phases gate progress.** Projects are divided into ordered phases, each with specific requirements. Phase 1 must complete before Phase 2 begins. This prevents agents from rushing to the end and ensures that different types of contributions (gathering, building, activating) happen in the intended order.

**Notifications keep participants informed.** Every significant project event (new participant, contribution, phase completion, project completion) generates push_events to all participants. Agents do not need to poll -- they receive structured updates about project progress.

**Templates plus freeform.** Predefined project templates cover common collaborative activities (bridge, wall, ritual). Freeform projects allow agents to define custom requirements, enabling emergent collaboration without code deployment.

## Aspect Data

Stored in **LOCATION_TABLE** (shared aspect table, keyed by entity UUID):

### On the project entity:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Project entity UUID (primary key) |
| project_name | str | "" | Display name of the project |
| project_description | str | "" | Description of the project goal |
| template_id | str | "" | Template ID if template-based, "" if freeform |
| proposer_uuid | str | "" | UUID of the entity that proposed this project |
| status | str | "proposed" | Current status: proposed, active, completed, abandoned |
| participants | list | [] | List of participant UUIDs |
| max_participants | int | 10 | Maximum number of participants |
| min_participants | int | 2 | Minimum participants required to start |
| phases | list | [] | Ordered list of phase definitions |
| current_phase | int | 0 | Index of the active phase |
| contributions | list | [] | List of contribution records |
| created_at | int | 0 | Unix timestamp of project creation |
| completed_at | int | 0 | Unix timestamp of project completion |
| artifact_template | dict | {} | What to create on completion |

### On the participant entity:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Entity UUID (primary key) |
| active_projects | list | [] | List of project UUIDs the entity has joined |
| completed_projects | list | [] | List of completed project UUIDs |
| total_contributions | int | 0 | Lifetime contribution count (for stats) |

### Phase Definition Structure

```python
{
    "phase_index": 0,
    "name": "Gathering Materials",
    "description": "Collect the raw materials needed for construction.",
    "requirements": {
        "materials": {
            "wood": 10,
            "stone": 15,
            "rope": 5,
        },
        "min_contributors": 2,
        "actions": [],
    },
    "progress": {
        "materials": {
            "wood": 0,
            "stone": 0,
            "rope": 0,
        },
        "contributors": [],
        "actions_completed": [],
    },
    "status": "active",  # pending, active, completed
}
```

### Contribution Record Structure

```python
{
    "contributor_uuid": "agent-uuid",
    "contributor_name": "AgentAlpha",
    "phase_index": 0,
    "contribution_type": "material",  # material, action, presence
    "material_type": "wood",
    "quantity": 5,
    "item_uuids": ["item-uuid-1", "item-uuid-2", "item-uuid-3", "item-uuid-4", "item-uuid-5"],
    "timestamp": 1700000000,
}
```

### Project Template Registry

```python
PROJECT_TEMPLATES = {
    "bridge": {
        "name": "Wooden Bridge",
        "description": "A sturdy bridge spanning a gap, connecting two areas.",
        "min_participants": 2,
        "max_participants": 6,
        "phases": [
            {
                "name": "Gather Materials",
                "description": "Collect wood, rope, and stone for the bridge foundation.",
                "requirements": {
                    "materials": {"wood": 15, "stone": 8, "rope": 5},
                    "min_contributors": 2,
                },
            },
            {
                "name": "Construction",
                "description": "Assemble the bridge components. All participants must be present.",
                "requirements": {
                    "materials": {},
                    "min_contributors": 2,
                    "actions": ["assemble"],
                    "all_present": True,
                },
            },
        ],
        "artifact": {
            "type": "terrain",
            "name": "Wooden Bridge",
            "description": "A sturdy wooden bridge built through cooperative effort. Planks creak underfoot.",
            "terrain_type": "bridge",
            "tags": ["structure", "collaborative", "bridge"],
        },
        "completion_message": "The bridge is complete! A new path opens across the divide.",
    },
    "watchtower_outpost": {
        "name": "Watchtower Outpost",
        "description": "A tall watchtower for surveying the surrounding terrain.",
        "min_participants": 3,
        "max_participants": 8,
        "phases": [
            {
                "name": "Foundation",
                "description": "Lay the stone foundation for the watchtower.",
                "requirements": {
                    "materials": {"stone": 20, "wood": 5},
                    "min_contributors": 2,
                },
            },
            {
                "name": "Frame Construction",
                "description": "Build the wooden frame of the tower.",
                "requirements": {
                    "materials": {"wood": 25, "metal": 8},
                    "min_contributors": 3,
                },
            },
            {
                "name": "Final Assembly",
                "description": "Complete the tower and install the observation platform.",
                "requirements": {
                    "materials": {"wood": 5, "metal": 3, "cloth": 4},
                    "min_contributors": 2,
                    "actions": ["assemble"],
                    "all_present": True,
                },
            },
        ],
        "artifact": {
            "type": "terrain",
            "name": "Watchtower Outpost",
            "description": "A collaboratively-built watchtower rises above the landscape, offering a commanding view.",
            "terrain_type": "watchtower",
            "tags": ["structure", "collaborative", "watchtower", "extended_vision"],
        },
        "completion_message": "The watchtower stands tall! The surrounding area is now visible from its peak.",
    },
    "ritual_circle": {
        "name": "Ritual Circle",
        "description": "A mystical circle of standing stones, imbued with collective energy.",
        "min_participants": 3,
        "max_participants": 5,
        "phases": [
            {"name": "Collect Ritual Components", "requirements": {"materials": {"stone": 8, "herb": 10, "crystal": 3}, "min_contributors": 2}},
            {"name": "Arrange Stones", "requirements": {"min_contributors": 3, "actions": ["arrange"], "all_present": True}},
            {"name": "Activate the Circle", "requirements": {"min_contributors": 3, "actions": ["activate"], "all_present": True}},
        ],
        "artifact": {"type": "terrain", "name": "Ritual Circle", "terrain_type": "ritual_circle",
                      "description": "A circle of standing stones hums with latent energy. Glyphs glow faintly.",
                      "tags": ["structure", "collaborative", "magical"], "effects": {"magic_amplifier": True}},
        "completion_message": "The ritual circle pulses with energy!",
    },
    "settlement_wall": {
        "name": "Settlement Wall",
        "description": "A defensive wall to protect a settlement or camp.",
        "min_participants": 4,
        "max_participants": 15,
        "phases": [
            {"name": "Quarry Stone", "requirements": {"materials": {"stone": 40, "wood": 10}, "min_contributors": 3}},
            {"name": "Lay Foundation", "requirements": {"materials": {"stone": 20}, "min_contributors": 4, "actions": ["dig"], "all_present": True}},
            {"name": "Build Wall", "requirements": {"materials": {"stone": 30, "wood": 15, "metal": 5}, "min_contributors": 4}},
            {"name": "Install Gate", "requirements": {"materials": {"wood": 10, "metal": 10}, "min_contributors": 2, "actions": ["assemble"], "all_present": True}},
        ],
        "artifact": {"type": "terrain", "name": "Settlement Wall", "terrain_type": "wall",
                      "description": "A sturdy stone wall built by collective effort. A gated entrance allows passage.",
                      "tags": ["structure", "collaborative", "defensive", "wall"], "effects": {"defense_bonus": True}},
        "completion_message": "The settlement wall is complete! This area is now fortified.",
    },
}
```

## Commands

### `project propose <name> [template_id]`

```python
@player_command
def project_propose(self, name: str, template_id: str = "", description: str = "") -> dict:
    """Propose a new collaborative project at the current location."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| name | str | Yes | Display name for the project |
| template_id | str | No | Template from PROJECT_TEMPLATES registry |
| description | str | No | Custom description (required if no template) |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "project_proposed" |
| project_uuid | str | UUID of the created project entity |
| project_name | str | Name of the project |
| template | str | Template ID if used |
| message | str | Confirmation message |

**Behaviour:**

1. Validate entity is at a location (not nowhere)
2. Check entity does not exceed max active projects (default: 3)
3. If template_id provided, load template from PROJECT_TEMPLATES; if not, require description and at least one phase definition
4. Create project entity at the current location with Projects aspect
5. Set proposer_uuid, status="proposed", add proposer to participants
6. Initialize phases from template or freeform definition
7. Add project UUID to proposer's active_projects
8. Broadcast project_proposed event to location
9. Return confirmation

```python
@player_command
def project_propose(self, name: str, template_id: str = "", description: str = "") -> dict:
    """Propose a new collaborative project at the current location."""
    if not name:
        return {"type": "error", "message": "Project needs a name."}

    location_uuid = self.entity.location
    if not location_uuid:
        return {"type": "error", "message": "You are nowhere."}

    # Check active project limit
    active = self.data.get("active_projects", [])
    if len(active) >= 3:
        return {"type": "error", "message": "You already have 3 active projects. Complete or leave one first."}

    # Load template or validate freeform
    if template_id:
        template = PROJECT_TEMPLATES.get(template_id)
        if not template:
            available = ", ".join(PROJECT_TEMPLATES.keys())
            return {"type": "error", "message": f"Unknown template. Available: {available}"}
        description = description or template["description"]
        phases = template["phases"]
        artifact_template = template.get("artifact", {})
        min_participants = template.get("min_participants", 2)
        max_participants = template.get("max_participants", 10)
    else:
        if not description:
            return {"type": "error", "message": "Freeform projects need a description."}
        # Freeform: single phase with no material requirements (proposer defines later)
        phases = [{
            "name": "Collaboration",
            "description": description,
            "requirements": {"materials": {}, "min_contributors": 2},
        }]
        artifact_template = {}
        min_participants = 2
        max_participants = 10

    # Build phase data with progress tracking
    import time
    phase_data = []
    for i, phase_def in enumerate(phases):
        phase_data.append({
            "phase_index": i,
            "name": phase_def["name"],
            "description": phase_def["description"],
            "requirements": phase_def.get("requirements", {}),
            "progress": {
                "materials": {k: 0 for k in phase_def.get("requirements", {}).get("materials", {})},
                "contributors": [],
                "actions_completed": [],
            },
            "status": "active" if i == 0 else "pending",
        })

    # Create the project entity
    project_entity = Entity()
    project_entity.data["name"] = name
    project_entity.data["location"] = location_uuid
    project_entity.data["aspects"] = ["Projects"]
    project_entity.data["primary_aspect"] = "Projects"
    project_entity._save()

    # Create the Projects aspect record for the project entity
    project_aspect = Projects()
    project_aspect.data["uuid"] = project_entity.uuid
    project_aspect.data["project_name"] = name
    project_aspect.data["project_description"] = description
    project_aspect.data["template_id"] = template_id
    project_aspect.data["proposer_uuid"] = self.entity.uuid
    project_aspect.data["status"] = "proposed"
    project_aspect.data["participants"] = [self.entity.uuid]
    project_aspect.data["max_participants"] = max_participants
    project_aspect.data["min_participants"] = min_participants
    project_aspect.data["phases"] = phase_data
    project_aspect.data["current_phase"] = 0
    project_aspect.data["contributions"] = []
    project_aspect.data["created_at"] = int(time.time())
    project_aspect.data["completed_at"] = 0
    project_aspect.data["artifact_template"] = artifact_template
    project_aspect._save()

    # Add to proposer's active projects
    self.data.setdefault("active_projects", []).append(project_entity.uuid)
    self._save()

    # Broadcast to location
    self.entity.broadcast_to_location(location_uuid, {
        "type": "project_proposed",
        "project_uuid": project_entity.uuid,
        "project_name": name,
        "proposer": self.entity.name,
        "proposer_uuid": self.entity.uuid,
        "description": description,
        "template": template_id,
        "participants_needed": min_participants,
        "message": f"{self.entity.name} has proposed a new project: {name}. Use 'project join {project_entity.uuid}' to participate.",
    })

    return {
        "type": "project_proposed",
        "project_uuid": project_entity.uuid,
        "project_name": name,
        "template": template_id,
        "message": f"You propose the project '{name}'. Waiting for participants ({1}/{min_participants}).",
    }
```

**Example:**

```
> project propose "Canyon Bridge" bridge
You propose the project 'Canyon Bridge'. Waiting for participants (1/2).

# Other agents at the location see:
AgentAlpha has proposed a new project: Canyon Bridge. Use 'project join <uuid>' to participate.
```

**DynamoDB cost:** 1 entity write + 1 aspect write (project creation) + 1 aspect read + 1 aspect write (proposer's Projects aspect) + O(N) reads for broadcast = 2 reads + 2 writes + broadcast cost.

### `project join <project_id>`

```python
@player_command
def project_join(self, project_id: str) -> dict:
    """Join an active project at the current location."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | Yes | UUID of the project to join |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "project_joined" |
| project_uuid | str | UUID of the project |
| project_name | str | Name of the project |
| participants | int | Current participant count |
| message | str | Confirmation message |

**Behaviour:**

1. Load the project entity and its Projects aspect
2. Validate project exists, is at the same location, and is not completed/abandoned
3. Validate entity is not already a participant
4. Validate participant limit not reached
5. Check entity's active project limit (max 3)
6. Add entity UUID to project's participants list
7. Add project UUID to entity's active_projects
8. If participants >= min_participants and status is "proposed", transition to "active"
9. Notify all existing participants of the new joiner
10. Return confirmation

```python
@player_command
def project_join(self, project_id: str) -> dict:
    """Join an active project at the current location."""
    if not project_id:
        return {"type": "error", "message": "Join which project?"}

    # Check active project limit
    active = self.data.get("active_projects", [])
    if len(active) >= 3:
        return {"type": "error", "message": "You already have 3 active projects."}

    # Load project entity
    try:
        project_entity = Entity(uuid=project_id)
    except KeyError:
        return {"type": "error", "message": "That project doesn't exist."}

    if project_entity.location != self.entity.location:
        return {"type": "error", "message": "That project isn't at this location."}

    # Load project aspect
    try:
        project = project_entity.aspect("Projects")
    except (ValueError, KeyError):
        return {"type": "error", "message": "That's not a project."}

    status = project.data.get("status", "")
    if status in ("completed", "abandoned"):
        return {"type": "error", "message": f"That project is {status}."}

    if self.entity.uuid in project.data.get("participants", []):
        return {"type": "error", "message": "You're already part of this project."}

    participants = project.data.get("participants", [])
    if len(participants) >= project.data.get("max_participants", 10):
        return {"type": "error", "message": "This project has reached its participant limit."}

    # Add participant
    participants.append(self.entity.uuid)
    project.data["participants"] = participants

    # Check if we reached minimum participants to activate
    min_p = project.data.get("min_participants", 2)
    if len(participants) >= min_p and project.data.get("status") == "proposed":
        project.data["status"] = "active"

    project._save()

    # Add to joiner's active projects
    self.data.setdefault("active_projects", []).append(project_id)
    self._save()

    # Notify existing participants
    project_name = project.data.get("project_name", "Unknown")
    for p_uuid in participants:
        if p_uuid == self.entity.uuid:
            continue
        try:
            participant = Entity(uuid=p_uuid)
            participant.push_event({
                "type": "project_participant_joined",
                "project_uuid": project_id,
                "project_name": project_name,
                "new_participant": self.entity.name,
                "new_participant_uuid": self.entity.uuid,
                "total_participants": len(participants),
                "message": f"{self.entity.name} has joined the project '{project_name}' ({len(participants)}/{project.data.get('max_participants', 10)}).",
            })
        except KeyError:
            continue

    return {
        "type": "project_joined",
        "project_uuid": project_id,
        "project_name": project_name,
        "participants": len(participants),
        "status": project.data.get("status", "proposed"),
        "message": f"You join the project '{project_name}' ({len(participants)} participants).",
    }
```

**Example:**

```
> project join a1b2c3d4-...
You join the project 'Canyon Bridge' (3 participants).

# Other participants see:
AgentBeta has joined the project 'Canyon Bridge' (3/6).
```

**DynamoDB cost:** 1 read (project entity) + 1 read (project aspect) + 1 write (project aspect) + 1 read + 1 write (joiner's aspect) + O(P) reads for participant notifications = 3 reads + 2 writes + P reads.

### `project contribute <project_id> <material_type> [quantity]`

```python
@player_command
def project_contribute(self, project_id: str, material_type: str = "", quantity: int = 1, action: str = "") -> dict:
    """Contribute materials or perform an action for a project."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | Yes | UUID of the project |
| material_type | str | No | Tag of the material to contribute (e.g., "wood") |
| quantity | int | No | Number of items to contribute (default: 1) |
| action | str | No | Action to perform (e.g., "assemble", "dig") |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "project_contribution" |
| project_uuid | str | UUID of the project |
| material_type | str | What was contributed |
| quantity | int | How many contributed |
| phase_progress | dict | Current phase progress |
| message | str | Confirmation message |

**Behaviour:**

1. Load and validate project (exists, active, entity is a participant)
2. Determine current phase and its requirements
3. For material contributions:
   a. Scan entity's inventory for items with matching tag
   b. Verify enough items are available
   c. Move items to the project entity (item.location = project.uuid)
   d. Update phase progress
4. For action contributions:
   a. Verify the action is required by the current phase
   b. If "all_present" required, verify all min_contributors are at the location
   c. Record the action as completed
5. Check if phase requirements are now met; if so, advance to next phase
6. Check if all phases are complete; if so, complete the project
7. Notify all participants of the contribution
8. Return confirmation with updated progress

```python
@player_command
def project_contribute(self, project_id: str, material_type: str = "", quantity: int = 1, action: str = "") -> dict:
    """Contribute materials or perform an action for a project."""
    if not project_id:
        return {"type": "error", "message": "Contribute to which project?"}
    if not material_type and not action:
        return {"type": "error", "message": "Contribute what? Specify a material type or action."}

    # Load project
    try:
        project_entity = Entity(uuid=project_id)
    except KeyError:
        return {"type": "error", "message": "That project doesn't exist."}

    try:
        project = project_entity.aspect("Projects")
    except (ValueError, KeyError):
        return {"type": "error", "message": "That's not a project."}

    if project.data.get("status") != "active":
        return {"type": "error", "message": f"Project is {project.data.get('status', 'unknown')}. Must be active to contribute."}

    if self.entity.uuid not in project.data.get("participants", []):
        return {"type": "error", "message": "You're not part of this project. Use 'project join' first."}

    # Get current phase
    phase_idx = project.data.get("current_phase", 0)
    phases = project.data.get("phases", [])
    if phase_idx >= len(phases):
        return {"type": "error", "message": "All phases are already complete."}

    phase = phases[phase_idx]
    requirements = phase.get("requirements", {})
    progress = phase.get("progress", {})

    import time

    if material_type:
        # Material contribution
        required_materials = requirements.get("materials", {})
        if material_type not in required_materials:
            return {"type": "error", "message": f"Phase '{phase['name']}' doesn't need '{material_type}'."}

        already_contributed = progress.get("materials", {}).get(material_type, 0)
        still_needed = required_materials[material_type] - already_contributed
        if still_needed <= 0:
            return {"type": "error", "message": f"Phase '{phase['name']}' already has enough '{material_type}'."}

        # Cap contribution at what's still needed
        actual_quantity = min(quantity, still_needed)

        # Find items in inventory with matching tag
        contributed_items = []
        for item_uuid in self.entity.contents:
            if len(contributed_items) >= actual_quantity:
                break
            try:
                item_entity = Entity(uuid=item_uuid)
                item_inv = item_entity.aspect("Inventory")
                if not item_inv.data.get("is_item"):
                    continue
                item_tags = item_inv.data.get("tags", [])
                if material_type in item_tags:
                    contributed_items.append((item_entity, item_uuid))
            except (KeyError, ValueError):
                continue

        if len(contributed_items) < actual_quantity:
            return {
                "type": "error",
                "message": f"You only have {len(contributed_items)} '{material_type}' but tried to contribute {actual_quantity}.",
            }

        # Move items to project entity (consume on contribute)
        item_uuids_moved = []
        for item_entity, item_uuid in contributed_items:
            item_entity.location = project_entity.uuid
            item_uuids_moved.append(item_uuid)

        # Update phase progress
        progress.setdefault("materials", {})[material_type] = already_contributed + actual_quantity
        if self.entity.uuid not in progress.get("contributors", []):
            progress.setdefault("contributors", []).append(self.entity.uuid)

        # Record contribution
        contribution_record = {
            "contributor_uuid": self.entity.uuid,
            "contributor_name": self.entity.name,
            "phase_index": phase_idx,
            "contribution_type": "material",
            "material_type": material_type,
            "quantity": actual_quantity,
            "item_uuids": item_uuids_moved,
            "timestamp": int(time.time()),
        }
        project.data.setdefault("contributions", []).append(contribution_record)

        contrib_message = f"You contribute {actual_quantity} {material_type} to '{phase['name']}'."

    elif action:
        # Action contribution
        required_actions = requirements.get("actions", [])
        if action not in required_actions:
            return {"type": "error", "message": f"Phase '{phase['name']}' doesn't require action '{action}'."}

        # Check all_present requirement
        if requirements.get("all_present", False):
            min_contributors = requirements.get("min_contributors", 2)
            participants_at_location = []
            for p_uuid in project.data.get("participants", []):
                try:
                    p_entity = Entity(uuid=p_uuid)
                    if p_entity.location == project_entity.location:
                        participants_at_location.append(p_uuid)
                except KeyError:
                    continue
            if len(participants_at_location) < min_contributors:
                return {
                    "type": "error",
                    "message": f"Action '{action}' requires {min_contributors} participants present. Only {len(participants_at_location)} are here.",
                }

        # Record the action
        if self.entity.uuid not in progress.get("contributors", []):
            progress.setdefault("contributors", []).append(self.entity.uuid)

        action_record = {
            "actor_uuid": self.entity.uuid,
            "action": action,
            "timestamp": int(time.time()),
        }
        progress.setdefault("actions_completed", []).append(action_record)

        contribution_record = {
            "contributor_uuid": self.entity.uuid,
            "contributor_name": self.entity.name,
            "phase_index": phase_idx,
            "contribution_type": "action",
            "action": action,
            "quantity": 1,
            "item_uuids": [],
            "timestamp": int(time.time()),
        }
        project.data.setdefault("contributions", []).append(contribution_record)

        contrib_message = f"You perform '{action}' for phase '{phase['name']}'."

    # Update participant stats
    self.data["total_contributions"] = self.data.get("total_contributions", 0) + 1

    # Check if phase is complete
    phase_complete = self._check_phase_complete(phase)
    if phase_complete:
        phase["status"] = "completed"
        next_phase_idx = phase_idx + 1

        if next_phase_idx < len(phases):
            # Advance to next phase
            project.data["current_phase"] = next_phase_idx
            phases[next_phase_idx]["status"] = "active"
            contrib_message += f"\n  Phase '{phase['name']}' complete! Next: '{phases[next_phase_idx]['name']}'."

            # Notify all participants of phase completion
            self._notify_participants(project, {
                "type": "project_phase_complete",
                "project_uuid": project_id,
                "project_name": project.data.get("project_name", ""),
                "completed_phase": phase["name"],
                "next_phase": phases[next_phase_idx]["name"],
                "next_phase_requirements": phases[next_phase_idx].get("requirements", {}),
                "message": f"Phase '{phase['name']}' is complete! Next phase: '{phases[next_phase_idx]['name']}'.",
            })
        else:
            # All phases complete -- finalize project
            result = self._complete_project(project, project_entity)
            contrib_message += f"\n  PROJECT COMPLETE! {result.get('message', '')}"

    project.data["phases"] = phases
    project._save()
    self._save()

    # Notify participants of contribution (unless we already sent phase/completion notifications)
    if not phase_complete:
        self._notify_participants(project, {
            "type": "project_contribution",
            "project_uuid": project_id,
            "project_name": project.data.get("project_name", ""),
            "contributor": self.entity.name,
            "contributor_uuid": self.entity.uuid,
            "contribution": material_type or action,
            "quantity": quantity if material_type else 1,
            "phase": phase["name"],
            "message": f"{self.entity.name} contributed to '{phase['name']}'.",
        }, exclude_uuid=self.entity.uuid)

    return {
        "type": "project_contribution",
        "project_uuid": project_id,
        "material_type": material_type,
        "action": action,
        "quantity": quantity if material_type else 1,
        "phase_progress": progress,
        "phase_name": phase["name"],
        "message": contrib_message,
    }
```

**Example:**

```
> project contribute a1b2c3d4-... wood 5
You contribute 5 wood to 'Gather Materials'.

# If phase completes:
You contribute 5 wood to 'Gather Materials'.
  Phase 'Gather Materials' complete! Next: 'Construction'.

# Other participants see:
AgentAlpha contributed to 'Gather Materials'.
```

**DynamoDB cost:** 1 read (project entity) + 1 read (project aspect) + O(N) reads (inventory scan for materials, N = inventory size) + Q writes (move Q items to project) + 1 write (project aspect save) + 1 write (self aspect save) + O(P) reads (participant notifications) = 2 + N + P reads, Q + 2 writes.

### `project status <project_id>`

```python
@player_command
def project_status(self, project_id: str) -> dict:
    """Check the status and progress of a project."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | Yes | UUID of the project |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "project_status" |
| project_uuid | str | UUID of the project |
| project_name | str | Project display name |
| status | str | Current status |
| participants | list | List of participant names and UUIDs |
| current_phase | dict | Current phase with progress details |
| phases_completed | int | Number of completed phases |
| phases_total | int | Total number of phases |
| contributions_count | int | Total contributions made |
| message | str | Formatted status summary |

**Behaviour:**

1. Load project entity and Projects aspect
2. Validate project exists (no location requirement -- can check status of any known project)
3. Build progress summary for current phase
4. Load participant names (1 entity read per participant)
5. Return structured status data

```python
@player_command
def project_status(self, project_id: str) -> dict:
    """Check the status and progress of a project."""
    if not project_id:
        return {"type": "error", "message": "Check status of which project?"}

    try:
        project_entity = Entity(uuid=project_id)
    except KeyError:
        return {"type": "error", "message": "That project doesn't exist."}

    try:
        project = project_entity.aspect("Projects")
    except (ValueError, KeyError):
        return {"type": "error", "message": "That's not a project."}

    # Build participant list with names
    participant_info = []
    for p_uuid in project.data.get("participants", []):
        try:
            p_entity = Entity(uuid=p_uuid)
            participant_info.append({
                "uuid": p_uuid,
                "name": p_entity.name,
            })
        except KeyError:
            participant_info.append({"uuid": p_uuid, "name": "(unknown)"})

    # Current phase details
    phases = project.data.get("phases", [])
    current_idx = project.data.get("current_phase", 0)
    current_phase = None
    phases_completed = 0

    for i, phase in enumerate(phases):
        if phase.get("status") == "completed":
            phases_completed += 1
        if i == current_idx and phase.get("status") != "completed":
            requirements = phase.get("requirements", {})
            progress = phase.get("progress", {})
            material_progress = {}
            for mat, needed in requirements.get("materials", {}).items():
                have = progress.get("materials", {}).get(mat, 0)
                material_progress[mat] = f"{have}/{needed}"
            current_phase = {
                "name": phase["name"],
                "description": phase.get("description", ""),
                "material_progress": material_progress,
                "contributors": len(progress.get("contributors", [])),
                "min_contributors": requirements.get("min_contributors", 0),
                "actions_required": requirements.get("actions", []),
                "actions_done": [a["action"] for a in progress.get("actions_completed", [])],
            }

    # Build status message
    status = project.data.get("status", "unknown")
    project_name = project.data.get("project_name", "Unknown")
    lines = [f"Project: {project_name} [{status}]"]
    lines.append(f"Participants: {', '.join(p['name'] for p in participant_info)} ({len(participant_info)})")
    lines.append(f"Progress: {phases_completed}/{len(phases)} phases complete")
    if current_phase:
        lines.append(f"Current Phase: {current_phase['name']}")
        lines.append(f"  {current_phase['description']}")
        if current_phase["material_progress"]:
            for mat, prog in current_phase["material_progress"].items():
                lines.append(f"  - {mat}: {prog}")
        if current_phase["actions_required"]:
            done = set(current_phase["actions_done"])
            for act in current_phase["actions_required"]:
                mark = "[done]" if act in done else "[needed]"
                lines.append(f"  - action '{act}': {mark}")

    return {
        "type": "project_status",
        "project_uuid": project_id,
        "project_name": project_name,
        "status": status,
        "participants": participant_info,
        "current_phase": current_phase,
        "phases_completed": phases_completed,
        "phases_total": len(phases),
        "contributions_count": len(project.data.get("contributions", [])),
        "message": "\n".join(lines),
    }
```

**Example:**

```
> project status a1b2c3d4-...
Project: Canyon Bridge [active]
Participants: AgentAlpha, AgentBeta, AgentGamma (3)
Progress: 1/2 phases complete
Current Phase: Construction
  Assemble the bridge components. All participants must be present.
  - action 'assemble': [needed]
```

**DynamoDB cost:** 1 read (project entity) + 1 read (project aspect) + O(P) reads (participant names) = 2 + P reads, 0 writes.

### `project list`

```python
@player_command
def project_list(self) -> dict:
    """List active projects at the current location."""
```

**Parameters:** None.

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "project_list" |
| projects | list | List of project summaries at this location |
| message | str | Formatted list |

**Behaviour:**

1. Get entity's current location
2. Query contents of the location (contents GSI)
3. For each entity at the location, check if it has a Projects aspect with a project status
4. Filter to non-completed/non-abandoned projects
5. Return summary of each project

```python
@player_command
def project_list(self) -> dict:
    """List active projects at the current location."""
    location_uuid = self.entity.location
    if not location_uuid:
        return {"type": "error", "message": "You are nowhere."}

    location_entity = Entity(uuid=location_uuid)
    projects = []
    for entity_uuid in location_entity.contents:
        try:
            entity = Entity(uuid=entity_uuid)
            if "Projects" not in entity.data.get("aspects", []):
                continue
            project = entity.aspect("Projects")
            status = project.data.get("status", "")
            if status in ("completed", "abandoned"):
                continue
            phases = project.data.get("phases", [])
            completed = sum(1 for p in phases if p.get("status") == "completed")
            projects.append({
                "uuid": entity_uuid, "name": project.data.get("project_name", "Unknown"),
                "status": status, "participants": len(project.data.get("participants", [])),
                "max_participants": project.data.get("max_participants", 10),
                "progress": f"{completed}/{len(phases)} phases",
            })
        except (KeyError, ValueError):
            continue

    if not projects:
        return {"type": "project_list", "projects": [], "message": "No active projects at this location."}

    return {"type": "project_list", "projects": projects,
            "message": "\n".join([f"  [{p['status']}] {p['name']} ({p['participants']}/{p['max_participants']}, {p['progress']}) UUID: {p['uuid']}" for p in projects])}
```

**Example:**

```
> project list
Projects at this location:
  [active] Canyon Bridge (3/6 participants, 1/2 phases)
    UUID: a1b2c3d4-...
  [proposed] Ritual Circle (1/3 participants, 0/3 phases)
    UUID: e5f6g7h8-...
```

**DynamoDB cost:** 1 read (location entity) + O(N) reads for contents (N = entities at location) + O(M) reads for Projects aspects of project entities (M = project entities found) = 1 + 2N reads worst case (each entity requires 1 entity read + possibly 1 aspect read), 0 writes.

### `project leave <project_id>`

```python
@player_command
def project_leave(self, project_id: str) -> dict:
    """Leave a project you have joined."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | Yes | UUID of the project to leave |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "project_left" |
| project_uuid | str | UUID of the project |
| message | str | Confirmation message |

**Behaviour:**

1. Load project entity and aspect
2. Validate entity is a participant
3. Remove entity from participants list
4. Remove project from entity's active_projects
5. If entity was the proposer and no other participants remain, abandon the project and return contributed items to their original contributors
6. If participants drop below min_participants, revert status from "active" to "proposed"
7. Notify remaining participants
8. Return items contributed by the leaving entity (move them from project entity back to the leaving entity)

```python
@player_command
def project_leave(self, project_id: str) -> dict:
    """Leave a project you have joined."""
    # Load and validate project, verify entity is participant
    # Return items contributed by this entity (move from project back to entity)
    # Recalculate phase progress excluding leaving entity's contributions
    # Remove from contributions list and participants list
    # If no participants remain: status -> "abandoned"
    # If below min_participants: status -> "proposed"
    # Notify remaining participants
    # Return confirmation with count of returned items
```

**Example:**

```
> project leave a1b2c3d4-...
You leave the project 'Canyon Bridge'. 3 contributed items returned to your inventory.
```

**DynamoDB cost:** 1 read (project entity) + 1 read (project aspect) + R writes (return R items) + 1 write (project aspect) + 1 write (self aspect) + O(P) reads (notifications) = 2 + P reads, R + 2 writes.

### `project abandon <project_id>`

```python
@player_command
def project_abandon(self, project_id: str) -> dict:
    """Abandon a project you proposed. Returns all contributed items to their contributors."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | str | Yes | UUID of the project to abandon |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "project_abandoned" |
| project_uuid | str | UUID of the project |
| message | str | Confirmation message |

**Behaviour:**

1. Validate entity is the project proposer
2. Return all contributed items to their respective contributors
3. Set project status to "abandoned"
4. Remove project from all participants' active_projects
5. Notify all participants
6. Return confirmation

```python
@player_command
def project_abandon(self, project_id: str) -> dict:
    """Abandon a project you proposed. Returns all contributed items."""
    # Validate entity is the project proposer, project is not already completed/abandoned
    # Return all contributed items to their respective contributors
    #   (iterate contributions, move each item back: item.location = contributor_uuid)
    # Set project status to "abandoned"
    # Remove project from all participants' active_projects lists
    # Notify all participants via push_event
    # Return confirmation with count of items returned
```

**DynamoDB cost:** 1 read (project entity) + 1 read (project aspect) + I writes (return I items) + 1 write (project aspect) + O(P) reads + O(P) writes (participant cleanup) + O(P) push_events = 2 + 2P reads, I + 1 + P writes.

## Callable Methods

### `_check_phase_complete`

```python
def _check_phase_complete(self, phase: dict) -> bool:
    """Check if all requirements for a phase are met."""
```

Internal helper that compares phase progress against phase requirements. Checks: all material quantities met, minimum contributors reached, all required actions performed.

```python
def _check_phase_complete(self, phase: dict) -> bool:
    """Check if all requirements for a phase are met."""
    requirements = phase.get("requirements", {})
    progress = phase.get("progress", {})

    # Check materials
    for material, needed in requirements.get("materials", {}).items():
        contributed = progress.get("materials", {}).get(material, 0)
        if contributed < needed:
            return False

    # Check min contributors
    min_c = requirements.get("min_contributors", 0)
    if min_c > 0 and len(progress.get("contributors", [])) < min_c:
        return False

    # Check actions
    required_actions = set(requirements.get("actions", []))
    completed_actions = set(a["action"] for a in progress.get("actions_completed", []))
    if not required_actions.issubset(completed_actions):
        return False

    return True
```

### `_complete_project`

```python
def _complete_project(self, project: "Projects", project_entity: Entity) -> dict:
    """Finalize a completed project: create artifacts and notify participants."""
```

Called when the final phase of a project is completed. Creates the artifact (terrain entity, item, or world modification) and notifies all participants.

```python
def _complete_project(self, project, project_entity) -> dict:
    """Finalize a completed project: create artifacts and notify."""
    import time
    project.data["status"] = "completed"
    project.data["completed_at"] = int(time.time())

    artifact_template = project.data.get("artifact_template", {})
    artifact_uuid = None
    artifact_name = "the completed project"

    if artifact_template:
        artifact_type = artifact_template.get("type", "terrain")
        if artifact_type == "terrain":
            # Create terrain entity at project location (Entity + Inventory aspect)
            artifact_entity = Entity()
            artifact_entity.data["name"] = artifact_template.get("name", "Collaborative Structure")
            artifact_entity.data["location"] = project_entity.location
            artifact_entity.data["aspects"] = ["Inventory"]
            artifact_entity.data["primary_aspect"] = "Inventory"
            artifact_entity._save()
            artifact_inv = Inventory()
            artifact_inv.data = {"uuid": artifact_entity.uuid, "is_terrain": True,
                "terrain_type": artifact_template.get("terrain_type", "structure"),
                "description": artifact_template.get("description", "A collaboratively-built structure."),
                "tags": artifact_template.get("tags", ["structure", "collaborative"])}
            if artifact_template.get("effects"):
                artifact_inv.data["effects"] = artifact_template["effects"]
            artifact_inv._save()
            artifact_uuid = artifact_entity.uuid
            artifact_name = artifact_template.get("name", "structure")
        elif artifact_type == "item":
            # Create item via Inventory.create_item at project location
            inv = Inventory()
            inv.entity = Entity(uuid=project_entity.location)
            result = inv.create_item(name=artifact_template.get("name", "Project Artifact"),
                description=artifact_template.get("description", "An artifact of collaborative effort."),
                tags=artifact_template.get("tags", ["artifact", "collaborative"]))
            artifact_uuid = result.get("item_uuid")
            artifact_name = artifact_template.get("name", "artifact")

    # Destroy contributed items that are still on the project entity
    for item_uuid in project_entity.contents:
        try:
            item = Entity(uuid=item_uuid)
            item.destroy()
        except KeyError:
            continue

    # Move project from active to completed for all participants
    completion_message = project.data.get("artifact_template", {}).get("completion_message",
        f"The project '{project.data.get('project_name', '')}' is complete!")

    for p_uuid in project.data.get("participants", []):
        try:
            p_entity = Entity(uuid=p_uuid)
            try:
                p_projects = p_entity.aspect("Projects")
                active = p_projects.data.get("active_projects", [])
                if project_entity.uuid in active:
                    active.remove(project_entity.uuid)
                p_projects.data["active_projects"] = active
                p_projects.data.setdefault("completed_projects", []).append(project_entity.uuid)
                p_projects._save()
            except (ValueError, KeyError):
                pass
            p_entity.push_event({
                "type": "project_complete",
                "project_uuid": project_entity.uuid,
                "project_name": project.data.get("project_name", ""),
                "artifact_uuid": artifact_uuid,
                "artifact_name": artifact_name,
                "message": completion_message,
            })
        except KeyError:
            continue

    return {
        "type": "project_complete",
        "artifact_uuid": artifact_uuid,
        "artifact_name": artifact_name,
        "message": completion_message,
    }
```

### `_notify_participants`

```python
def _notify_participants(self, project, event: dict, exclude_uuid: str = "") -> None:
    """Send a push_event to all project participants."""
```

Iterates the participant list and sends the event to each connected participant. Loads each participant entity (1 read each).

```python
def _notify_participants(self, project, event: dict, exclude_uuid: str = "") -> None:
    """Send a push_event to all project participants."""
    for p_uuid in project.data.get("participants", []):
        if p_uuid == exclude_uuid:
            continue
        try:
            p_entity = Entity(uuid=p_uuid)
            p_entity.push_event(event)
        except KeyError:
            continue
```

### `on_entity_depart` (callable)

```python
@callable
def on_entity_depart(self, entity_uuid: str, location_uuid: str) -> dict:
    """Handle a participant leaving the project's location during an all_present phase."""
```

If the current phase requires all participants to be present and a participant leaves, this sends a warning to other participants. This is a callable method that could be triggered by the Land aspect's departure broadcast, but since it requires Cross-aspect coupling (Land calling Projects), the initial implementation relies on the `all_present` check happening at contribution time rather than on departure.

## Events

Events pushed to players via WebSocket:

| Event Type | When | Fields |
|------------|------|--------|
| `project_proposed` | New project proposed at location | project_uuid, project_name, proposer, proposer_uuid, description, template, participants_needed, message |
| `project_participant_joined` | Someone joins a project | project_uuid, project_name, new_participant, new_participant_uuid, total_participants, message |
| `project_participant_left` | Someone leaves a project | project_uuid, project_name, participant, participant_uuid, remaining, message |
| `project_contribution` | Someone contributes | project_uuid, project_name, contributor, contributor_uuid, contribution, quantity, phase, message |
| `project_phase_complete` | Phase requirements met | project_uuid, project_name, completed_phase, next_phase, next_phase_requirements, message |
| `project_complete` | All phases done | project_uuid, project_name, artifact_uuid, artifact_name, message |
| `project_abandoned` | Proposer abandons project | project_uuid, project_name, message |

## Integration Points

### Projects + Inventory (material consumption)

Materials are contributed by physically moving item entities to the project entity. The project entity effectively has an inventory (entities whose location = project UUID appear in project.contents). On project completion, these items are destroyed. On project abandonment, items are returned to contributors.

```python
# During contribute:
item_entity.location = project_entity.uuid  # Move item to project

# During abandon:
item_entity.location = contributor_uuid  # Return item to contributor

# During completion:
item.destroy()  # Consume contributed materials
```

### Projects + Land (location binding)

Projects are created at a location. The project entity's location field is set to the room UUID. The project appears in `look` results as an entity at the location. Completed project artifacts are terrain entities placed at the same location.

### Projects + Building (complementary, not overlapping)

Building (08) creates single-player structures with interior rooms and exits. Projects create collaborative artifacts (terrain entities, special items) without interior rooms. A bridge project does not create a room with exits -- it creates a terrain entity that exists at the location. Future integration: a completed Projects bridge could unlock a new exit in the Land aspect, but this requires the cross-aspect write pattern flagged in both designs.

### Projects + Communication (discovery)

Project proposals broadcast to the room via `broadcast_to_location`. Agents at the location receive `project_proposed` events. The Communication aspect's `say` command could be used by agents to announce projects in adjacent rooms manually.

### Projects + Quest (potential future integration)

Quests could include "contribute to a project" objectives. The Quest aspect would listen for `project_contribution` events and check against quest objectives. This is a natural extension but adds the same cross-aspect coupling that Quest already has with other systems.

### Projects + Faction (potential future integration)

Projects at faction-controlled locations could require faction standing to join. Completed projects could grant faction reputation to all participants. The Faction aspect's `_adjust_reputation` method could be called from `_complete_project`.

### Projects + Trading (material gathering motivation)

Projects create demand for specific materials, driving agents to trade. An agent who needs 15 wood for a bridge project but only has 5 might buy 10 wood from a merchant or trade with another player. This is emergent economic activity driven by project requirements.

## Error Handling

| Error Condition | Error Message | Resolution |
|-----------------|---------------|------------|
| Project not found | "That project doesn't exist." | Provide valid project UUID |
| Not at project location | "That project isn't at this location." | Move to the project's location |
| Already a participant | "You're already part of this project." | No action needed |
| Project full | "This project has reached its participant limit." | Join a different project |
| Too many active projects | "You already have 3 active projects." | Leave or complete a project |
| Project not active | "Project is {status}. Must be active to contribute." | Wait for enough participants or find an active project |
| Not a participant | "You're not part of this project. Use 'project join' first." | Join the project first |
| Material not needed | "Phase '{name}' doesn't need '{material_type}'." | Check project status for current requirements |
| Insufficient materials | "You only have N '{type}' but tried to contribute M." | Gather more materials |
| Phase fully supplied | "Phase already has enough '{material_type}'." | Contribute to something else or wait for next phase |
| Action not required | "Phase doesn't require action '{action}'." | Check project status for required actions |
| Not enough present | "Action requires N participants present. Only M are here." | Wait for participants to arrive |
| Not the proposer | "Only the project proposer can abandon it." | Ask the proposer or use 'project leave' |
| Concurrent write conflict | (Silent data loss) | Architecture limitation -- see Critical Analysis |

## Cost Analysis

### Per-Operation DynamoDB Costs

| Operation | Reads | Writes | Notes |
|-----------|-------|--------|-------|
| project propose | 2 | 4 | Entity + aspect creation + proposer aspect read/write |
| project join | 3 + P | 2 | Project load + P participant notifications |
| project contribute (material) | 2 + N + P | Q + 2 | N = inventory scan, Q = items moved, P = notifications |
| project contribute (action) | 2 + K + P | 2 | K = presence check (if all_present), P = notifications |
| project status | 2 + P | 0 | Read-only, P = participant name loads |
| project list | 1 + 2M | 0 | M = entities at location, check aspects |
| project leave | 2 + P | R + 2 + P | R = items returned, P = notifications + participant cleanup |
| project abandon | 2 + P | I + 1 + P | I = items returned, P = participant cleanup |
| project complete | P + C | A + 2P + C | A = artifact creation (2-4), C = items to destroy, P = participant updates |

### Monthly Projections

**Scenario: 20 active agents, each participating in 1 project per day, average 5 participants per project, 3 phases per project, 10 contributions total per project.**

Per project lifecycle:
- Propose: 4 writes, 2 reads
- 4 joins: 4 * (3 + 5) reads + 4 * 2 writes = 32 reads, 8 writes
- 10 contributions (averaging 5 items each): 10 * (2 + 20 + 5) reads + 10 * (5 + 2) writes = 270 reads, 70 writes
- 3 phase completions (notifications): 3 * 5 reads = 15 reads
- 1 completion: 5 + 5 reads + 4 + 10 + 5 writes = 10 reads, 19 writes
- Total per project: ~329 reads, ~101 writes

Projects per day: 20 agents / 5 per project = 4 projects per day.
Daily: 4 * 329 = 1,316 reads, 4 * 101 = 404 writes.
Monthly: 39,480 reads, 12,120 writes.

At 1 WCU / 1 RCU provisioned: 12,120 writes / 30 days / 86,400 seconds = 0.005 WCU average (negligible). But burst during active contribution windows (5 agents contributing within 1 minute = 70 writes per minute = 1.17 WCU) will cause throttling.

**Step Functions cost:** Zero recurring cost. Projects do not use ticks. Optional decay timers (if implemented) would add $0.000025 per abandoned project check. With 50 abandoned projects checked daily: $0.00125/day = $0.0375/month.

## Future Considerations

1. **Global project board.** A `project search` command that queries all active projects across locations, using a DynamoDB GSI on project status. This would solve the discovery problem but add a new GSI to the location table.

2. **Project voting.** Allow participants to vote on freeform project decisions: which artifact to create, whether to change direction mid-project. Adds a voting sub-system with consensus thresholds.

3. **Recurring projects.** Some projects could be repeatable (weekly community build, seasonal event). Add a `repeatable` flag and cooldown timer to templates.

4. **Project reputation integration.** Track contribution history per agent and grant reputation points for completed projects. A "reliable contributor" title for agents who complete 10+ projects. This connects directly to Document 19 (Social Graph).

5. **Cross-location projects.** Projects that span multiple locations (a road connecting two settlements, a trade route). Each location holds a sub-project entity, and completion requires all sub-projects to finish. This dramatically increases complexity but enables world-scale collaboration.

6. **NPC project participation.** NPC entities could join projects as participants, contributing materials from their inventories on their tick cycle. This creates NPC-agent collaboration and makes projects viable even with few active players.

7. **Conditional write for contribution safety.** Replace `put_item` with DynamoDB `UpdateItem` using `list_append` for the contributions list and `ADD` for numeric progress counters. This would make concurrent contributions safe. The cost is breaking the codebase's uniform `put_item` pattern.

8. **Project templates from DynamoDB.** Move PROJECT_TEMPLATES to a DynamoDB table, allowing admins to add new project types at runtime without code deployment. This follows the same trajectory recommended for quest, crafting, and building registries.

9. **Material substitution.** Allow alternative materials for the same requirement (e.g., stone OR brick for a wall foundation). Increases project flexibility and creates more trading opportunities.

10. **Skill-gated contributions.** Certain phase contributions could require specific skills or endorsements (from Document 19). A bridge construction phase might require a participant endorsed as a "builder." This creates inter-system synergy between Projects and Social Graph.
