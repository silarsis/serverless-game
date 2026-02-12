# User Registration & Authentication Requirements — serverless-game

**Status:** 🔄 Updated for Firebase Auth with Google Sign-In only (no passwords)

**Previous approach:** See `AUTH_DESIGN.md` and `EMAIL_DESIGN.md` for email/password design (deprecated in favor of Firebase Auth).

---

## Goal

Enable user authentication and automatic player entity creation using Firebase Authentication with Google Sign-In. No password management, no email verification complexity — leverage Google's infrastructure.

---

## Authentication Method

**Firebase Authentication with Google Sign-In only.**

**Why:**
- No password to manage, hash, or breach
- Google handles email verification, 2FA, account recovery
- Users trust "Sign in with Google"
- Client SDK handles tokens automatically
- Free tier: 10,000 sign-ins/month

---

## User Flow

### First-Time User
1. Clicks "Sign in with Google" button
2. Google OAuth popup (or redirect)
3. User selects Google account, consents
4. Firebase returns ID token to frontend
5. Frontend sends ID token to backend `/api/auth/login`
6. Backend verifies with Firebase Admin SDK
7. Backend creates `users` table entry (if new)
8. Backend auto-creates Player entity at (0,0,0)
9. Backend issues internal JWT with entity info
10. Frontend stores token, connects to WebSocket
11. WebSocket auto-possesses Player entity

### Returning User
1. Clicks "Sign in with Google"
2. If already signed into Google: seamless, no popup
3. Backend finds existing user → returns existing entity assignment
4. Same WebSocket possession flow

### Sign Out
1. Client calls Firebase SDK `signOut()`
2. WebSocket disconnects
3. Backend needs no action (stateless JWT)

---

## Database Schema

### DynamoDB `users` Table

| Field | Type | Description |
|-------|------|-------------|
| `firebase_uid` | PK (string) | Firebase Auth UID (unique) |
| `email` | string | From Google profile |
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

Authenticates user with Firebase ID token, creates user/entity if needed.

**Headers:**
```
Authorization: Bearer <firebase_id_token>
```

**Response (200):**
```json
{
  "token": "<internal_jwt>",
  "user": {
    "firebase_uid": "...",
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
- `401` — Invalid/expired Firebase token
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

- `SignInButton` — Firebase Google Auth trigger
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
firebase-admin>=6.2.0    # Verify Firebase ID tokens
PyJWT>=2.7.0             # Issue internal JWTs
boto3>=1.28.0            # DynamoDB
cryptography>=41.0.0     # JWT signing
```

### Lambda Functions

**`auth_login`** (`POST /api/auth/login`)
- Verify Firebase ID token via Admin SDK
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

## Firebase Setup Required

### 1. Create Firebase Project

- Go to https://console.firebase.google.com
- Add project (can reuse existing Google Cloud project)

### 2. Enable Google Sign-In

- Authentication → Sign-in method → Google → Enable
- Configure support email

### 3. Frontend Config

- Register web app in Firebase Console
- Get `firebaseConfig` (apiKey, authDomain, projectId, etc.)

### 4. Backend Service Account

- Project settings → Service accounts
- Generate private key JSON
- Download for Lambda deployment

---

## Security Considerations

- **Firebase tokens expire** — ID tokens valid ~1 hour, refresh automatically
- **Internal tokens expire** — Set 24h expiry for WebSocket auth
- **Token refresh** — Frontend handles Firebase refresh, re-calls `/login` for new internal token
- **No passwords** — Entirely eliminate password attack surface
- **Google's security** — Benefits from Google's threat detection, 2FA, anomaly detection

---

## Migration Plan

This is a **fresh approach** replacing the email/password design.

**Deprecated:**
- `AUTH_DESIGN.md` — Email/password technical design
- `EMAIL_DESIGN.md` — Email verification/token design

**Current approach:**
- `FIREBASE_AUTH_DESIGN.md` — Firebase Auth with Google Sign-In (this doc's technical companion)

---

## Open Questions

None — design complete, ready for implementation.

**Decisions made:**
- ✅ Firebase Auth with Google Sign-In only
- ✅ No passwords, no email verification, no forgot password
- ✅ React frontend with Firebase client SDK
- ✅ Backend verifies Firebase tokens, issues internal JWTs
- ✅ Auto-create Player entity at (0,0,0) on first sign-in
- ✅ WebSocket uses internal JWT for auto-possession

---

*Last updated: 2026-02-05*
*Previous approach: Email/password with verification (see AUTH_DESIGN.md, EMAIL_DESIGN.md)*
