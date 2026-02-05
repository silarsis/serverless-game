# Email Verification System Design – serverless-game

## MVP Testing Mode (No Email Infrastructure)

For initial development and testing, we'll skip email delivery and display tokens directly on the web page:

**Flow:**
1. User submits registration
2. System generates verification token
3. Frontend displays: "Your verification code: XYZ123ABC - copy this and paste it on the verification page"
4. User navigates to verification page, pastes code
5. Same for forgot password reset codes

**Benefits:**
- No email service setup needed for MVP
- Immediate testing of full auth flow
- Tokens still expire (24h verification, 1h reset) for security
- Easy to switch to email later (just change token delivery method)

**Production Upgrade Path:**
Replace on-page display with email sending via SES (see below).

---

## 1. Email Delivery Mechanism (Production)

### Options Considered

| Service | Free Tier | Paid | Best For |
|---------|-----------|------|----------|
| **AWS SES** | 62,000 emails/month from EC2/Lambda | $0.10/1,000 | AWS-native, cheapest at scale |
| **SendGrid** | 100 emails/day | ~$20/75,000 | Analytics, dashboards |
| **Mailgun** | 5,000 emails/month (3 months) | $0.80/1,000 | Good deliverability |
| **Postmark** | 100 emails/month trial | $10/10,000 | Transactional focus |

### **Recommendation: AWS SES**

**Why:**
- Deep AWS integration (IAM, Lambda, CloudWatch)
- 62,000 free emails/month when sending from Lambda/EC2
- Then only $0.10 per 1,000 emails
- Reliable deliverability with proper setup
- No third-party dependency

**Setup steps:**
1. Verify domain in SES (add DKIM/SPF records)
2. Verify email address (for testing in sandbox)
3. Request production access (move out of sandbox)
4. Configure IAM role for Lambda to send email

---

## 2. Email Sending Architecture

### MVP (Testing Mode): Synchronous Token Return
- API returns token in response body
- Frontend displays token to user
- No external dependencies

### Production: Asynchronous Email Sending
**Pattern:** Lambda → SNS → Email Lambda

**Why async:**
- API responds immediately (don't wait for email)
- Retries on SES throttle automatically
- Isolates email failures from registration API
- Scales with spikes

---

## 3. Token Management

Store tokens in the `users` table:

```
verification_token: string (when status=pending)
verification_expiry: number (Unix timestamp)
reset_token: string (when password reset requested)
reset_expiry: number (Unix timestamp)
```

**Why not separate table:** Simpler for our scale, single query to check token.

**Expiry times:**
- Verification: 24 hours
- Password reset: 1 hour

---

## 4. Email Templates

### Verification Email
```
Subject: Verify your serverless-game account

Hi,

Welcome to serverless-game! Please verify your email by clicking:

https://game.example.com/verify?token=XYZ123ABC

This link expires in 24 hours.

If you didn't sign up, you can ignore this email.

— The serverless-game team
```

### Password Reset Email
```
Subject: Password reset request

Hi,

We received a request to reset your password. Click this link:

https://game.example.com/reset?token=ABC789XYZ

This link expires in 1 hour.

If you didn't request this, you can ignore this email.

— The serverless-game team
```

---

## 5. Sample Code: Lambda Sending Email (Python)

```python
import boto3
from botocore.exceptions import ClientError

ses = boto3.client('ses', region_name='us-east-1')

def send_verification_email(to_email: str, token: str):
    verification_link = f"https://game.example.com/verify?token={token}"
    
    try:
        response = ses.send_email(
            Source='no-reply@game.example.com',
            Destination={'ToAddresses': [to_email]},
            Message={
                'Subject': {'Data': 'Verify your serverless-game account'},
                'Body': {
                    'Text': {
                        'Data': f'Welcome! Verify: {verification_link}\n\nExpires in 24h.'
                    }
                }
            }
        )
        return {'message_id': response['MessageId']}
    except ClientError as e:
        return {'error': str(e)}
```

---

## Summary

| Phase | Token Delivery | Service | Notes |
|-------|----------------|---------|-------|
| **MVP** | Display on page | None | Immediate testing, no setup |
| **Staging** | SES email | AWS SES | Test with real email, still low volume |
| **Production** | SES email | AWS SES | 62k free/month, then cheap |

---

*Last updated: 2026-02-05*
