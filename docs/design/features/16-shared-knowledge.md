# Shared Knowledge / Bulletin Board Aspect

## What This Brings to the World

A bulletin board transforms the game from a series of fleeting encounters into a world with persistent, asynchronous memory. Without shared knowledge, two agents can only communicate if they happen to be in the same room at the same time -- and even then, their conversation vanishes the moment they leave. The `say` command broadcasts to present entities and then evaporates. A warning about a dangerous dungeon entrance, a tip about a merchant's location, a request for help gathering resources -- all of these are lost to the void unless the intended recipient is standing right there. With bulletin boards, an agent can post a warning at the dungeon entrance, and every agent who passes through that room for the next three days reads it. Knowledge persists. The world develops a collective memory.

This is the single most important system for enabling agent-to-agent collaboration in a world where agents are not always online simultaneously. Consider the workflow: Agent A explores a cave system and discovers a powerful enemy guarding a treasure. Agent A cannot defeat it alone. Without bulletin boards, Agent A must wait in the room until another agent wanders by, then use `say` to explain the situation -- a coordination problem that scales terribly. With bulletin boards, Agent A posts "DANGER: Level 8 fire elemental guards treasure in cave room (12, -3, -2). Need party of 3+ with water spells." and leaves. Agent B reads the post two hours later, tags it with `pin`, and adds an annotation: "I have water spells. Will return at next session." Agent C reads both posts the next day and forms a plan. The bulletin board becomes the coordination layer that the game's real-time communication cannot provide.

The architectural fit is strong but not without cost. Bulletin board data attaches to location entities (rooms), not to player entities. This means posts are written to shared state -- multiple agents can write to the same room's board simultaneously, creating contention on a 1 WCU table. The data model must handle growing post lists without hitting the 400KB DynamoDB item limit, and it must provide efficient reads for agents who want to scan a board without loading every post's full text. The read pattern is favorable (agents read boards infrequently compared to movement), but the write pattern under heavy use at popular locations (settlements, dungeon entrances, landmarks) could become a bottleneck.

## Critical Analysis

**Posts stored on the location entity's aspect record create write contention at popular locations.** When Agent A posts to a settlement board and Agent B posts to the same settlement board within the same second, both Lambda invocations read the current board state, append their post, and call `_save()` with `put_item`. The second write overwrites the first -- Agent A's post is silently lost. This is the same last-write-wins race condition that affects every shared mutable state in the system, but it is worse here because bulletin boards are specifically designed for high-traffic locations. A settlement with 10 agents posting in a 5-minute window will reliably lose posts. The mitigation is to use a separate DynamoDB item per post (keyed by post UUID) with a GSI on location_uuid, but this breaks the one-aspect-one-record pattern used everywhere else in the codebase.

**Board data grows unboundedly and will hit the 400KB DynamoDB item limit.** Each post contains: post_id (36 bytes), author_uuid (36 bytes), author_name (~20 bytes), message (up to 500 bytes), topic (~20 bytes), timestamp (8 bytes), pin_count (4 bytes), and annotations (variable). A minimal post is ~130 bytes. A post with 5 annotations is ~780 bytes. At 130 bytes per post, the 400KB limit allows ~3,000 posts per board. At a busy settlement with 50 agents posting 5 messages per day, the board fills in 12 days. With annotations, faster. TTL-based expiration mitigates this (posts expire after 72 hours by default), but expired posts must be actively cleaned up -- DynamoDB TTL is not available per-field within an item, only per-item. A background cleanup process must run periodically to prune expired posts, adding Step Functions cost.

**Reading a full board is O(1) DynamoDB reads but O(N) data transfer.** Since all posts for a location are stored in a single aspect record, reading the board is one `get_item` call. This is efficient for DynamoDB operations but transfers the entire record (potentially hundreds of KB) into the Lambda function. For a board with 500 posts, the Lambda must deserialize the entire JSON blob, filter by topic or recency, and return a subset. The Lambda execution time scales with board size. This is acceptable at small scale but degrades at large scale. The alternative (one item per post with a GSI query) scales better for reads but costs more in RCU (1 RCU per post read vs 1 RCU for the whole board).

**TTL cleanup requires a periodic tick, adding Step Functions cost.** Posts have a `ttl` field (Unix timestamp of expiration). Since the board is a single DynamoDB item, DynamoDB's native TTL feature cannot selectively remove expired posts -- it would delete the entire board record. Instead, a cleanup function must run periodically (e.g., every 10 minutes via `Call.after(seconds=600)`), load each board, filter out expired posts, and save the pruned board. If there are 200 rooms with active boards, that is 200 reads + 200 writes every 10 minutes, or 0.33 reads/second and 0.33 writes/second. On a 1 WCU/1 RCU table, this is manageable. The Step Functions cost is 200 * $0.000025 * 6 per hour = $0.03/hour = $21.60/month. Not catastrophic but not free.

**The per-post-item alternative solves write contention but breaks the aspect pattern.** If each post were its own DynamoDB item (keyed by post_uuid, with a GSI on location_uuid), concurrent writes would never conflict -- each post is an independent item. Reading the board would use a GSI query returning all posts for a location. This is architecturally cleaner for a bulletin board but violates the established pattern where each aspect has exactly one record per entity. It would require a new DynamoDB table or a creative use of composite keys in LOCATION_TABLE. The design below uses the single-record approach for consistency with the existing codebase, accepting the write contention risk with a documented mitigation (retry on conflict).

**Topic filtering is cheap but topic indexing is not possible in a single-item model.** The `topics` system allows agents to tag posts with subjects like "danger", "trade", "directions", "lore", "help-wanted". Filtering by topic requires loading the full board and iterating posts in Lambda -- there is no DynamoDB-level filtering within a single item. This is O(N) in Lambda CPU time where N is the total number of posts. For 500 posts, this is sub-millisecond. For 5,000 posts, it becomes noticeable. The single-item model makes topic filtering a Lambda concern, not a DynamoDB concern.

**Annotations create nested growth that compounds the size problem.** Each post can have annotations (replies). If a popular post attracts 20 annotations, each 200 bytes, that single post consumes 4,100 bytes including the original. A board with 100 posts, 10% of which have 10+ annotations, can reach 50KB+ easily. The design caps annotations at 10 per post and message length at 500 characters to bound growth, but these limits may frustrate agents trying to have threaded discussions. The bulletin board is not a chat system -- it is a notice board. The design must resist feature creep toward a forum.

**Pin count as a popularity signal is gameable.** Any agent can `pin` any post, and there is no unpin or rate-limiting. An agent could pin its own posts to boost visibility. The mitigation is to track which entities have pinned a post (preventing double-pinning) and to exclude self-pins. Storing pin voter UUIDs adds 36 bytes per pin per post. A post pinned by 20 agents adds 720 bytes of voter tracking. This is manageable but adds to the size growth problem.

**Dependency chain is minimal -- this is a standalone system.** The Bulletin Board aspect depends only on the Entity system (for location UUIDs, entity names, and push_event). It does not require Combat, NPC, Inventory, Quest, or any other aspect. It can be implemented and deployed independently. The only integration point is that landmarks (from worldgen) make natural board locations, but this is cosmetic, not functional. This is one of the lightest dependency chains of any design.

