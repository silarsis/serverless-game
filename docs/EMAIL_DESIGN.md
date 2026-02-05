# Email Verification System Design – serverless-game

## 1. Email Delivery Mechanism

### Options Considered
- **AWS SES (Simple Email Service):**
  - **Pros:**
    - Deep AWS integration (IAM, Lambda, CloudWatch)
    - Extremely cost-effective ($0.10/1,000 emails after 62,000 free/month)
    - Highly reliable and scalable
    - Supports API and SMTP
  - **Cons:**
    - Can be complex to set up initially (DKIM, SPF, verification)
    - Sandbox restrictions until account is verified
    - Limited support on lower AWS plans
- **SendGrid:**
  - **Pros:**
    - Popular among developers, good docs
    - Managed dashboards, analytics, better support tiers
    - Less AWS lock-in
  - **Cons:**
    - Higher pricing at scale (~$20 per 75,000 emails)
    - Third-party dependency, rate limits possible
    - Can require extra middleware for complex flows
- **Direct SMTP (using Lambda to connect to other SMTP):**
  - **Pros:**
    - Use with any existing SMTP server
    - No extra vendor lock-in
  - **Cons:**
    - Reliability & deliverability issues
    - More likely to get flagged as spam
    - Management overhead (rate limits, IP reputation, blacklisting)

### **Recommendation:**
**AWS SES** is highly cost-effective, reliable, and integrates natively with Lambda and the rest of our stack. We recommend SES unless you require SendGrid's analytics, dashboards, or multi-cloud support.


## 2. Email Sending Architecture

### Synchronous (API waits for send)
- Simpler for small scale
- API call latency depends on email sending speed
- If SES/SMTP is slow, user registration delays
- Email errors surface immediately

### Asynchronous (decoupled)
- **Pattern:** Lambda → (SNS/SQS/EventBridge queue) → Email Lambda sender
- API can respond instantly; email sending retries, backoff, DLQs handled separately
- Handles spikes, retries on SES throttle, isolates failures
- Scalable: async patterns are best practice in serverless

### **Recommendation:**
**Async email sending** via SNS or SQS trigger to a dedicated "send email" Lambda. Improves reliability and user experience.


## 3. Token Management

### Where to store verification tokens?
- **users Table (with token & TTL columns):**
  - Simple for small scale
  - Problematic if you want multiple unexpired tokens (resends)
- **Separate verifications Table:**
  - Store: id, user_id, token, expiry, status
  - Easily handles multiple valid tokens for one user (e.g., rate limiting, resends)
  - Easier to query for expired tokens and cleanup

### **Recommendation:**
- Create a **`verifications` table** (user_id, token, expiry, status)
- Always generate new token on resend, store each instance
- Cleanup old tokens via scheduled Lambda/TTL


## 4. Resend Verification Handling
- Allow one active token per user, or keep all (and only newest counts)
- Rate-limit resends (e.g., max every 60 seconds; 5/hour)
- On resend, old tokens expire, new one issued
- Expose endpoint for resending; same SNS process triggers email with latest token


## 5. Error Handling Strategy

### Issues:
- SES/SMTP failures (log/retry via SQS DLQ)
- Bounced emails (handled by SES bounce notifications via SNS)
- Invalid emails (validate syntactically before send)
- Rate limit resend endpoint, log abuse

#### **Tactics:**
- Use **SES SNS bounce notifications** to mark emails invalid in DB
- All email sends should be idempotent and retryable (async, DLQ)
- Use reasonable rate limits (per IP and per email)
- Log failed deliveries for manual review


## 6. Email Content and Template

- Use **plain text** for reliability (consider adding HTML later)
- Template system: Keep one base template, interpolate values in Lambda
- Minimal branding, clear call-to-action
- Verification link = `https://app.example.com/verify?token=XXXX`

#### **Example Template (Plain Text)**
```
Subject: Verify your email – serverless-game

Hi {{username}},

Thanks for registering for serverless-game!

Please verify your email by clicking the link below:

{{verification_link}}

If you didn't sign up, you can ignore this email.

Thanks,
The serverless-game team
```

## 7. Sample Code: Sending Email from Lambda with SES

```js
// AWS SDK v3 (Node.js)
import { SESClient, SendEmailCommand } from '@aws-sdk/client-ses';

const ses = new SESClient({ region: 'us-east-1' });

export async function sendVerificationEmail({ to, username, token }) {
  const verificationLink = `https://app.example.com/verify?token=${token}`;
  const params = {
    Source: 'no-reply@example.com',
    Destination: { ToAddresses: [to] },
    Message: {
      Subject: { Data: 'Verify your email – serverless-game' },
      Body: {
        Text: {
          Data: `Hi ${username},\n\nPlease verify: ${verificationLink}\n\n— Team`,
        },
      },
    },
  };
  await ses.send(new SendEmailCommand(params));
}
```

---

# Summary Table
- **Service:** AWS SES (recommended)
- **Architecture:** Async send via SNS→Lambda
- **Token Storage:** Separate verifications table
- **Errors:** Async retries, SNS bounce handling, rate limiting
- **Template:** Plain text (sample above)

---
For further questions, see the AWS SES and Lambda docs, or this file's source links.