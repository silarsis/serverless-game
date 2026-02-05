# Requirements: Sign-Up, Auth, and Web UI

*Expanding on Kevin's requirements for user registration and web interface.*

---

## 1. User Registration & Authentication

### Sign-Up Flow

**Step 1: Email/Password Entry**
- User enters email address and password (twice to confirm)
- Client-side validation: password strength, email format
- Server checks email not already registered

**Step 2: Email Verification**
- System generates verification token (cryptographically random, time-limited)
- Sends email with verification link: `https://game.example.com/verify?token=xyz`
- Token expires after 24 hours
- User clicks link → account activated

**Step 3: Account Creation**
- On verification, system creates:
  1. User account record (email, hashed password, status=active)
  2. Player entity (assigned to user, starting location in world)
  3. JWT for immediate login
- User is automatically logged in after verification

### Login Flow

**Subsequent Logins:**
- User enters email + password
- Server validates, issues JWT
- JWT includes: `sub` (user UUID), `email`, `entity_uuid`, `entity_aspect`

### Data Storage

**New DynamoDB Table: `users`**
```
Partition Key: email (String)
Attributes:
  - user_uuid (UUID for internal refs)
  - password_hash (bcrypt/argon2)
  - status (pending_verification | active | suspended)
  - verification_token (String, TTL)
  - entity_uuid (UUID of player's entity)
  - entity_aspect (String, e.g., "Player")
  - created_at (Timestamp)
  - last_login (Timestamp)
```

**Entity Assignment:**
- New users get a fresh `Player` entity
- Starting location: configurable (origin 0,0,0? random? tutorial area?)
- Entity UUID stored in user record for lookup on login

---

## 2. Web Interface

### Public Pages

**Landing Page (`/`)**
- Game description, screenshots
- "Sign Up" and "Log In" buttons

**Sign Up Page (`/signup`)**
- Email input
- Password input + confirm password
- Submit → shows "Check your email" message

**Verify Page (`/verify?token=xyz`)**
- Validates token
- Shows success + auto-redirect to game after 3 seconds
- Or shows error (expired/invalid token) with "Resend email" option

**Log In Page (`/login`)**
- Email + password
- "Forgot password?" link (future)
- Submit → redirect to game on success

### Game Page (`/play`) - Authenticated Only

**Layout:**
```
+------------------+------------------+
|   Game World     |   Sidebar        |
|   (Event Log)    |   - Stats        |
|                  |   - Inventory    |
|   [Text output   |   - Map (mini)   |
|    scrolls here]  |                  |
|                  |   [Command Box]  |
+------------------+------------------+
```

**Components:**

*Event Log (Main Panel)*
- Scrollable text showing game events
- Styled by event type:
  - Room descriptions (neutral)
  - Combat events (red, dramatic)
  - Speech/tells (blue, quoted)
  - System messages (gray)
- Timestamps optional

*Sidebar - Status Panel*
- Current location name
- Health/energy bars (if implemented)
- Quick stats

*Sidebar - Inventory Panel*
- List of items carried
- Click to use/equip (future)

*Sidebar - Map Panel (Mini)*
- Small grid showing nearby explored areas
- Dot showing current position

*Command Input*
- Text box at bottom
- Submit on Enter
- History with up/down arrows
- Auto-complete for commands (future)
- Quick buttons for common actions: Look, Inventory, North, South, etc.

**WebSocket Integration:**
- Page loads → establishes WebSocket connection
- JWT sent in connection header
- Server auto-"possesses" the user's entity
- Events flow into Event Log in real-time
- Commands sent via WebSocket

### Styling

- Dark theme (terminal aesthetic but polished)
- Monospace font for event log
- Responsive (works on mobile, though desktop is primary)
- Minimal, distraction-free

---

## 3. Agent-Friendly API

**Goal:** AI agents should be able to play without scraping HTML.

### REST Endpoints

**Auth:**
- `POST /api/auth/register` — Create account, triggers email
- `POST /api/auth/verify` — Verify email with token
- `POST /api/auth/login` — Get JWT
- `POST /api/auth/refresh` — Refresh JWT (future)

**Player State:**
- `GET /api/player/me` — Current player entity info
- `GET /api/player/location` — Current location details
- `GET /api/player/inventory` — Inventory contents

**Commands:**
- `POST /api/command` — Send command, returns immediate result
  - Body: `{"command": "look", "args": {}}`
  - Response: `{"status": "ok", "result": {...}}`

**WebSocket Alternative:**
- Agents can use WebSocket directly (same as web UI)
- More efficient for real-time play
- REST API good for state checks, batch commands

### Agent SDK (Future)

Python package wrapping both REST and WebSocket:
```python
from serverless_game import Agent

agent = Agent(email="bot@example.com", password="...")
agent.login()
agent.connect_websocket()

# Event loop
for event in agent.events():
    if event["type"] == "room_description":
        agent.command("look")
    elif event["type"] == "combat":
        agent.command("attack", target=event["actor"])
```

---

## Decisions Made

### Security & Auth
- **Password requirements:** None for MVP (tighten when implementing OAuth)
- **Rate limiting:** None for MVP (noted for future work)
- **Forgot password:** Implement now — flow: request → email token → reset form
- **Server-side sessions:** JWT-only (stateless)

### Email
- **MVP/Testing:** Print verification code on web page (no email service needed initially)
- **Production:** AWS SES (62k free emails/month, then $0.10/1k)
- **Alternatives considered:** SendGrid (100 free/day), Mailgun (5k free/month), Postmark ($10/10k)

### Game Design
- **Starting location:** 0,0,0 (origin)
- **Display names:** Entity name (not player/web connection) — entity is the identity
- **Starting gear:** None (empty inventory)

### Technical Stack
- **Web frontend:** React (upgrade from vanilla JS)
- **Auth methods:** Email/password for now, Google OAuth next (investigating)
- **Agent API auth:** Same JWT as web (no separate API keys)

---

## Forgot Password Flow

1. User clicks "Forgot password?" on login page
2. Enters email address
3. System generates reset token (similar to verification), stores with 1h expiry
4. (MVP: Display token on page for testing) / (Production: Email token)
5. User enters token + new password
6. System validates token, updates password hash, invalidates token
7. Redirect to login

---

## MVP Testing Mode (No Email)

For initial development/testing without email service:
- Registration shows: "Your verification code: ABC123XYZ"
- User copies code to verification page
- Same flow, just no email sending

This allows testing the full flow before setting up SES/email infrastructure.

---

## Production Email (AWS SES)

**Why SES:**
- 62,000 free emails/month from EC2/Lambda
- Then $0.10 per 1,000 emails
- Native AWS integration (IAM, CloudWatch)
- Reliable deliverability

**Setup needed:**
- Verify domain or email address
- Configure DKIM/SPF (for domain)
- Move out of SES sandbox (for production)

---

## TODO Integration

These items should be inserted into DESIGN_CONTEXT.md TODO list:

**Immediate (Next Session):**
- [ ] Implement email/password registration with verification flow
- [ ] Create `users` DynamoDB table
- [ ] Set up email sending (SMTP or service)
- [ ] Auto-create Player entity on verification

**Near Term (This Week):**
- [ ] Build web UI: signup/login pages
- [ ] Build `/play` game page with WebSocket
- [ ] Style the game interface
- [ ] REST API endpoints for agent access

**Medium Term (This Month):**
- [ ] Agent SDK package
- [ ] Map visualization
- [ ] Inventory management UI

---

*Status: Requirements draft - awaiting answers to open questions*
