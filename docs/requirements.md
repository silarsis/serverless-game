# User Registration & Authentication Requirements — serverless-game

**Status:** ✅ Google OAuth 2.0 with Google Sign-In (no passwords, no Firebase)

**Previous approaches:**
- See `AUTH_DESIGN.md` and `EMAIL_DESIGN.md` for deprecated email/password design
- See `design/decisions/archive/firebase-auth.md` for deprecated Firebase Auth design

---

## Goal

Enable user authentication and automatic player entity creation using Google OAuth 2.0 with Google Sign-In. No password management, no email verification complexity — direct Google OAuth without Firebase middleware.

---

## Authentication Method

**Google OAuth 2.0 with Google Sign-In only.**

**Why:**
- No password to manage, hash, or breach
- Google handles email verification, 2FA, account recovery
- Users trust "Sign in with Google"
- Direct OAuth flow — no Firebase abstraction layer
- Full control over token handling and session management

---

## User Flow

### First-Time User
1. Clicks "Sign in with Google" button
2. Frontend redirects to Google OAuth consent screen
3. User selects Google account, consents
4. Google redirects back with authorization code
5. Frontend exchanges code for Google ID token (or backend does this)
6. Frontend sends Google ID token to backend `/api/auth/login`
7. Backend verifies token directly with Google (tokeninfo endpoint or OAuth2 library)
8. Backend creates `users` table entry (if new)
9. Backend auto-creates Player entity at (0,0,0)
10. Backend issues internal JWT with entity info
11. Frontend stores token, connects to WebSocket
12. WebSocket auto-possesses Player entity

### Returning User
1. Clicks "Sign in with Google"
2. If already signed into Google with consent: seamless redirect
3. Backend finds existing user → returns existing entity assignment
4. Same WebSocket possession flow

### Sign Out
1. Client clears internal JWT from storage
2. Optionally: redirect to Google logout or revoke token
3. WebSocket disconnects
4. Backend needs no action (stateless JWT)

---

## Database Schema

### DynamoDB `users` Table

| Field | Type | Description |
|-------|------|-------------|
| `google_id` | PK (string) | Google OAuth user ID (sub claim, unique) |
| `email` | string | From Google profile (verified) |
| `display_name` | string | From Google profile |
| `photo_url` | string | From Google profile (optional) |
| `entity_uuid` | string | Player entity UUID |
| `entity_aspect` | string | "aspects/player" |
| `created_at` | number | Unix timestamp (first sign-in) |
| `last_login` | number | Unix timestamp |

**GSIs:**
- `entity_uuid-index` — For reverse lookup (entity → user)

---

## API Endpoints

### `POST /api/auth/login`

Authenticates user with Google ID token, creates user/entity if needed.

**Headers:**
```
Authorization: Bearer <google_id_token>
```

**Response (200):**
```json
{
  "token": "<internal_jwt>",
  "user": {
    "google_id": "...",
    "email": "user@example.com",
    "display_name": "User Name",
    "photo_url": "https://..."
  },
  "entity": {
    "uuid": "...",
    "aspect": "aspects/player",
    "location": {"x": 0, "y": 0, "z": 0}
  }
}
```

**Errors:**
- `401` — Invalid/expired Google token
- `500` — Database or entity creation failure

### `POST /api/auth/logout`

Client-side operation. Backend accepts for analytics but is stateless.

**Headers:**
```
Authorization: Bearer <internal_jwt>
```

**Response:** `200` with empty body

---

## WebSocket Authentication

WebSocket connection uses internal JWT issued by backend:

**Connection:**
```
wss://game.example.com/ws?token=<internal_jwt>
```

Or via header (if supported by API Gateway):
```
X-Api-Key: <internal_jwt>
```

**Auto-Possession:**
On connect, WebSocket handler decodes JWT, extracts `entity_uuid` and `entity_aspect`, automatically possesses that entity for the connection.

---

## Frontend (React)

### Pages

1. **Landing Page** (`/`)
   - Game description
   - "Sign in with Google" button
   - Link to agent SDK docs

