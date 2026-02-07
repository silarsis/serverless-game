# Google OAuth Setup Investigation — serverless-game

## Summary
This document covers the process and feasibility of setting up Google OAuth as an alternative authentication method (vs. email/password) for `serverless-game`. It details what can be automated, what requires manual browser steps, and recommends the best approach for swift and reliable implementation.

---

## 1. Google Cloud Console Access
- **Access Method:** Requires Google account with access to the Cloud Console at https://console.cloud.google.com
- **Credentials Needed:** Google OAuth login (can use password from 1Password)
- **Programmatic Access:** Some steps are scriptable (gcloud CLI, APIs), but OAuth and consent screen setup for public auth always includes browser steps for verification/approval.

## 2. Project Creation
- **Can It Be Automated?**
    - Projects can be created via the [Google Cloud Resource Manager API](https://cloud.google.com/resource-manager/docs/creating-managing-projects) (requires API access and billing setup), or using the `gcloud` CLI.
    - **Limitations:** Initial setup—especially linking billing and permissions—is easiest in the Console UI.
    - **Info Needed:** Project name, (optionally) organization/billing info.

- **Manual Steps May Be Required:** If billing isn’t already configured, MUST use web UI.

## 3. OAuth Consent Screen Setup
- **Required Fields:** App name, user support email, developer contact (can be automated for internal-only brands)
- **Automation:**
    - A brand can be created **programmatically** (**internal only**; only users in your Workspace/org can sign in — not for public/Gmail users).
    - **Limitation:** To allow public sign-in (any Google account), you must manually set brand to public and submit for review **via the web UI**: https://console.cloud.google.com/apis/credentials/consent
    - **Scopes Needed:** `openid`, `email`, `profile`

## 4. OAuth Credentials (Client ID/Secret)
- **Automation Possible:**
    - You can create OAuth clients for IAP (Identity Aware Proxy) programmatically ([docs](https://cloud.google.com/iap/docs/programmatic-oauth-clients)), but these are locked for IAP-use and can't set custom redirect URIs for stand-alone web apps.
    - **General Web App OAuth credentials** must be created manually in the Cloud Console ([see also](https://docs.n8n.io/integrations/builtin/credentials/google/oauth-generic/)).
    - Must specify Application Type as "Web Application" and assign authorized redirect URIs (`https://game.example.com/auth/callback`), then download `client_secret.json`.

- **Manual Action:** Web browser required to create and configure OAuth client for most app scenarios.

## 5. Alternative: Firebase Auth
- **Easier Approach:** Firebase Authentication provides a streamlined way to add Google Sign-In (and other auth methods) to web apps [Docs](https://firebase.google.com/docs/auth/web/google-signin).
- **Setup:**
    - Project must be created in [Firebase Console](https://console.firebase.google.com)
    - Google Sign-in can be enabled with very little configuration (select from UI, no need to create OAuth credentials manually for most use cases)
    - Provides client SDK for integration
- **Automation:** No programmatic project creation for Auth, but far less manual config for OAuth flows vs raw GCP. Once Firebase is set up, the rest is all code.

---

## Steps That CAN Be Automated
- Creating GCP projects (if you have billing and permissions set)
- API enabling (gcloud CLI or REST)
- Adding users/roles (for internal brands only)

## Steps That REQUIRE Manual Browser Interaction
- Setting OAuth Consent Screen to "public" (required for any user, not just G Suite/Workspace)
- Creating regular OAuth credentials with custom redirect URIs for a general web app
- Downloading client secrets from the console
- Enabling Google Sign-In in Firebase Console (but very fast — just a few clicks)

---

## Recommended Approach
- **Firebase Auth** is *strongly* recommended for new user-facing projects — fewer manual steps, instant (painless) Google Sign-In, clear documentation, much less scope/data review friction. Only need the Firebase Console for a few minutes during setup.
- **Classic Google OAuth via Cloud Console** is only needed if you require fine-grained control or use outside Google/Firebase ecosystem (slower, more manual config, more review required for public OAuth consent).

---

## Manual Step-by-Step (if needed)
**Google Cloud OAuth (Basic Web App):**
1. Visit https://console.cloud.google.com
2. Log in with your Google account
3. Click the project dropdown (top bar), select "New Project"
    - Enter a meaningful Project Name
    - Choose (or create) an Organization if needed
    - Attach to Billing Account
    - Click "Create"
4. In left menu: APIs & Services → OAuth consent screen
    - Set App Info (name, support email, etc.)
    - Choose **External** (if you want public users)
    - Fill in required fields, Save
    - If public: Submit for verification (can take 1–3 days for review)
5. APIs & Services → Credentials
    - Click "Create Credentials", choose "OAuth client ID"
    - App Type: Web Application
    - Enter name, add Authorized Redirect URI: `https://game.example.com/auth/callback`
    - Save, download `client_secret.json`
6. Provide the downloaded credentials file securely (e.g., encrypted email or secure file transfer service).

---

## Time Estimates
- **Firebase Auth**: 5-15 minutes (once logged in)
- **Classic Google OAuth**: 15-45 minutes (+ extra days if public verification required)

---

## Conclusion
- **Automation ceiling:** Cloud APIs allow some scaffolding, but public OAuth setup for web users always requires browser-based steps due to Google’s verification and security requirements.
- **Recommended for most:** Use Firebase Auth unless you need raw OAuth for cross-platform or non-Firebase needs.
- **If you want help performing the manual steps:** see above checklist and let me know when you have provided credentials.
