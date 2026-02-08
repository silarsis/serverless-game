# /design — System Design Document Writer

Brainstorm, expand, critique, and write a complete design document for a new game system, following the established pattern in `docs/designs/`.

## Arguments
- `$ARGUMENTS` — Required: a description of the system to design (e.g., "player identity and appearance", "pet system", "auction house"). Can include specific requirements or constraints.

## Workflow

### 1. Research the Codebase

Before designing anything, deeply understand the existing architecture:

a. **Read core files** to understand patterns:
   - `backend/aspects/thing.py` — Entity/Aspect base classes, Call system, broadcast_to_location
   - `backend/aspects/land.py` — Land/Location aspect (movement, look, room generation)
   - `backend/aspects/inventory.py` — Inventory aspect (items, examine, take/drop)
   - `backend/aspects/communication.py` — Communication aspect (say, whisper, emote)
   - `backend/aspects/decorators.py` — @player_command and @callable decorators
   - `scripts/local-server.py` — WebSocket server, command routing, player creation

b. **Read existing design docs** for context and to avoid overlap:
   ```
   ls docs/designs/
   ```
   - Skim at least 3-4 existing docs to understand cross-references
   - Check if the proposed system overlaps with any existing design

c. **Identify integration points** — which existing aspects will this system interact with? What data does it need from them?

### 2. Determine Document Number

- List existing docs in `docs/designs/` and find the next sequential number
- File naming convention: `docs/designs/NN-short-name.md` (e.g., `21-player-identity.md`)

### 3. Brainstorm

Think broadly about the system. Consider:
- What problem does this solve for players (especially AI agents)?
- What are the 5-10 core capabilities it needs?
- What existing systems does it interact with?
- What would make this uniquely valuable in a MUD designed for AI agents?
- What are the failure modes and edge cases?

### 4. Expand with Codebase-Specific Design

Map the brainstorm to the actual architecture:
- **DynamoDB tables**: Which table stores the data? (ENTITY_TABLE, LOCATION_TABLE, LAND_TABLE, or new table?) Remember: all aspects use `_tableName` pointing to an env var, most share LOCATION_TABLE.
- **Aspect pattern**: New aspect class extending `Aspect`? Or extending an existing aspect?
- **Commands**: Which `@player_command` methods does the player invoke via WebSocket?
- **Callable methods**: Which `@callable` methods are invoked via SNS dispatch (Call.now/Call.after)?
- **Events**: What WebSocket events does this push to players?
- **Entity.name / Entity.location / Entity.contents**: How does this interact with shared entity fields?
- **broadcast_to_location**: When should events be broadcast to the room?
- **DynamoDB constraints**: 400KB item limit, 1 WCU/1 RCU provisioned, put_item is full replacement (last-write-wins)

### 5. Critique Ruthlessly

Every design doc MUST include honest, thorough critique. Address:
- **DynamoDB race conditions**: put_item is last-write-wins. If two players write simultaneously, one write is lost. Where can this happen in this design?
- **Cost analysis**: Count reads and writes per operation. What's the monthly cost at 50 players, 200 players? Step Functions cost ($0.000025/transition) if using Call.after().
- **Item size growth**: Will the aspect record grow unboundedly? How close to 400KB can it get?
- **Cross-aspect coupling**: Does this system need to know about other aspects? That's an architectural violation — document it honestly.
- **Scalability**: What happens with 100 concurrent players? 1000?
- **What's NOT solved**: Every system has gaps. Name them explicitly.

### 6. Write the Document

Write the complete document with ALL 13 sections in this exact order. Every section is mandatory. The document should be 800-2000+ lines of detailed, implementation-ready design.

#### Required Sections (in order):

1. **`# Title`** — H1 heading with the aspect/system name

2. **`## What This Brings to the World`** — 3-5 paragraphs of narrative. What does this system enable? Why does it matter for AI agents specifically? What gameplay emerges from it? Be specific about current limitations it solves. This is NOT a dry summary — it's a compelling argument for why this system should exist.

3. **`## Critical Analysis`** — 5-15 numbered paragraphs of honest critique. Each paragraph addresses one specific issue: race conditions, cost concerns, architectural violations, scalability limits, design tradeoffs. Bold the first sentence of each paragraph as a summary. This section should make the reader trust the design MORE, not less — it shows you've thought through the problems.

4. **`## Overview`** — 1-2 paragraph technical summary. What is the aspect, what data does it store, what commands does it expose?

5. **`## Design Principles`** — 4-6 bold-titled principles that guide the design. Each principle is a sentence followed by 1-2 sentences of explanation. These should be opinionated and specific to this system.

6. **`## Aspect Data`** — Tables showing all stored fields. Include: Field name, Type, Default, Description. Show the DynamoDB table used. Include example data structures as Python dicts/JSON.

7. **`## Commands`** — One subsection per `@player_command`. Each command needs:
   - Function signature as a Python code block
   - Parameters table (name, type, required, default, description)
   - Returns table (field, type, description)
   - Behaviour as a numbered step list
   - Example showing input JSON and output JSON
   - DynamoDB operations count

8. **`## Callable Methods`** — One subsection per `@callable` method (internal SNS-dispatched methods). Same format as Commands but for system-to-system calls.

9. **`## Events`** — Table of all WebSocket events this system can push to players. Include: Event type, Fields, When it fires, Who receives it.

10. **`## Integration Points`** — How this system connects to other aspects. For each integration: which aspect, what data flows, who initiates, DynamoDB operations added.

11. **`## Error Handling`** — Table of all error conditions. Include: Condition, Error message, HTTP-equivalent status.

12. **`## Cost Analysis`** — Detailed DynamoDB read/write costs per operation. Monthly cost projections at different player counts. Step Functions costs if applicable. Storage growth estimates.

13. **`## Future Considerations`** — 5-10 bullet points of things deliberately NOT included in this design but worth considering later. Each should explain why it was deferred.

### 7. Save the Document

Write the completed document to `docs/designs/NN-short-name.md`.

## Important Rules
- NEVER create a thin or shallow document. Every section must have real substance.
- The Critical Analysis section is the MOST IMPORTANT section. It builds trust in the design by showing you've identified the problems before implementation.
- Always reference specific DynamoDB table names, aspect class names, and method names from the actual codebase.
- Use Python code blocks for function signatures and data structures.
- Use tables (markdown) for structured data like parameters, fields, and events.
- Cross-reference other design documents by number (e.g., "see Document 05 (Equipment)" or "as proposed in 19-social-graph.md").
- Count DynamoDB operations for every command and callable method. Be precise.
- Do NOT invent new infrastructure (no new DynamoDB tables, no new SNS topics, no new Step Functions state machines) unless absolutely necessary — and if you do, justify the cost.
- The document should be implementable by a developer who has never seen the codebase, using only the design doc and the source code.
