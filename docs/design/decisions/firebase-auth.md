# Firebase Auth Design — serverless-game

**Approach:** Firebase Authentication with Google Sign-In only (no passwords)

---

## Why Firebase Auth

- **No password management** — Google handles credentials, security, breaches
- **No email verification** — Google already verified the email
- **No forgot password flow** — Google handles account recovery
- **Client SDK** — Simple frontend integration, handles tokens automatically
- **Free tier** — 10,000 sign-ins/month free, then pay-as-you-go
- **Trusted provider** — Users comfortable with "Sign in with Google"

---

## Architecture

### Sign-In Flow

```
┌─────────────┐     ┌─────────────────────┐     ┌─────────────┐
│   Browser   │────▶│  Firebase Auth SDK  │────▶│ Google OAuth│
│  (React)    │     │  (popup/redirect)   │     │  (id_token) │
└─────────────┘     └─────────────────────┘     └─────────────┘
                            │
                            ▼
                    ┌───────────────┐
                    │  Firebase ID  │
                    │    Token      │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │  Your Lambda  │
                    │  Verify Token│
                    │  + Create User│
                    └───────────────┘
```

### Backend Verification Flow

1. Frontend signs in via Firebase SDK → receives Firebase ID Token (JWT)
2. Frontend sends token to backend: `POST /api/auth/login` with `Authorization: Bearer <id_token>`
3. Backend verifies token with Firebase Admin SDK
4. If valid:
   - Extract `uid`, `email`, `name`, `picture`
   - Check if user exists in DynamoDB `users` table
   - If new user: create entry + auto-create Player entity at (0,0,0)
   - If existing: retrieve their entity assignment
5. Backend issues **internal JWT** (or use Firebase token directly) with entity info
6. WebSocket connects using internal token for possession

---

## Database Schema (Simplified)

### DynamoDB `users` Table

| Field | Type | Notes |
|-------|------|-------|
| `firebase_uid` | PK (string) | From Firebase Auth |
| `email` | string | From Google profile |
| `display_name` | string | From Google profile (optional) |
| `photo_url` | string | From Google profile (optional) |
| `entity_uuid` | string | Player entity UUID |
| `entity_aspect` | string | "aspects/player" |
| `created_at` | number | Unix timestamp |
| `last_login` | number | Unix timestamp |

**No longer needed:** password_hash, verification_token, reset_token, status

---

## API Endpoints

### `POST /api/auth/login`

**Headers:**
```
Authorization: Bearer <firebase_id_token>
```

**Response:**
```json
{
  "token": "<internal_jwt>",
  "entity": {
    "uuid": "...",
    "aspect": "aspects/player",
    "location": {"x": 0, "y": 0, "z": 0}
  }
}
```

**Flow:**
1. Verify Firebase ID token with Firebase Admin SDK
2. Get or create user in DynamoDB
3. Get or create Player entity
4. Issue internal JWT containing entity info
5. Return token for WebSocket auth

### `POST /api/auth/logout`

Client-side only — Firebase SDK handles sign-out, backend just clears any cached state.

---

## Frontend (React)

### Firebase SDK Setup

```javascript
// firebase.js
import { initializeApp } from 'firebase/app';
import { getAuth, GoogleAuthProvider, signInWithPopup } from 'firebase/auth';

const firebaseConfig = {
  apiKey: process.env.REACT_APP_FIREBASE_API_KEY,
  authDomain: process.env.REACT_APP_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.REACT_APP_FIREBASE_PROJECT_ID,
};

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
export const googleProvider = new GoogleAuthProvider();
```

### Sign-In Component

