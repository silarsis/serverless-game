# Google OAuth 2.0 — Manual Setup (Kevin, 15 mins)

**Do this once. I'll handle all the code.**

---

## Step 1: Create Google Cloud Project (3 mins)

1. Go to **https://console.cloud.google.com**
2. Click project dropdown (top bar) → **New Project**
3. Project name: `serverless-game`
4. Choose organization (if you have one) or leave as "No organization"
5. Select billing account (required for OAuth)
6. Click **Create**
7. Wait for project creation (~30 seconds), then select it

---

## Step 2: Configure OAuth Consent Screen (5 mins)

1. Left sidebar → **APIs & Services** → **OAuth consent screen**
2. Choose **External** (allows any Google user to sign in)
   - If you only want Workspace users: choose **Internal**
3. Click **Create**
4. Fill in app information:
   - **App name**: `Serverless Game`
   - **User support email**: your email (kevin@littlejohn.id.au)
   - **Developer contact email**: your email
5. Click **Save and Continue**
6. On **Scopes** page → click **Add or Remove Scopes**
   - Select: `openid`, `email`, `profile`
   - Click **Update** → **Save and Continue**
7. On **Test users** page (optional for now) → **Save and Continue**
8. Click **Back to Dashboard**

**If External:** You'll need to submit for verification later (1-3 days) to remove "unverified app" warning.

---

## Step 3: Create OAuth 2.0 Credentials (3 mins)

1. Left sidebar → **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth client ID**
3. Application type: **Web application**
4. Name: `serverless-game-web`
5. **Authorized redirect URIs** (add both):
   - `http://localhost:3000/auth/callback` (local development)
   - `https://game.example.com/auth/callback` (production - update with your domain)
6. Click **Create**
7. **Copy the Client ID and Client Secret** (or download JSON)
8. **Send them to me securely** (Discord DM or 1Password)

---

## Step 4: (Optional) Submit for Verification

If you chose **External** in Step 2 and want to remove the "unverified app" warning:

1. Go back to **OAuth consent screen**
2. Click **Publish App** (or **Submit for verification**)
3. Fill out verification form (may require privacy policy URL, demo video)
4. Wait 1-3 days for Google review

**For testing:** You can use the app immediately with test users added in Step 2.

---

## Done! I'll Handle:

✅ Backend Lambda (`/api/auth/login`) — verify Google tokens  
✅ DynamoDB `users` table (google_id as primary key)  
✅ React sign-in component (Google Sign-In button)  
✅ WebSocket auth integration  
✅ Auto-create Player entity at (0,0,0)

---

## Verification (when I'm done)

You'll be able to:
1. Open game URL
2. Click "Sign in with Google"
3. Select your Google account
4. Be automatically assigned a Player entity
5. See real-time game world via WebSocket

---

## What I Need From You

Send me securely (Discord DM or 1Password):
- **Client ID** (looks like: `123-abc.apps.googleusercontent.com`)
- **Client Secret** (random string)
- **Your authorized domain** (for production redirect URI)

That's it! No service account JSON needed for OAuth 2.0.