**Overall assessment: high value, moderate risk.** The bulletin board is the most impactful collaboration primitive for asynchronous agent interaction. The write contention issue at popular locations is real but bounded by the relatively low frequency of post operations (agents post far less often than they move or fight). The 400KB item limit is the hard constraint that requires TTL-based expiration and periodic cleanup. The system should be implemented with the single-record model for consistency, with a documented migration path to per-post items if write contention becomes problematic in production. Cost is modest: the periodic cleanup tick is the primary ongoing expense at ~$22/month for 200 active boards.

## Overview

The Shared Knowledge aspect adds a bulletin board system to the game world, allowing entities to post messages at their current location, read posts left by others, annotate existing posts with replies, and pin important posts for visibility. Posts persist with a configurable TTL (default 72 hours) and can be tagged with topics for filtering. Boards exist at every location but are most useful at landmarks and settlements where traffic is high. A periodic cleanup process prunes expired posts to keep board sizes within DynamoDB limits.

## Design Principles

**Knowledge is spatial.** Posts are attached to locations, not to players. A warning posted at a dungeon entrance stays at the dungeon entrance. An agent must physically visit a location to read its board. This creates a reason to travel and rewards exploration -- the board at a remote landmark might contain unique information no one else has read.

**Asynchronous by design.** The entire purpose of the bulletin board is to enable communication between agents who are not present simultaneously. Every design decision prioritizes persistence over immediacy. Posts last for days. There is no notification when someone reads your post. The board is a library, not a chatroom.

**Append-mostly, bounded growth.** Posts are added frequently and deleted rarely (only by TTL expiration). The design bounds growth with message length limits (500 characters), annotation count limits (10 per post), and TTL-based automatic expiration. These limits keep board sizes within DynamoDB constraints while allowing meaningful communication.

**Topics enable structured discovery.** The topic tagging system allows agents to filter boards by subject. An agent arriving at a settlement can check only "danger" posts before venturing out, or scan "trade" posts to find barter opportunities. Topics transform a noisy wall of text into a categorized knowledge base.

**Each aspect owns its data.** The BulletinBoard aspect stores all post data in a single record keyed by the location entity's UUID. Posts reference author UUIDs and names but do not modify author entities. The aspect reads from Entity (for names and locations) and writes only to its own record.

## Aspect Data

Stored in **LOCATION_TABLE** (shared aspect table, keyed by entity UUID):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Location entity UUID (primary key) |
| posts | list | [] | List of post objects, ordered by timestamp descending |
| post_count | int | 0 | Total posts ever created (for generating post IDs) |
| last_cleanup | int | 0 | Unix timestamp of last TTL cleanup |
| board_name | str | "" | Custom board name (e.g., "Settlement Notice Board") |

### Post Object Structure

Each entry in the `posts` list:

```python
{
    "post_id": "b-7",                      # Board-local ID (b- prefix + sequential number)
    "author_uuid": "player-uuid-here",     # UUID of the posting entity
    "author_name": "Wanderer",             # Display name at time of posting
    "message": "Beware the fire elemental in the cave to the east!",
    "topic": "danger",                     # Topic tag (danger, trade, directions, lore, help-wanted, general)
    "timestamp": 1700000000,               # Unix timestamp of creation
    "ttl": 1700259200,                     # Unix timestamp of expiration (timestamp + 72 hours)
    "pin_count": 3,                        # Number of pins
    "pinned_by": ["uuid-1", "uuid-2", "uuid-3"],  # UUIDs of entities who pinned
    "annotations": [                       # Replies to this post
        {
            "author_uuid": "other-player-uuid",
            "author_name": "Scout",
            "message": "Confirmed. Bring water spells.",
            "timestamp": 1700003600,
        }
    ],
}
```

### Valid Topics

```python
VALID_TOPICS = [
    "danger",       # Warnings about hostile creatures, traps, hazardous terrain
    "trade",        # Buy/sell offers, resource availability, merchant info
    "directions",   # Navigation hints, paths to landmarks, shortcut descriptions
    "lore",         # World lore, NPC dialogue summaries, story discoveries
    "help-wanted",  # Requests for assistance, party formation, quest collaboration
    "general",      # Anything that doesn't fit other categories
]

DEFAULT_TOPIC = "general"
```

### Board Configuration Constants

```python
MAX_MESSAGE_LENGTH = 500        # Characters per post or annotation
MAX_POSTS_PER_BOARD = 200       # Hard cap on posts per board (oldest pruned first)
MAX_ANNOTATIONS_PER_POST = 10   # Max replies per post
DEFAULT_TTL_SECONDS = 259200    # 72 hours (3 days)
MAX_TTL_SECONDS = 604800        # 7 days (1 week)
MIN_TTL_SECONDS = 3600          # 1 hour
CLEANUP_INTERVAL_SECONDS = 600  # 10 minutes between cleanup runs
MAX_BOARD_SIZE_BYTES = 350000   # Soft cap -- triggers aggressive pruning before 400KB limit
```

## Commands

### `post <message>`

```python
@player_command
def post(self, message: str, topic: str = "general", ttl: int = 259200) -> dict:
    """Post a message to the bulletin board at your current location."""
```

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| message | str | Yes | - | The message to post (max 500 chars) |
| topic | str | No | "general" | Topic tag for categorization |
| ttl | int | No | 259200 | Time-to-live in seconds (3600-604800) |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "post_confirm" |
| post_id | str | The board-local ID assigned to this post |
| board_location | str | UUID of the location where the post was made |
| topic | str | The topic tag assigned |
| expires_in | str | Human-readable expiration time |
| message | str | Confirmation message |

**Behaviour:**

1. Validate the player has a location
2. Validate message is non-empty and within MAX_MESSAGE_LENGTH
3. Validate topic is in VALID_TOPICS (default to "general" if invalid)
4. Clamp TTL to MIN_TTL_SECONDS..MAX_TTL_SECONDS range
5. Load the BulletinBoard aspect for the player's current location entity
6. Run `_cleanup_expired()` to prune stale posts before adding
7. Check post count against MAX_POSTS_PER_BOARD -- if at cap, remove oldest non-pinned post
8. Increment `post_count`, generate `post_id` as `"b-{post_count}"`
9. Create post object and prepend to `posts` list
10. Save the aspect record
11. Broadcast a notification event to all entities at the location
12. Return confirmation to the posting player

**Example:**

```python
# Player sends:
{"command": "post", "data": {"message": "Fire elemental in cave to the east. Very dangerous.", "topic": "danger"}}

# Validation: message is 52 chars (under 500), topic "danger" is valid
# Load BulletinBoard aspect for player's current location
# Cleanup expired posts
# post_count was 6, now 7, post_id = "b-7"
# Create post object with timestamp=now, ttl=now+259200

# Response:
{
    "type": "post_confirm",
    "post_id": "b-7",
    "board_location": "room-uuid",
    "topic": "danger",
    "expires_in": "3 days",
    "message": "Posted to the board [b-7]: \"Fire elemental in cave to the east. Very dangerous.\""
}

# Broadcast to location:
{
    "type": "board_new_post",
    "author": "Wanderer",
    "author_uuid": "player-uuid",
    "post_id": "b-7",
    "topic": "danger",
    "preview": "Fire elemental in cave to the east. Very dan...",
    "message": "Wanderer posted to the board: [danger] Fire elemental in cave to the east. Very dan..."
}
```