```javascript
import { signInWithPopup } from 'firebase/auth';
import { auth, googleProvider } from './firebase';

function SignIn() {
  const handleSignIn = async () => {
    try {
      const result = await signInWithPopup(auth, googleProvider);
      const idToken = await result.user.getIdToken();
      
      // Send to backend
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${idToken}`,
        },
      });
      
      const data = await response.json();
      localStorage.setItem('token', data.token);
      // Redirect to game
    } catch (error) {
      console.error('Sign-in failed:', error);
    }
  };

  return <button onClick={handleSignIn}>Sign in with Google</button>;
}
```

---

## Backend (Python Lambda)

### Dependencies

```
firebase-admin>=6.2.0    # Verify Firebase tokens
PyJWT>=2.7.0             # Issue internal tokens (optional, can use Firebase token)
boto3>=1.28.0            # DynamoDB
```

### Token Verification

```python
import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials

# Initialize once
cred = credentials.Certificate('firebase-service-account.json')
firebase_admin.initialize_app(cred)

def verify_firebase_token(id_token: str) -> dict:
    """Verify Firebase ID token, return decoded claims."""
    try:
        decoded = firebase_auth.verify_id_token(id_token)
        return {
            'uid': decoded['uid'],
            'email': decoded.get('email'),
            'name': decoded.get('name'),
            'picture': decoded.get('picture'),
        }
    except Exception as e:
        raise ValueError(f"Invalid token: {e}")
```

### Login Handler

```python
def auth_login(event, context):
    """Handle login: verify Firebase token, get/create user, return internal JWT."""
    # Extract token from Authorization header
    auth_header = event['headers'].get('Authorization', '')
    id_token = auth_header.replace('Bearer ', '')
    
    # Verify with Firebase
    firebase_user = verify_firebase_token(id_token)
    
    # Get or create user in DynamoDB
    user = get_or_create_user(
        firebase_uid=firebase_user['uid'],
        email=firebase_user['email'],
        display_name=firebase_user.get('name'),
    )
    
    # Issue internal JWT with entity info
    internal_token = create_jwt({
        'sub': user['firebase_uid'],
        'email': user['email'],
        'entity_uuid': user['entity_uuid'],
        'entity_aspect': user['entity_aspect'],
    })
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'token': internal_token,
            'entity': {
                'uuid': user['entity_uuid'],
                'aspect': user['entity_aspect'],
            }
        })
    }
```

---

## Setup Required

### 1. Create Firebase Project

1. Go to https://console.firebase.google.com
2. Click "Add project" → choose Google Cloud project (or create new)
3. Enable Google Analytics (optional)
4. Project created

### 2. Enable Google Sign-In

1. In Firebase Console → Authentication → Get started
2. Sign-in method tab → Google → Enable
3. Configure support email → Save

### 3. Get Firebase Config (Frontend)

1. Project settings → General → Your apps → Add app → Web
2. Register app (nickname: "serverless-game-web")
3. Copy config object (apiKey, authDomain, projectId, etc.)
4. Provide to me for `.env` file

### 4. Get Service Account (Backend)

1. Project settings → Service accounts
2. Click "Generate new private key"
3. Download JSON file
4. Provide securely to me for Lambda deployment

---

## WebSocket Auth

Internal JWT structure for WebSocket possession:

```json
{
  "sub": "<firebase_uid>",
  "email": "user@example.com",
  "entity_uuid": "...",
  "entity_aspect": "aspects/player",
  "iat": 1234567890,
  "exp": 1234571490
}
```

WebSocket connection sends token in `X-Api-Key` header (or query param for browser WebSocket).

---

## Migration from Password-Based (if needed)

If any existing password users:
1. Keep old auth endpoint for migration period
2. Prompt users to sign in with Google
3. Link Firebase UID to existing entity
4. Sunset password auth after 30 days

For fresh start: No migration needed.

---

## Benefits Summary

| Concern | Before (Password) | After (Firebase Auth) |
|---------|------------------|----------------------|
| Password breaches | Our problem | Google's problem |
| Email verification | Custom flow | Google handles it |
| Forgot password | Custom flow | Google handles it |
| Account security | Our responsibility | Google's 2FA/SAT/etc |
| User trust | "Can I trust this site?" | "I trust Google" |
| Implementation time | Days (custom auth) | Hours (SDK integration) |
| Cost | Free | 10k sign-ins/month free |

---

*Last updated: 2026-02-05*
