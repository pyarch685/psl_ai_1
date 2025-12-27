# Password Reset and Recovery System

This document describes the password reset and recovery system implementation.

## Overview

The password reset system allows users to securely reset their passwords via email verification tokens. It follows security best practices to protect user accounts.

## Features

- **Secure Token Generation**: Uses cryptographically secure random tokens (32 bytes, URL-safe)
- **Token Hashing**: Tokens are hashed using bcrypt before storage in database
- **Time-Limited Tokens**: Reset tokens expire after 1 hour
- **Single-Use Tokens**: Each token can only be used once
- **Email Verification**: Password reset links are sent via email
- **Security-First Design**: Doesn't reveal whether email exists in system

## API Endpoints

### 1. Request Password Reset

**Endpoint**: `POST /auth/forgot-password`

**Request Body**:
```json
{
  "email": "user@example.com"
}
```

**Response**:
```json
{
  "success": true,
  "message": "If the email exists in our system, a password reset link has been sent."
}
```

**Notes**:
- Always returns success to prevent email enumeration attacks
- Sends reset email only if user exists and account is active
- Invalidates any previous unused reset tokens for the user

### 2. Reset Password with Token

**Endpoint**: `POST /auth/reset-password`

**Request Body**:
```json
{
  "token": "secure-random-token-from-email",
  "new_password": "NewSecurePassword123!"
}
```

**Response**:
```json
{
  "success": true,
  "message": "Password has been reset successfully"
}
```

**Error Responses**:
- `400`: Invalid or expired token
- `400`: Password doesn't meet security requirements
- `403`: Account is inactive

## Database Schema

### password_reset_tokens Table

```sql
CREATE TABLE password_reset_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP,
    CHECK (LENGTH(token) > 0)
);
```

**Indexes**:
- `idx_password_reset_tokens_token` on `token`
- `idx_password_reset_tokens_user_id` on `user_id`
- `idx_password_reset_tokens_expires` on `expires_at`

## Email Configuration

Configure email settings in your `.env` file:

```bash
# For development (disables actual email sending, prints to console)
DISABLE_EMAIL=true

# For production (configure SMTP settings)
DISABLE_EMAIL=false
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-specific-password
SMTP_FROM_EMAIL=noreply@pslpredictor.com
SMTP_FROM_NAME=PSL Soccer Predictor

# Frontend reset password page URL
PASSWORD_RESET_URL=https://yourapp.com/reset-password
```

### Email Providers

#### Gmail
1. Enable 2-factor authentication
2. Generate an App Password
3. Use App Password as `SMTP_PASSWORD`

#### SendGrid
```bash
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASSWORD=your-sendgrid-api-key
```

#### AWS SES
```bash
SMTP_HOST=email-smtp.us-east-1.amazonaws.com
SMTP_PORT=587
SMTP_USER=your-ses-smtp-username
SMTP_PASSWORD=your-ses-smtp-password
```

## Security Considerations

### Token Security
- Tokens are 32 bytes (256 bits) of cryptographically secure random data
- Tokens are hashed using bcrypt before storage
- Tokens expire after 1 hour
- Tokens can only be used once
- Old tokens are automatically invalidated when a new reset is requested

### Email Enumeration Prevention
- API always returns success, never reveals if email exists
- Same response time regardless of email existence (where possible)

### Rate Limiting
Consider implementing rate limiting on the forgot-password endpoint to prevent abuse:
- Limit requests per IP address (e.g., 5 requests per hour)
- Limit requests per email (e.g., 3 requests per hour)

### Account Security
- Password requirements are enforced (minimum 8 characters, uppercase, lowercase, digit, special character)
- Inactive accounts cannot reset passwords
- Confirmation emails are sent after successful password reset

## Usage Flow

1. **User Requests Reset**:
   - User enters email on forgot password page
   - Frontend calls `POST /auth/forgot-password`
   - Backend generates secure token and sends email

2. **User Receives Email**:
   - Email contains reset link with token
   - Link format: `https://yourapp.com/reset-password?token=TOKEN`
   - Token expires in 1 hour

3. **User Resets Password**:
   - User clicks link and enters new password
   - Frontend calls `POST /auth/reset-password` with token and new password
   - Backend validates token, updates password, marks token as used

4. **User Receives Confirmation**:
   - Confirmation email is sent
   - User can now log in with new password

## Testing

### Development Mode
Set `DISABLE_EMAIL=true` in `.env` to print reset links to console instead of sending emails:

```bash
[email] Email sending disabled. Reset token: abc123...
[email] Reset URL: http://localhost:8080/reset-password?token=abc123...
```

### Manual Testing

1. Start the API server
2. Register a user
3. Request password reset:
   ```bash
   curl -X POST http://localhost:8000/auth/forgot-password \
     -H "Content-Type: application/json" \
     -d '{"email": "test@example.com"}'
   ```
4. Copy token from console output (if DISABLE_EMAIL=true)
5. Reset password:
   ```bash
   curl -X POST http://localhost:8000/auth/reset-password \
     -H "Content-Type: application/json" \
     -d '{"token": "TOKEN_HERE", "new_password": "NewPassword123!"}'
   ```

## Maintenance

### Cleanup Old Tokens
Consider adding a periodic job to clean up expired tokens:

```sql
DELETE FROM password_reset_tokens
WHERE expires_at < NOW() - INTERVAL '7 days';
```

This can be added as a scheduled task or part of the application startup routine.

## Troubleshooting

### Emails Not Sending
1. Check SMTP credentials in `.env`
2. Verify SMTP server is accessible
3. Check firewall rules for SMTP port (587)
4. Review application logs for error messages
5. Test SMTP connection manually

### Tokens Not Working
1. Verify token hasn't expired (1 hour limit)
2. Check token hasn't been used already
3. Ensure token is being sent correctly (no truncation)
4. Verify database connection and schema is up to date

### Password Requirements
Passwords must meet these requirements:
- Minimum 8 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one digit
- At least one special character (!@#$%^&*()_+-=[]{}|;:,.<>?)
