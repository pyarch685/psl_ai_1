# Password Reset and Recovery System - Implementation Summary

This document provides a summary of the password reset and recovery system implementation.

## Overview

A complete password reset and recovery system has been implemented with email verification tokens, following security best practices.

## Implementation Details

### 1. Database Schema

**New Table**: `password_reset_tokens`
- Location: `db/create_schema.py`
- Fields: user_id, token (hashed), created_at, expires_at, used_at
- Indexes on token, user_id, and expires_at for performance
- Foreign key relationship with users table (CASCADE on delete)

**Migration Script**: `db/migrations/001_add_password_reset_tokens.py`
- Standalone migration script for existing databases
- Idempotent (safe to run multiple times)

### 2. Email Module

**Location**: `core/email_utils.py`

**Functions**:
- `send_password_reset_email()`: Sends password reset email with token link
- `send_password_reset_confirmation_email()`: Sends confirmation after successful reset

**Features**:
- HTML and plain text email versions
- Configurable SMTP settings via environment variables
- Development mode (DISABLE_EMAIL=true) prints to console
- Support for Gmail, SendGrid, AWS SES, and other SMTP providers

### 3. API Endpoints

**Location**: `app/api.py`

#### POST /auth/forgot-password
- Request: `{ "email": "user@example.com" }`
- Generates secure token, stores hashed version in database
- Sends reset email if user exists and is active
- Always returns success (prevents email enumeration)
- Invalidates previous unused tokens

#### POST /auth/reset-password
- Request: `{ "token": "token-from-email", "new_password": "NewPass123!" }`
- Validates token (not expired, not used)
- Enforces password strength requirements
- Updates password and marks token as used
- Sends confirmation email

### 4. Security Features

**Token Generation**:
- Uses `secrets.token_urlsafe(32)` for cryptographically secure tokens
- 32 bytes = 256 bits of entropy
- URL-safe encoding for easy transmission

**Token Storage**:
- Tokens hashed with bcrypt before storage
- Only hashed version stored in database
- Original token never stored

**Token Validation**:
- 1-hour expiration time
- Single-use (marked as used after password reset)
- Old tokens automatically invalidated on new reset request

**Password Requirements**:
- Minimum 8 characters
- At least one uppercase letter
- At least one lowercase letter  
- At least one digit
- At least one special character

**Security Best Practices**:
- No email enumeration (always returns success)
- Inactive accounts cannot reset passwords
- Tokens are time-limited and single-use
- Confirmation emails sent after password change

### 5. Configuration

**Environment Variables** (`.env.example`):
```bash
# Email Configuration
DISABLE_EMAIL=true                    # Development mode
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_EMAIL=noreply@pslpredictor.com
SMTP_FROM_NAME=PSL Soccer Predictor

# Password Reset URL (frontend)
PASSWORD_RESET_URL=http://localhost:8080/reset-password
```

## Files Created/Modified

### Created:
- `core/email_utils.py` - Email sending utilities
- `db/migrations/__init__.py` - Migrations package
- `db/migrations/001_add_password_reset_tokens.py` - Migration script
- `docs/password_reset.md` - Detailed documentation
- `.env.example` - Environment configuration template
- `PASSWORD_RESET_IMPLEMENTATION.md` - This file

### Modified:
- `app/api.py` - Added endpoints and helper functions
- `db/create_schema.py` - Added password_reset_tokens table

## Setup Instructions

### For New Installations:

1. **Run database schema creation**:
   ```bash
   python db/create_schema.py
   ```
   This creates all tables including `password_reset_tokens`.

2. **Configure environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

3. **For development**, set in `.env`:
   ```bash
   DISABLE_EMAIL=true
   ```
   This prints reset links to console instead of sending emails.

### For Existing Installations:

1. **Run migration script**:
   ```bash
   python db/migrations/001_add_password_reset_tokens.py
   ```

2. **Update environment variables** in `.env`:
   Add email configuration settings (see `.env.example`)

3. **Restart application**:
   ```bash
   ./start_app.sh
   ```

## Usage Examples

### Request Password Reset:
```bash
curl -X POST http://localhost:8000/auth/forgot-password \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com"}'
```

Response:
```json
{
  "success": true,
  "message": "If the email exists in our system, a password reset link has been sent."
}
```

### Reset Password:
```bash
curl -X POST http://localhost:8000/auth/reset-password \
  -H "Content-Type: application/json" \
  -d '{
    "token": "secure-token-from-email",
    "new_password": "NewPassword123!"
  }'
```

Response:
```json
{
  "success": true,
  "message": "Password has been reset successfully"
}
```

## Testing

### Development Mode Testing:

1. Set `DISABLE_EMAIL=true` in `.env`
2. Start the API server
3. Request password reset for a registered email
4. Check console output for reset token and URL:
   ```
   [email] Email sending disabled. Reset token: abc123xyz...
   [email] Reset URL: http://localhost:8080/reset-password?token=abc123xyz...
   ```
5. Use the token to reset password

### Production Testing:

1. Configure SMTP settings in `.env`
2. Set `DISABLE_EMAIL=false`
3. Request password reset
4. Check email inbox for reset link
5. Click link and reset password

## API Documentation

The FastAPI automatic documentation includes the new endpoints:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Maintenance

### Cleanup Old Tokens

Consider adding a scheduled job to clean up expired tokens:

```python
# Add to jobs/scheduler.py or similar
from sqlalchemy import text
from db.engine import get_db_engine

def cleanup_expired_tokens():
    engine = get_db_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            DELETE FROM password_reset_tokens
            WHERE expires_at < NOW() - INTERVAL '7 days'
        """))
```

## Security Considerations

1. **Rate Limiting**: Consider implementing rate limiting on forgot-password endpoint
2. **HTTPS**: Always use HTTPS in production for secure token transmission
3. **Email Security**: Use app-specific passwords or OAuth for email providers
4. **Token Entropy**: 32 bytes (256 bits) provides sufficient security
5. **No Email Enumeration**: API doesn't reveal if email exists

## Support for Email Providers

### Gmail
1. Enable 2FA on your Google account
2. Generate App Password
3. Use App Password as SMTP_PASSWORD

### SendGrid
- Set SMTP_HOST=smtp.sendgrid.net
- Set SMTP_USER=apikey
- Set SMTP_PASSWORD to your SendGrid API key

### AWS SES
- Use SES SMTP credentials
- Set region-specific SMTP host
- Verify sender email/domain in SES console

## Additional Documentation

For more detailed information, see:
- `docs/password_reset.md` - Complete documentation with troubleshooting
- `.env.example` - Configuration examples
- API docs at `/docs` endpoint

## Future Enhancements

Potential improvements:
1. Rate limiting middleware
2. Account lockout after failed attempts
3. Password reset history tracking
4. Multi-factor authentication
5. Email template customization
6. Internationalization (i18n) for emails
7. SMS-based password reset option