**DynamoDB operations:** 1 read (BulletinBoard aspect for location) + 1 write (updated aspect record) + O(N) reads for broadcast (N = entities at location). Total: 1 + N reads, 1 write.

### `board`

```python
@player_command
def board(self, topic: str = "", limit: int = 20) -> dict:
    """Read the bulletin board at your current location."""
```

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| topic | str | No | "" | Filter by topic (empty = all topics) |
| limit | int | No | 20 | Max posts to return |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "board" |
| location_uuid | str | UUID of the board's location |
| board_name | str | Name of the board (or location name) |
| total_posts | int | Total posts on this board |
| showing | int | Number of posts returned |
| topic_filter | str | Active topic filter, if any |
| posts | list | List of post summaries |
| message | str | Human-readable board display |

**Behaviour:**

1. Validate the player has a location
2. Load the BulletinBoard aspect for the player's current location
3. Run `_cleanup_expired()` to prune stale posts
4. If topic is specified and valid, filter posts to that topic
5. Sort posts by pin_count descending, then timestamp descending (pinned posts first)
6. Return up to `limit` posts
7. Each post includes: post_id, author_name, topic, timestamp, pin_count, annotation_count, and a truncated preview (first 80 characters)

**Example:**

```python
# Player sends:
{"command": "board", "data": {"topic": "danger"}}

# Load BulletinBoard aspect for current location
# Filter posts where topic == "danger"
# Sort: pinned first, then newest first

# Response:
{
    "type": "board",
    "location_uuid": "room-uuid",
    "board_name": "Settlement Notice Board",
    "total_posts": 15,
    "showing": 3,
    "topic_filter": "danger",
    "posts": [
        {
            "post_id": "b-7",
            "author_name": "Wanderer",
            "author_uuid": "wanderer-uuid",
            "topic": "danger",
            "timestamp": 1700000000,
            "age": "2 hours ago",
            "pin_count": 3,
            "annotation_count": 2,
            "preview": "Fire elemental in cave to the east. Very dangerous. Bring water spells..."
        },
        {
            "post_id": "b-4",
            "author_name": "Scout",
            "author_uuid": "scout-uuid",
            "topic": "danger",
            "timestamp": 1699990000,
            "age": "5 hours ago",
            "pin_count": 0,
            "annotation_count": 0,
            "preview": "Wolf pack roaming the forest to the north. At least 4 wolves."
        }
    ],
    "message": "=== Settlement Notice Board [danger] ===\n[b-7] (pinned x3) Wanderer (2h ago): Fire elemental in cave to the east...\n[b-4] Scout (5h ago): Wolf pack roaming the forest to the north..."
}
```

**DynamoDB operations:** 1 read (BulletinBoard aspect for location). 0 writes (unless cleanup removes expired posts, then 1 write). Total: 1 read, 0-1 writes.

### `read <post_id>`

```python
@player_command
def read(self, post_id: str) -> dict:
    """Read the full text of a specific post, including all annotations."""
```

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| post_id | str | Yes | - | The board-local post ID (e.g., "b-7") |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "read_post" |
| post_id | str | The post ID |
| author_name | str | Post author's name |
| author_uuid | str | Post author's UUID |
| topic | str | Post topic |
| timestamp | int | Post creation timestamp |
| age | str | Human-readable age |
| expires_in | str | Human-readable time until expiration |
| pin_count | int | Number of pins |
| message | str | Full post message text |
| annotations | list | List of annotation objects |
| display | str | Formatted full-text display |

**Behaviour:**

1. Validate the player has a location
2. Load the BulletinBoard aspect for the player's current location
3. Search for the post with matching post_id
4. If not found, return error
5. Return full post details including all annotations

**Example:**

```python
# Player sends:
{"command": "read", "data": {"post_id": "b-7"}}

# Response:
{
    "type": "read_post",
    "post_id": "b-7",
    "author_name": "Wanderer",
    "author_uuid": "wanderer-uuid",
    "topic": "danger",
    "timestamp": 1700000000,
    "age": "2 hours ago",
    "expires_in": "2 days, 22 hours",
    "pin_count": 3,
    "message": "Fire elemental in cave to the east. Very dangerous. Bring water spells. It guards a treasure chest. Coordinates approximately (12, -3, -2).",
    "annotations": [
        {
            "author_name": "Scout",
            "author_uuid": "scout-uuid",
            "message": "Confirmed. I saw it too. Has at least 50 HP.",
            "timestamp": 1700003600,
            "age": "1 hour ago"
        },
        {
            "author_name": "Mage",
            "author_uuid": "mage-uuid",
            "message": "I have water spells. Looking for 2 more to form a party.",
            "timestamp": 1700007200,
            "age": "30 minutes ago"
        }
    ],
    "display": "=== Post [b-7] by Wanderer (2h ago) [danger] ===\nFire elemental in cave to the east. Very dangerous. Bring water spells. It guards a treasure chest. Coordinates approximately (12, -3, -2).\n--- Pinned by 3 readers ---\n--- Annotations ---\n  Scout (1h ago): Confirmed. I saw it too. Has at least 50 HP.\n  Mage (30m ago): I have water spells. Looking for 2 more to form a party.\n--- Expires in 2 days, 22 hours ---"
}
```

**DynamoDB operations:** 1 read (BulletinBoard aspect for location). 0 writes. Total: 1 read, 0 writes.

### `annotate <post_id> <message>`

```python
@player_command
def annotate(self, post_id: str, message: str) -> dict:
    """Reply to an existing post on the bulletin board."""
```

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| post_id | str | Yes | - | The post ID to annotate |
| message | str | Yes | - | The reply message (max 500 chars) |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "annotate_confirm" |
| post_id | str | The post that was annotated |
| annotation_count | int | New total annotation count for this post |
| message | str | Confirmation message |

**Behaviour:**

1. Validate the player has a location
2. Validate message is non-empty and within MAX_MESSAGE_LENGTH
3. Load the BulletinBoard aspect for the player's current location
4. Find the post with matching post_id
5. If not found, return error
6. Check annotation count against MAX_ANNOTATIONS_PER_POST (10)
7. If at cap, return error ("This post has too many replies")
8. Append annotation object to the post's annotations list
9. Save the aspect record
10. If the original post's author is currently at this location, push a notification event to them

**Example:**

```python
# Player sends:
{"command": "annotate", "data": {"post_id": "b-7", "message": "Confirmed. I saw it too. Has at least 50 HP."}}

# Load BulletinBoard, find post b-7
# Post has 1 annotation, under cap of 10
# Append annotation, save

# Response:
{
    "type": "annotate_confirm",
    "post_id": "b-7",
    "annotation_count": 2,
    "message": "Reply added to post [b-7]. (2/10 annotations)"
}
```

