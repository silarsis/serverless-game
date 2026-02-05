# AUTH_DESIGN.md (Technical Design Doc)

## 1. Database Schema

### DynamoDB `users` Table
- **Partition Key:** `email` (string)
- **Attributes:**
  - `user_uuid`: string (UUIDv4, unique per user, used as `sub` in JWT)
  - `password_hash`: string (argon2 or bcrypt hash)
  - `status`: string (`pending`, `active`, `disabled`)
  - `verification_token`: string (when status=pending)
  - `verification_expiry`: number (Unix timestamp)
  - `entity_uuid`: string (Player/entity object UUID)
  - `entity_aspect`: string
- **GSIs:**
  - `user_uuid-index` (project: all)
  - `verification_token-index` (project: all)

## 2. Registration Flow (Sequence)
1. User submits registration form (email, password)
2. Lambda `auth_register`:
    - Check if email exists
    - If not, hash password (**argon2** recommended)
    - Generate `user_uuid` (UUIDv4)
    - Generate random `verification_token` (`secrets.token_urlsafe(32)`)
    - Set `verification_expiry` (now + 24h)
    - status=`pending`
    - Store in `users` table
    - Send verification email (see below)
3. User receives email, clicks verification link

## 3. Verification Flow
1. User follows `/verify?token=...`
2. Lambda `auth_verify`:
    - Lookup `verification_token` (GSI)
    - Check `verification_expiry` > now & status==`pending`
    - If valid:
      - Set status = `active`, remove token/expiry
      - Create Player entity (persist `entity_uuid`, `entity_aspect`)
      - Return success
    - If invalid/expired, return error

## 4. Login Flow
1. User submits login (email, password)
2. Lambda `auth_login`:
    - Get user by email PK
    - status must be `active`
    - Validate password (argon2/bcrypt)
    - If OK, issue JWT via **PyJWT**:
      - JWT payload: `sub`, `email`, `entity_uuid`, `entity_aspect`
      - Return JWT

## 5. Security Considerations
- **Hashing:** Use `argon2-cffi`. (Optional fallback: bcrypt for widest portability)
- **Token Generation:** `secrets.token_urlsafe(32)` ensures randomness
- **JWT:** Use `PyJWT` (well-maintained)
- **Token Expiry:** 24h, invalidate after use
- **Email:** Throttle verification attempts; optionally limit by IP/email

## 6. Lambda/Function Structure
- Separate Lambdas/functions:
  - `auth_register`
  - `auth_verify`
  - `auth_login`
- Managed as `auth` aspect if grouping supported

## 7. Email Structure
- **Preferred:** HTML+Plain text fallback
- Minimal viable: Plain text
- Example:
  ```
  Subject: Verify your serverless-game account

  Hi,

  Please verify your account by clicking the link below:
  https://yourdomain.com/verify?token=abcdef123456...

  This link will expire in 24 hours.
  Thanks,
  The serverless-game Team
  ```

## 8. Dependencies for `requirements.txt`
```
argon2-cffi>=23.1.0      # password hashing
PyJWT>=2.7.0             # JWT tokens
boto3>=1.28.0            # AWS
email-validator>=2.0.0   # (optional) strong email parsing
# (Optionally: bcrypt>=4.0.0)
```

---

### Key Picks/Reasoning Recap
1. **argon2-cffi**: strongest modern hash (as of 2024)
2. **DynamoDB**: PK=`email`, GSI on `verification_token`, `user_uuid` if needed
3. **Token**: `secrets.token_urlsafe(32)`
4. **JWT:** `PyJWT`
5. **Email:** HTML ideal, plain text is sufficient for MVP
6. **Lambda:** Separate Lambda per step, group under `auth` aspect if your model supports it