2. **Game Page** (`/play`)
   - Requires authentication (redirects to / if not logged in)
   - WebSocket connection panel
   - Event log (styled by event type)
   - Command input with history
   - Sidebar: location, stats, inventory

3. **Profile/Settings** (future — `/profile`)
   - Display name edit (optional)
   - Sign out button

### Components

- `SignInButton` — Google OAuth trigger (react-oauth/google or direct flow)
- `AuthProvider` — React context for auth state
- `ProtectedRoute` — Route guard requiring auth
- `GameInterface` — Main game UI with WebSocket
- `EventLog` — Scrollable event display
- `CommandInput` — Command entry with history
- `Sidebar` — Location, stats, inventory display

---

## Backend Structure

### Dependencies

```
google-auth>=2.22.0      # Verify Google ID tokens
requests>=2.31.0         # HTTP for token verification
PyJWT>=2.7.0             # Issue internal JWTs
boto3>=1.28.0            # DynamoDB
cryptography>=41.0.0     # JWT signing
```

### Lambda Functions

**`auth_login`** (`POST /api/auth/login`)
- Verify Google ID token via Google Auth library or tokeninfo endpoint
- Extract `sub` (Google ID), `email`, `name`, `picture` from token
- Get or create user in DynamoDB
- Get or create Player entity
- Issue internal JWT
- Return token + user + entity

**`auth_logout`** (`POST /api/auth/logout`)
- Optional: update last_logout timestamp
- Return success (stateless)

### WebSocket Handler
- Extract token from connection request
- Verify internal JWT
- Auto-possess entity from JWT claims
- Handle commands via `@player_command` decorator

---

## Google OAuth Setup Required

### 1. Create Google Cloud Project

- Go to https://console.cloud.google.com
- Create new project (or select existing)
- Enable billing if not already enabled

### 2. Configure OAuth Consent Screen

- APIs & Services → OAuth consent screen
- Choose "External" (for any Google user) or "Internal" (Workspace only)
- Fill in app name, support email, developer contact
- Add scopes: `openid`, `email`, `profile`
- If External: Submit for verification (1-3 days review)

### 3. Create OAuth 2.0 Credentials

- APIs & Services → Credentials
- Create OAuth client ID
- Application type: Web application
- Add authorized redirect URIs:
  - `http://localhost:3000/auth/callback` (local dev)
  - `https://game.example.com/auth/callback` (production)
- Download `client_secret.json`

### 4. Backend Configuration

- Store client ID/secret in environment variables or AWS Secrets Manager
- No service account needed for token verification (just call Google's tokeninfo endpoint)

---

## Security Considerations

- **Google tokens expire** — ID tokens valid ~1 hour, refresh via normal OAuth flow
- **Internal tokens expire** — Set 24h expiry for WebSocket auth
- **Token refresh** — Frontend handles OAuth refresh, re-calls `/login` for new internal token
- **No passwords** — Entirely eliminate password attack surface
- **Google's security** — Benefits from Google's threat detection, 2FA, anomaly detection
- **Direct verification** — Backend verifies tokens directly with Google (no middleware trust)

---

## Migration Plan

This is a **fresh approach** replacing prior auth designs.

**Deprecated:**
- `AUTH_DESIGN.md` — Email/password technical design
- `EMAIL_DESIGN.md` — Email verification/token design
- `FIREBASE_AUTH_DESIGN.md` — Firebase Auth (removed Firebase dependency)

**Current approach:**
- `design/decisions/oauth.md` — Direct Google OAuth 2.0 (this doc's technical companion)

---

## Open Questions

None — design complete, ready for implementation.

**Decisions made:**
- ✅ Direct Google OAuth 2.0 (no Firebase middleware)
- ✅ No passwords, no email verification, no forgot password
- ✅ React frontend with Google Sign-In button
- ✅ Backend verifies Google tokens directly, issues internal JWTs
- ✅ Auto-create Player entity at (0,0,0) on first sign-in
- ✅ WebSocket uses internal JWT for auto-possession

---

*Last updated: 2026-02-12*
*Previous approaches: Email/password → Firebase Auth → Direct Google OAuth*