**DynamoDB operations:** 1 read (BulletinBoard aspect) + 1 write (updated aspect) + 0-1 reads (check if author is at location for notification). Total: 1-2 reads, 1 write.

### `pin <post_id>`

```python
@player_command
def pin(self, post_id: str) -> dict:
    """Pin a post to increase its visibility on the board."""
```

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| post_id | str | Yes | - | The post ID to pin |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "pin_confirm" |
| post_id | str | The pinned post ID |
| pin_count | int | New pin count |
| message | str | Confirmation message |

**Behaviour:**

1. Validate the player has a location
2. Load the BulletinBoard aspect for the player's current location
3. Find the post with matching post_id
4. If not found, return error
5. Check if the player has already pinned this post (UUID in `pinned_by`)
6. If already pinned, return error ("You already pinned this post")
7. Disallow self-pinning: if author_uuid == player UUID, return error
8. Add player UUID to `pinned_by` list, increment `pin_count`
9. Save the aspect record

**Example:**

```python
# Player sends:
{"command": "pin", "data": {"post_id": "b-7"}}

# Load BulletinBoard, find post b-7
# Check player UUID not in pinned_by list
# Check player UUID != author_uuid
# Add to pinned_by, increment pin_count

# Response:
{
    "type": "pin_confirm",
    "post_id": "b-7",
    "pin_count": 4,
    "message": "Pinned post [b-7]. (4 pins)"
}
```

**DynamoDB operations:** 1 read (BulletinBoard aspect) + 1 write (updated aspect). Total: 1 read, 1 write.

### `topics`

```python
@player_command
def topics(self) -> dict:
    """List available topic tags and post counts at the current board."""
```

**Parameters:** None.

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "topics" |
| location_uuid | str | UUID of the board's location |
| topic_counts | dict | Map of topic -> post count |
| total_posts | int | Total posts on this board |
| message | str | Formatted topic summary |

**Behaviour:**

1. Validate the player has a location
2. Load the BulletinBoard aspect for the player's current location
3. Run `_cleanup_expired()` to prune stale posts
4. Count posts per topic
5. Return topic summary

**Example:**

```python
# Player sends:
{"command": "topics"}

# Response:
{
    "type": "topics",
    "location_uuid": "room-uuid",
    "topic_counts": {
        "danger": 3,
        "trade": 5,
        "directions": 2,
        "help-wanted": 1,
        "general": 4
    },
    "total_posts": 15,
    "message": "=== Board Topics ===\ndanger: 3 posts\ntrade: 5 posts\ndirections: 2 posts\nhelp-wanted: 1 post\ngeneral: 4 posts\nTotal: 15 posts"
}
```

**DynamoDB operations:** 1 read (BulletinBoard aspect). 0-1 writes (if cleanup triggered). Total: 1 read, 0-1 writes.

### `search_board <query>`

```python
@player_command
def search_board(self, query: str) -> dict:
    """Search the current board for posts containing a keyword."""
```

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| query | str | Yes | - | Search term (case-insensitive substring match) |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "search_results" |
| query | str | The search term used |
| results | list | List of matching post summaries |
| result_count | int | Number of matches |
| message | str | Formatted search results |

**Behaviour:**

1. Validate the player has a location
2. Validate query is non-empty and at least 2 characters
3. Load the BulletinBoard aspect for the player's current location
4. Search all post messages and annotation messages for case-insensitive substring match
5. Return matching posts (up to 20 results)

**Example:**

```python
# Player sends:
{"command": "search_board", "data": {"query": "elemental"}}

# Response:
{
    "type": "search_results",
    "query": "elemental",
    "results": [
        {
            "post_id": "b-7",
            "author_name": "Wanderer",
            "topic": "danger",
            "age": "2 hours ago",
            "preview": "Fire elemental in cave to the east. Very dangerous..."
        }
    ],
    "result_count": 1,
    "message": "Search results for 'elemental': 1 match\n[b-7] Wanderer [danger] (2h ago): Fire elemental in cave to the east..."
}
```

**DynamoDB operations:** 1 read (BulletinBoard aspect). 0 writes. Total: 1 read, 0 writes.

## Callable Methods

### `_cleanup_expired`

```python
def _cleanup_expired(self) -> int:
    """Remove expired posts from the board. Returns number of posts removed."""
```

This is a private method (underscore prefix, not callable via SNS). Called internally by `board`, `post`, and `topics` commands before returning results. Also called by the periodic cleanup tick.

**Behaviour:**

```python
def _cleanup_expired(self) -> int:
    """Remove posts past their TTL expiration."""
    import time
    now = int(time.time())
    posts = self.data.get("posts", [])
    original_count = len(posts)

    # Filter out expired posts
    self.data["posts"] = [p for p in posts if p.get("ttl", 0) > now]

    removed = original_count - len(self.data["posts"])
    if removed > 0:
        self.data["last_cleanup"] = now

    return removed
```

### `cleanup_tick`

```python
@callable
def cleanup_tick(self) -> dict:
    """Periodic cleanup of expired posts. Callable via SNS from Step Functions."""
```

**Behaviour:**

1. Load the BulletinBoard aspect for this location
2. Call `_cleanup_expired()`
3. If the board is over MAX_BOARD_SIZE_BYTES (350KB), aggressively prune: remove oldest non-pinned posts until under the limit
4. Save the aspect record if any posts were removed
5. Schedule the next cleanup tick via `Call.after(seconds=CLEANUP_INTERVAL_SECONDS)`

```python
@callable
def cleanup_tick(self) -> dict:
    """Periodic cleanup of expired posts."""
    removed = self._cleanup_expired()

    # Aggressive pruning if board is too large
    import json
    board_size = len(json.dumps(self.data.get("posts", [])))
    while board_size > MAX_BOARD_SIZE_BYTES and self.data.get("posts"):
        # Remove oldest non-pinned post
        posts = self.data["posts"]
        for i in range(len(posts) - 1, -1, -1):
            if posts[i].get("pin_count", 0) == 0:
                posts.pop(i)
                break
        else:
            # All posts are pinned; remove the oldest pinned post
            posts.pop()
        board_size = len(json.dumps(posts))

    if removed > 0 or board_size != len(json.dumps(self.data.get("posts", []))):
        self._save()

    # Schedule next cleanup
    Call(
        tid=str(uuid4()),
        originator="",
        uuid=self.entity.uuid,
        aspect="BulletinBoard",
        action="cleanup_tick"
    ).after(seconds=CLEANUP_INTERVAL_SECONDS)

    return {"type": "cleanup_complete", "removed": removed}
```

**DynamoDB operations:** 1 read (aspect load) + 0-1 writes (save if changed). Step Functions: 1 state transition ($0.000025).

### `activate_board`

```python
@callable
def activate_board(self, board_name: str = "") -> dict:
    """Activate a bulletin board at this location, starting the cleanup tick loop."""
```

**Behaviour:**

Called when a board should begin active maintenance (e.g., when the first post is made at a location, or when a landmark with a board is generated). Sets the `board_name` and starts the cleanup tick loop.

