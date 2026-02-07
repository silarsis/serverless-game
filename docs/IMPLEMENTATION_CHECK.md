# Implementation Readiness Check

**For:** Coding sub-agent (opencode)
**Context:** Auth system implementation about to begin

## Current Design Status

### Completed Design Docs:
- ✅ `REQUIREMENTS.md` — Feature requirements, decisions made
- ✅ `AUTH_DESIGN.md` — Technical auth design (argon2, PyJWT, flows)
- ✅ `EMAIL_DESIGN.md` — MVP token display + SES production path
- ✅ `DESIGN_CONTEXT.md` — Updated TODO list

### Decisions Confirmed:
1. **Password requirements:** None for MVP
2. **Rate limiting:** None for MVP (noted for future)
3. **Forgot password:** Yes, implement now
4. **Email (MVP):** Display token on page, no email service
5. **Email (production):** AWS SES (investigating setup)
6. **Starting location:** 0,0,0
7. **Display names:** Entity name (not player)
8. **Starting gear:** None
9. **Web stack:** React
10. **OAuth:** Investigating Google setup (separate task)

### Open Investigation:
- ⏳ Google OAuth setup feasibility (sub-agent running)

## What We're Building (MVP)

### Backend:
1. `users` DynamoDB table (email PK, password hash, tokens, entity assignment)
2. Registration API (create user, generate verify token, return in response)
3. Verification API (validate token, activate user, create Player entity at 0,0,0)
4. Login API (validate password, issue JWT with entity info)
5. Forgot password APIs (request reset token, validate & update password)

### Frontend (React):
1. Landing page
2. Signup form → shows verification code
3. Verification code entry → redirects to game
4. Login form
5. Forgot password flow (request + reset)
6. Game page (`/play`) — WebSocket connection, event log, command input

### WebSocket:
1. Auto-possess entity on connect (lookup from user record)
2. JWT auth in header

## Question for Coder Sub-Agent

**Is this design sufficient to begin implementation work?**

If YES: We'll start with backend auth Lambdas and React frontend scaffold.

If NO: What's missing? What needs more detail?

Specifically:
- Are the API endpoints clear enough?
- Do you need more detail on the React component structure?
- Is the DynamoDB schema sufficiently specified?
- Any integration points that need clarification?

---

*Status: Awaiting coder sub-agent review*
