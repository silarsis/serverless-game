# Firebase Auth — Manual Setup (Kevin, 5 mins)

**Do this once. I'll handle all the code.**

---

## Step 1: Create Firebase Project (2 mins)

1. Go to **https://console.firebase.google.com**
2. Click **"Add project"**
3. Choose: **"serverless-game"** (or create new Google Cloud project)
4. Enable Analytics: **No** (we don't need it)
5. Wait for project creation (~30 seconds)

---

## Step 2: Enable Google Sign-In (1 min)

1. In Firebase Console sidebar → **Authentication** → **Get started**
2. Click **Sign-in method** tab
3. Click **Google** → **Enable**
4. Set **Support email**: your email (kevin@littlejohn.id.au)
5. Click **Save**

---

## Step 3: Get Frontend Config (1 min)

1. Click ⚙️ **Project settings** (gear icon, top left)
2. Under **Your apps** → click **</>** (web icon)
3. **Register app**:
   - Nickname: `serverless-game-web`
   - Check **"Also set up Firebase Hosting"** → **NO** (we don't need it)
   - Click **Register app**
4. Copy this config block (looks like):
   ```javascript
   const firebaseConfig = {
     apiKey: "AIza...",
     authDomain: "serverless-game.firebaseapp.com",
     projectId: "serverless-game",
     storageBucket: "...",
     messagingSenderId: "...",
     appId: "..."
   };
   ```
5. **Paste it to me** (Discord DM or here)

---

## Step 4: Get Backend Service Account (1 min)

1. Still in **Project settings** → **Service accounts** tab
2. Click **"Generate new private key"**
3. Click **Generate key**
4. JSON file downloads (name like `serverless-game-abc123.json`)
5. **Send it to me securely** (Discord DM attachment, 1Password, or paste contents)

---

## Done! I'll Handle:

✅ Backend Lambda (`/api/auth/login`)  
✅ DynamoDB `users` table  
✅ React sign-in component  
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

**Time estimate**: Your part = 5 minutes. My part = 1-2 hours.

**Blockers?** If any step fails, tell me where and I'll help.