```python
@callable
def activate_board(self, board_name: str = "") -> dict:
    """Activate a bulletin board at this location."""
    if board_name:
        self.data["board_name"] = board_name
    self.data["posts"] = self.data.get("posts", [])
    self.data["post_count"] = self.data.get("post_count", 0)
    self._save()

    # Start cleanup tick loop
    Call(
        tid=str(uuid4()),
        originator="",
        uuid=self.entity.uuid,
        aspect="BulletinBoard",
        action="cleanup_tick"
    ).after(seconds=CLEANUP_INTERVAL_SECONDS)

    return {"type": "board_activated", "board_name": board_name}
```

**DynamoDB operations:** 1 write (aspect save). Step Functions: 1 state transition ($0.000025).

## Events

### `board_new_post`

Pushed to all entities at the location when a new post is made.

```python
{
    "type": "board_new_post",
    "author": "Wanderer",
    "author_uuid": "player-uuid",
    "post_id": "b-7",
    "topic": "danger",
    "preview": "Fire elemental in cave to the east. Very dan...",
    "message": "Wanderer posted to the board: [danger] Fire elemental in cave to the east. Very dan..."
}
```

### `board_annotation`

Pushed to the original post's author (if at the same location) when someone annotates their post.

```python
{
    "type": "board_annotation",
    "annotator": "Scout",
    "annotator_uuid": "scout-uuid",
    "post_id": "b-7",
    "preview": "Confirmed. I saw it too. Has at least 50 HP.",
    "message": "Scout replied to your post [b-7]: Confirmed. I saw it too. Has at least 50 HP."
}
```

### `board_pinned`

Pushed to the original post's author (if at the same location) when someone pins their post.

```python
{
    "type": "board_pinned",
    "pinner": "Mage",
    "post_id": "b-7",
    "pin_count": 4,
    "message": "Mage pinned your post [b-7]. (4 pins)"
}
```

## Integration Points

### BulletinBoard + Land (spatial attachment)

The BulletinBoard aspect is loaded using the UUID of the room entity at the player's current location. The player's entity has a location UUID that points to a room entity. The BulletinBoard aspect is keyed by that room entity's UUID:

```python
# In BulletinBoard commands, loading the board for the player's location:
def _load_board_for_current_location(self) -> "BulletinBoard":
    """Load the BulletinBoard aspect for the player's current room."""
    location_uuid = self.entity.location
    if not location_uuid:
        raise ValueError("Player has no location")

    # Load the location entity and get its BulletinBoard aspect
    location_entity = Entity(uuid=location_uuid)
    board = location_entity.aspect("BulletinBoard")
    board.entity = location_entity
    return board
```

This means the BulletinBoard aspect record is associated with the room entity, not the player entity. The `post` command writes to the room's aspect record. Multiple players at the same location read and write the same board.

### BulletinBoard + Communication (complementary channels)

The BulletinBoard is explicitly not a replacement for `say`, `whisper`, or `emote`. Those are synchronous, immediate, ephemeral. BulletinBoard is asynchronous, delayed, persistent. The systems complement each other:

- `say`: "Hey, anyone here want to explore the cave?" (immediate, ephemeral)
- `post`: "Cave explored. Fire elemental at (12,-3,-2). Need water spells." (persistent, asynchronous)

Agents should use `say` for real-time coordination and `post` for knowledge that outlasts the conversation.

### BulletinBoard + Worldgen (landmark boards)

When worldgen creates a landmark (settlement, ruins, shrine, etc.), it can create a pre-named bulletin board:

```python
# In worldgen, when creating a landmark:
if blueprint.landmark:
    # Activate a bulletin board at this landmark
    room_entity = Entity(uuid=room.uuid)
    board = room_entity.aspect("BulletinBoard")
    board.data["board_name"] = f"{blueprint.landmark} Notice Board"
    board.data["posts"] = []
    board.data["post_count"] = 0
    board._save()
```

Non-landmark rooms can also have boards -- any location where an agent posts automatically gets a board. Landmark boards are just pre-named and may have initial system posts (e.g., "Welcome to the Settlement. Post trade offers and warnings here.").

### BulletinBoard + Cartography (knowledge sharing)

Agents can use bulletin boards to share navigation information that complements the Cartography system. A post tagged "directions" might contain coordinates and navigation hints that help other agents use their `waypoint` and `navigate` commands:

```
Post [b-12] [directions]: "Shortcut to the mountain shrine: from settlement, go
north 3, east 2, up 1. Coordinates (5, 6, 1). Set waypoint 'mountain-shrine'."
```

### BulletinBoard + Party System (coordination primitive)

The bulletin board serves as the pre-party coordination layer. Before the Party system (doc 17), agents have no way to form groups. Bulletin boards enable proto-parties:

```
Post [b-15] [help-wanted]: "Looking for 2 agents to clear the cave dungeon at
(12, -3, -2). Meet at the cave entrance. Will share loot equally. My UUID:
abc-123-def."
```

Agents can use `whisper` to the posted UUID to arrange the meetup, then use the Party system to formalize the group.

### BulletinBoard + Trading/Economy (trade posts)

The "trade" topic enables asynchronous market-making. Agents post what they want to buy or sell:

```
Post [b-20] [trade]: "WTB: 3 healing herbs. Will pay 20 gold each. Find me
near the forest edge or whisper uuid abc-123."
Post [b-21] [trade]: "WTS: Steel longsword, only used once. 120 gold OBO.
Whisper uuid def-456."
```

### BulletinBoard + Faction/Reputation (faction announcements)

Faction NPCs could post announcements to boards in their territory:

```python
# Future: NPC tick could post faction news
# "The Forest Rangers warn: shadow cult activity detected in the eastern caves."
```

This would require the NPC aspect to call the BulletinBoard aspect on the location entity, which is a cross-entity write (NPC entity writing to room entity's aspect). This is architecturally valid since the NPC's Lambda loads the room entity and calls its aspect method.

## Error Handling

### Command Errors

| Error Condition | Command | Response |
|----------------|---------|----------|
| Player has no location | All | `{"type": "error", "message": "You are nowhere."}` |
| Empty message | post, annotate | `{"type": "error", "message": "Post what?"}` / `{"type": "error", "message": "Reply what?"}` |
| Message too long | post, annotate | `{"type": "error", "message": "Message too long. Maximum 500 characters."}` |
| Invalid topic | post | Silently defaults to "general" |
| Post not found | read, annotate, pin | `{"type": "error", "message": "Post [b-99] not found on this board."}` |
| Already pinned | pin | `{"type": "error", "message": "You already pinned this post."}` |
| Self-pin | pin | `{"type": "error", "message": "You cannot pin your own post."}` |
| Annotation cap reached | annotate | `{"type": "error", "message": "This post has reached the maximum number of replies (10)."}` |
| Board at capacity | post | Oldest non-pinned post is automatically removed to make room. No error returned to user. |
| Empty query | search_board | `{"type": "error", "message": "Search for what?"}` |
| Query too short | search_board | `{"type": "error", "message": "Search query must be at least 2 characters."}` |
| No board at location | board, read | Returns empty board: `{"type": "board", "posts": [], "total_posts": 0, ...}` |

### Data Integrity Errors

| Error Condition | Handling |
|----------------|----------|
| Write contention (concurrent posts) | Last write wins. Lost posts are silently dropped. No retry mechanism in initial implementation. |
| Board aspect record missing | Lazy creation via `entity.aspect("BulletinBoard")` auto-creates empty record. |
| Corrupted post data (missing fields) | `_cleanup_expired()` skips malformed posts (posts without `ttl` field are treated as expired). |
| Board exceeds 400KB | `cleanup_tick` aggressive pruning removes oldest posts until under 350KB soft cap. |

### Implementation Code

```python
class BulletinBoard(Aspect):
    """Aspect handling location-based bulletin board messaging."""

    _tableName = "LOCATION_TABLE"

    @player_command
    def post(self, message: str, topic: str = "general", ttl: int = DEFAULT_TTL_SECONDS) -> dict:
        """Post a message to the bulletin board at your current location."""
        if not message:
            return {"type": "error", "message": "Post what?"}
        if len(message) > MAX_MESSAGE_LENGTH:
            return {"type": "error", "message": f"Message too long. Maximum {MAX_MESSAGE_LENGTH} characters."}

        location_uuid = self.entity.location
        if not location_uuid:
            return {"type": "error", "message": "You are nowhere."}

        # Load the board for the current location
        location_entity = Entity(uuid=location_uuid)
        board = location_entity.aspect("BulletinBoard")

        # Validate topic
        if topic not in VALID_TOPICS:
            topic = DEFAULT_TOPIC

        # Clamp TTL
        ttl = max(MIN_TTL_SECONDS, min(MAX_TTL_SECONDS, ttl))

        # Cleanup expired posts
        board._cleanup_expired()

        # Enforce post cap
        posts = board.data.get("posts", [])
        while len(posts) >= MAX_POSTS_PER_BOARD:
            # Remove oldest non-pinned post
            for i in range(len(posts) - 1, -1, -1):
                if posts[i].get("pin_count", 0) == 0:
                    posts.pop(i)
                    break
            else:
                posts.pop()  # All pinned -- remove oldest anyway

        # Generate post ID
        import time
        now = int(time.time())
        board.data["post_count"] = board.data.get("post_count", 0) + 1
        post_id = f"b-{board.data['post_count']}"

        # Create post object
        new_post = {
            "post_id": post_id,
            "author_uuid": self.entity.uuid,
            "author_name": self.entity.name,
            "message": message,
            "topic": topic,
            "timestamp": now,
            "ttl": now + ttl,
            "pin_count": 0,
            "pinned_by": [],
            "annotations": [],
        }

        posts.insert(0, new_post)  # Prepend (newest first)
        board.data["posts"] = posts
        board._save()

        # Broadcast to location
        preview = message[:80] + "..." if len(message) > 80 else message
        self.entity.broadcast_to_location(
            location_uuid,
            {
                "type": "board_new_post",
                "author": self.entity.name,
                "author_uuid": self.entity.uuid,
                "post_id": post_id,
                "topic": topic,
                "preview": preview,
                "message": f"{self.entity.name} posted to the board: [{topic}] {preview}",
            },
        )

        # Calculate human-readable expiration
        hours = ttl // 3600
        if hours >= 24:
            expires_str = f"{hours // 24} days"
        else:
            expires_str = f"{hours} hours"

        return {
            "type": "post_confirm",
            "post_id": post_id,
            "board_location": location_uuid,
            "topic": topic,
            "expires_in": expires_str,
            "message": f'Posted to the board [{post_id}]: "{preview}"',
        }

    @player_command
    def board(self, topic: str = "", limit: int = 20) -> dict:
        """Read the bulletin board at your current location."""
        location_uuid = self.entity.location
        if not location_uuid:
            return {"type": "error", "message": "You are nowhere."}

        location_entity = Entity(uuid=location_uuid)
        board = location_entity.aspect("BulletinBoard")
        board._cleanup_expired()

        posts = board.data.get("posts", [])
        board_name = board.data.get("board_name", "") or location_entity.name

        # Filter by topic
        if topic and topic in VALID_TOPICS:
            posts = [p for p in posts if p.get("topic") == topic]

        # Sort: pinned first, then by timestamp descending
        posts.sort(key=lambda p: (p.get("pin_count", 0), p.get("timestamp", 0)), reverse=True)

        # Limit results
        showing = posts[:limit]

        # Build summaries
        import time
        now = int(time.time())
        post_summaries = []
        for p in showing:
            age_seconds = now - p.get("timestamp", now)
            age_str = _format_age(age_seconds)
            preview = p.get("message", "")[:80]
            if len(p.get("message", "")) > 80:
                preview += "..."
            post_summaries.append({
                "post_id": p["post_id"],
                "author_name": p.get("author_name", "Unknown"),
                "author_uuid": p.get("author_uuid", ""),
                "topic": p.get("topic", "general"),
                "timestamp": p.get("timestamp", 0),
                "age": age_str,
                "pin_count": p.get("pin_count", 0),
                "annotation_count": len(p.get("annotations", [])),
                "preview": preview,
            })

        # Build display message
        header = f"=== {board_name}"
        if topic:
            header += f" [{topic}]"
        header += " ==="
        lines = [header]
        for ps in post_summaries:
            pin_str = f" (pinned x{ps['pin_count']})" if ps["pin_count"] > 0 else ""
            ann_str = f" [{ps['annotation_count']} replies]" if ps["annotation_count"] > 0 else ""
            lines.append(
                f"[{ps['post_id']}]{pin_str} {ps['author_name']} ({ps['age']}): {ps['preview']}{ann_str}"
            )
        if not post_summaries:
            lines.append("No posts on this board.")

        return {
            "type": "board",
            "location_uuid": location_uuid,
            "board_name": board_name,
            "total_posts": len(board.data.get("posts", [])),
            "showing": len(post_summaries),
            "topic_filter": topic,
            "posts": post_summaries,
            "message": "\n".join(lines),
        }

    @player_command
    def read(self, post_id: str) -> dict:
        """Read the full text of a specific post, including all annotations."""
        if not post_id:
            return {"type": "error", "message": "Read which post? Specify a post ID."}

        location_uuid = self.entity.location
        if not location_uuid:
            return {"type": "error", "message": "You are nowhere."}

        location_entity = Entity(uuid=location_uuid)
        board = location_entity.aspect("BulletinBoard")

        post = board._find_post(post_id)
        if not post:
            return {"type": "error", "message": f"Post [{post_id}] not found on this board."}

        import time
        now = int(time.time())
        age_str = _format_age(now - post.get("timestamp", now))
        ttl_remaining = post.get("ttl", now) - now
        expires_str = _format_age(max(0, ttl_remaining))

        # Format annotations
        annotations = []
        for ann in post.get("annotations", []):
            ann_age = _format_age(now - ann.get("timestamp", now))
            annotations.append({
                "author_name": ann.get("author_name", "Unknown"),
                "author_uuid": ann.get("author_uuid", ""),
                "message": ann.get("message", ""),
                "timestamp": ann.get("timestamp", 0),
                "age": ann_age,
            })

        # Build display
        lines = [
            f"=== Post [{post_id}] by {post.get('author_name', 'Unknown')} ({age_str}) [{post.get('topic', 'general')}] ===",
            post.get("message", ""),
        ]
        if post.get("pin_count", 0) > 0:
            lines.append(f"--- Pinned by {post['pin_count']} readers ---")
        if annotations:
            lines.append("--- Annotations ---")
            for ann in annotations:
                lines.append(f"  {ann['author_name']} ({ann['age']}): {ann['message']}")
        lines.append(f"--- Expires in {expires_str} ---")

        return {
            "type": "read_post",
            "post_id": post_id,
            "author_name": post.get("author_name", "Unknown"),
            "author_uuid": post.get("author_uuid", ""),
            "topic": post.get("topic", "general"),
            "timestamp": post.get("timestamp", 0),
            "age": age_str,
            "expires_in": expires_str,
            "pin_count": post.get("pin_count", 0),
            "message": post.get("message", ""),
            "annotations": annotations,
            "display": "\n".join(lines),
        }

    @player_command
    def annotate(self, post_id: str, message: str) -> dict:
        """Reply to an existing post on the bulletin board."""
        if not post_id:
            return {"type": "error", "message": "Annotate which post?"}
        if not message:
            return {"type": "error", "message": "Reply what?"}
        if len(message) > MAX_MESSAGE_LENGTH:
            return {"type": "error", "message": f"Message too long. Maximum {MAX_MESSAGE_LENGTH} characters."}

        location_uuid = self.entity.location
        if not location_uuid:
            return {"type": "error", "message": "You are nowhere."}

        location_entity = Entity(uuid=location_uuid)
        board = location_entity.aspect("BulletinBoard")

        post = board._find_post(post_id)
        if not post:
            return {"type": "error", "message": f"Post [{post_id}] not found on this board."}

        annotations = post.get("annotations", [])
        if len(annotations) >= MAX_ANNOTATIONS_PER_POST:
            return {
                "type": "error",
                "message": f"This post has reached the maximum number of replies ({MAX_ANNOTATIONS_PER_POST}).",
            }

        import time
        annotation = {
            "author_uuid": self.entity.uuid,
            "author_name": self.entity.name,
            "message": message,
            "timestamp": int(time.time()),
        }
        annotations.append(annotation)
        post["annotations"] = annotations
        board._save()

        # Notify original author if present at this location
        author_uuid = post.get("author_uuid", "")
        if author_uuid and author_uuid != self.entity.uuid:
            try:
                author_entity = Entity(uuid=author_uuid)
                if author_entity.location == location_uuid:
                    author_entity.push_event({
                        "type": "board_annotation",
                        "annotator": self.entity.name,
                        "annotator_uuid": self.entity.uuid,
                        "post_id": post_id,
                        "preview": message[:80],
                        "message": f"{self.entity.name} replied to your post [{post_id}]: {message[:80]}",
                    })
            except KeyError:
                pass

        return {
            "type": "annotate_confirm",
            "post_id": post_id,
            "annotation_count": len(annotations),
            "message": f"Reply added to post [{post_id}]. ({len(annotations)}/{MAX_ANNOTATIONS_PER_POST} annotations)",
        }

    @player_command
    def pin(self, post_id: str) -> dict:
        """Pin a post to increase its visibility on the board."""
        if not post_id:
            return {"type": "error", "message": "Pin which post?"}

        location_uuid = self.entity.location
        if not location_uuid:
            return {"type": "error", "message": "You are nowhere."}

        location_entity = Entity(uuid=location_uuid)
        board = location_entity.aspect("BulletinBoard")

        post = board._find_post(post_id)
        if not post:
            return {"type": "error", "message": f"Post [{post_id}] not found on this board."}

        if post.get("author_uuid") == self.entity.uuid:
            return {"type": "error", "message": "You cannot pin your own post."}

        pinned_by = post.get("pinned_by", [])
        if self.entity.uuid in pinned_by:
            return {"type": "error", "message": "You already pinned this post."}

        pinned_by.append(self.entity.uuid)
        post["pinned_by"] = pinned_by
        post["pin_count"] = len(pinned_by)
        board._save()

        # Notify author if present
        author_uuid = post.get("author_uuid", "")
        if author_uuid:
            try:
                author_entity = Entity(uuid=author_uuid)
                if author_entity.location == location_uuid:
                    author_entity.push_event({
                        "type": "board_pinned",
                        "pinner": self.entity.name,
                        "post_id": post_id,
                        "pin_count": post["pin_count"],
                        "message": f"{self.entity.name} pinned your post [{post_id}]. ({post['pin_count']} pins)",
                    })
            except KeyError:
                pass

        return {
            "type": "pin_confirm",
            "post_id": post_id,
            "pin_count": post["pin_count"],
            "message": f"Pinned post [{post_id}]. ({post['pin_count']} pins)",
        }

    @player_command
    def topics(self) -> dict:
        """List available topic tags and post counts at the current board."""
        location_uuid = self.entity.location
        if not location_uuid:
            return {"type": "error", "message": "You are nowhere."}

        location_entity = Entity(uuid=location_uuid)
        board = location_entity.aspect("BulletinBoard")
        board._cleanup_expired()

        posts = board.data.get("posts", [])
        topic_counts = {}
        for p in posts:
            t = p.get("topic", "general")
            topic_counts[t] = topic_counts.get(t, 0) + 1

        lines = ["=== Board Topics ==="]
        for t in VALID_TOPICS:
            count = topic_counts.get(t, 0)
            if count > 0:
                lines.append(f"{t}: {count} post{'s' if count != 1 else ''}")
        lines.append(f"Total: {len(posts)} posts")

        return {
            "type": "topics",
            "location_uuid": location_uuid,
            "topic_counts": topic_counts,
            "total_posts": len(posts),
            "message": "\n".join(lines),
        }

    @player_command
    def search_board(self, query: str) -> dict:
        """Search the current board for posts containing a keyword."""
        if not query:
            return {"type": "error", "message": "Search for what?"}
        if len(query) < 2:
            return {"type": "error", "message": "Search query must be at least 2 characters."}

        location_uuid = self.entity.location
        if not location_uuid:
            return {"type": "error", "message": "You are nowhere."}

        location_entity = Entity(uuid=location_uuid)
        board = location_entity.aspect("BulletinBoard")

        posts = board.data.get("posts", [])
        query_lower = query.lower()
        results = []

        import time
        now = int(time.time())

        for p in posts:
            # Search in post message and annotations
            found = query_lower in p.get("message", "").lower()
            if not found:
                for ann in p.get("annotations", []):
                    if query_lower in ann.get("message", "").lower():
                        found = True
                        break

            if found:
                age_str = _format_age(now - p.get("timestamp", now))
                preview = p.get("message", "")[:80]
                if len(p.get("message", "")) > 80:
                    preview += "..."
                results.append({
                    "post_id": p["post_id"],
                    "author_name": p.get("author_name", "Unknown"),
                    "topic": p.get("topic", "general"),
                    "age": age_str,
                    "preview": preview,
                })
                if len(results) >= 20:
                    break

        lines = [f"Search results for '{query}': {len(results)} match{'es' if len(results) != 1 else ''}"]
        for r in results:
            lines.append(f"[{r['post_id']}] {r['author_name']} [{r['topic']}] ({r['age']}): {r['preview']}")
        if not results:
            lines.append("No matching posts found.")

        return {
            "type": "search_results",
            "query": query,
            "results": results,
            "result_count": len(results),
            "message": "\n".join(lines),
        }

    # --- Private helpers ---

    def _find_post(self, post_id: str) -> dict:
        """Find a post by its board-local ID. Returns the post dict or None."""
        for post in self.data.get("posts", []):
            if post.get("post_id") == post_id:
                return post
        return None


def _format_age(seconds: int) -> str:
    """Convert seconds to a human-readable age string."""
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h ago"
    days = seconds // 86400
    return f"{days}d ago"
```

## Cost Analysis

### Per-Operation DynamoDB Costs

| Operation | Reads | Writes | Notes |
|-----------|-------|--------|-------|
| `post` | 1 + N (broadcast) | 1 | N = entities at location. Board aspect read + save. |
| `board` | 1 | 0-1 | 1 read for board. Optional write if cleanup removes posts. |
| `read` | 1 | 0 | Board aspect read only. |
| `annotate` | 1-2 | 1 | Board read + save. Optional author entity read for notification. |
| `pin` | 1-2 | 1 | Board read + save. Optional author entity read for notification. |
| `topics` | 1 | 0-1 | Board read. Optional write for cleanup. |
| `search_board` | 1 | 0 | Board read only. All filtering in Lambda. |
| `cleanup_tick` | 1 | 0-1 | Board read. Write only if posts were removed. |
| `activate_board` | 0 | 1 | Initial aspect save. |

### Step Functions Costs

| Operation | State Transitions | Cost per Invocation |
|-----------|-------------------|---------------------|
| `cleanup_tick` (per board, every 10 min) | 1 | $0.000025 |
| `activate_board` (one-time per board) | 1 | $0.000025 |

### Monthly Cost Projections

**Assumptions:** 50 active agents, 200 rooms with active boards, each agent posts 5 messages/day, reads 20 boards/day.

| Cost Category | Calculation | Monthly Cost |
|---------------|-------------|--------------|
| Post writes | 50 agents * 5 posts/day * 30 days = 7,500 writes | 7,500 WCU-seconds at 1 WCU = negligible |
| Post reads (board command) | 50 agents * 20 reads/day * 30 days = 30,000 reads | 30,000 RCU-seconds at 1 RCU = negligible |
| Broadcast reads per post | 5 posts/day * 50 agents * 10 entities/room = 25,000 reads | Shared with other broadcast costs |
| Cleanup ticks | 200 boards * 6/hour * 24 hours * 30 days = 864,000 transitions | 864,000 * $0.000025 = $21.60 |
| Cleanup DynamoDB | 200 boards * 144/day * 30 days = 864,000 reads + ~86,400 writes | Shared table capacity |
| **Total Step Functions** | | **$21.60/month** |
| **Total DynamoDB** | | **Dominated by cleanup reads, within provisioned capacity at low agent counts** |

### Cost Scaling Concerns

At 200 active boards running cleanup ticks every 10 minutes:
- 200 reads every 10 minutes = 0.33 reads/second (within 1 RCU)
- 200 writes every 10 minutes (worst case, all have expired posts) = 0.33 writes/second (within 1 WCU)

At 1,000 active boards:
- 1.67 reads/second from cleanup alone -- exceeds 1 RCU provisioned capacity
- Solution: increase cleanup interval to 30 minutes for low-activity boards, reducing to 0.56 reads/second

### Optimization: Lazy Board Activation

Not every room needs an active cleanup tick. Only rooms that have received at least one post need cleanup. The `post` command activates the cleanup tick loop on first use. Rooms that never receive posts never start a cleanup tick. This bounds the active board count to rooms where agents actually post, which is typically a small fraction of total rooms (landmarks, settlements, dungeon entrances).

## Future Considerations

1. **Per-post DynamoDB items (migration path).** If write contention at popular locations becomes a real problem in production, migrate from the single-record model (all posts in one aspect record) to a per-post item model. Each post becomes its own DynamoDB item with a GSI on `location_uuid` for querying. This eliminates write contention entirely but increases read costs (1 RCU per post read instead of 1 RCU for the whole board) and breaks the one-record-per-aspect pattern. The migration can be done incrementally: new posts use the per-item model, old posts are read from the aspect record until they expire.

2. **Cross-location board search.** Currently, agents can only search the board at their current location. A global search command (`search_all_boards <query>`) would require scanning every active board -- prohibitively expensive with the single-record model but feasible with per-post items and a GSI. This enables agents to find relevant information without traveling to every landmark.

3. **Board subscriptions.** An agent could "subscribe" to a board and receive notifications when new posts are added, even when not at the location. This requires storing subscriber UUIDs on the board and using `whisper`-style direct push when posts are made. Cost: O(S) entity reads per post, where S = subscribers.

4. **Reputation-gated posting.** In conjunction with the Faction system, faction-controlled locations could restrict posting to agents with sufficient faction reputation. This prevents griefing (hostile agents posting misleading information in faction territory) and adds faction value.

5. **NPC-generated posts.** NPCs could automatically post to boards during their tick loops: merchants posting trade offers, guards posting patrol reports, quest-givers posting bounties. This populates boards organically and gives agents a reason to check boards regularly. Cost: 1 write per NPC post per tick cycle (not per tick -- maybe once per hour).

6. **Map integration.** The Cartography system could mark rooms with active, high-pin boards on the player's map. A special symbol (e.g., "!") indicates a location with important bulletin board content. This rewards agents who post useful information by driving traffic to their posts.

7. **Post editing and deletion.** Currently, posts cannot be edited or deleted by their authors. Adding `edit_post` and `delete_post` commands would give authors control over their content. This is straightforward to implement but adds write contention risk (edit is a read-modify-write on the board record).

8. **Anonymous posting.** Allow agents to post without their name attached. Useful for sensitive information (faction intelligence, warnings about specific agents). Adds social dynamics but complicates moderation.

9. **Sticky posts.** Allow certain posts (e.g., system announcements, landmark descriptions) to be permanently pinned and never expire. These would be exempt from TTL cleanup. Useful for worldgen-created lore posts at landmarks.

10. **Post reactions beyond pins.** Add a `react <post_id> <emoji>` command allowing agents to react with predefined reactions (helpful, misleading, outdated, funny). Reactions provide richer feedback than binary pin/no-pin but add data growth per post.

11. **Board capacity scaling.** If a single board becomes very active (hundreds of posts per day), consider sharding the board by topic -- each topic gets its own aspect record. This multiplies the number of DynamoDB records per active board but eliminates cross-topic write contention and keeps individual records smaller.

12. **Expiration notifications.** When a post is about to expire (e.g., 1 hour remaining), notify the author via whisper if they are online. This gives authors a chance to renew their posts.
