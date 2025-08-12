# CardCapture Student Registration System

A secure, dual-path student registration system with magic link authentication and event code access.

## 🎯 Overview

This system provides two registration paths:
1. **Email Path**: Student enters email → magic link → authenticated form
2. **Event Code Path**: Student enters event code → authenticated form

Both paths lead to the same protected registration form that never exposes PII to the open internet.

## 🏗️ Architecture

### Backend Components

- **Registration API** (`/api/register/*`): Core registration endpoints
- **Session Management**: Secure form sessions with HttpOnly cookies
- **Rate Limiting**: IP and email-based rate limiting
- **CAPTCHA Integration**: Pluggable invisible CAPTCHA providers
- **Magic Links**: Secure token-based email verification
- **Event Codes**: Time-bounded 6-digit codes for event access

### Frontend Components

- **RegisterPage** (`/register`): Landing page with dual CTAs
- **CheckEmailPage**: Email confirmation flow
- **RegistrationFormPage**: Protected registration form
- **VerifyEmailPage**: Email verification handler

### Database Schema

```sql
-- New tables
event_codes         -- Event access codes
form_sessions       -- Short-lived form access tokens
registration_attempts   -- Rate limiting data
registration_metrics    -- Analytics

-- Extended tables  
students.verified        -- Email verification status
students.source_method   -- Registration path tracking
```

## 🚀 Setup & Configuration

### 1. Database Migration

```bash
# Run the migration
cd /path/to/card-capture-api
supabase migration up
```

### 2. Environment Variables

```bash
# Required
DATABASE_URL=your_supabase_url
RESEND_API_KEY=your_resend_key
FRONTEND_URL=http://localhost:3000

# Optional CAPTCHA (defaults to noop)
CAPTCHA_PROVIDER=noop|hcaptcha|recaptcha
HCAPTCHA_SECRET_KEY=your_hcaptcha_secret
RECAPTCHA_SECRET_KEY=your_recaptcha_secret
RECAPTCHA_MIN_SCORE=0.5
```

### 3. Start Services

```bash
# Backend
cd card-capture-api
python -m uvicorn app.main:app --reload --port 8000

# Frontend
cd card-capture-fe  
npm run dev
```

## 📋 API Endpoints

### Registration Flow

```
POST /api/register/start-email
POST /api/register/verify-event-code
GET  /api/register/verify-magic-link?token=...
GET  /api/register/form-session
POST /api/register/submit
POST /api/register/verify-email
POST /api/register/resend-verification
```

### Event Code Management

```
POST /events/{event_id}/codes        # Create code
GET  /events/{event_id}/codes        # List codes  
PATCH /events/codes/{code_id}        # Update code
DELETE /events/codes/{code_id}       # Deactivate code
```

## 🛡️ Security Features

### Rate Limiting
- **Email starts**: 10/minute per IP, 3/hour per email
- **Code verification**: 20/minute per IP
- **Form submission**: 5/10 minutes per IP

### Session Security
- HttpOnly, Secure cookies
- 30-minute TTL
- Path-restricted to `/register`
- Database-backed for auditability

### Input Validation
- Email format + disposable domain blocking
- Phone number format validation
- Name field sanitization
- Form field type validation

### Access Control
- Form never publicly accessible
- Session required for form access
- RLS policies on all tables
- Anonymous access blocked

## 🌟 User Experience

### Email Flow
1. Student visits `/register`
2. Clicks "Continue with Email"
3. Enters email → receives magic link
4. Clicks link → redirected to form
5. Completes form → verified immediately

### Event Code Flow  
1. Student visits `/register`
2. Clicks "I have an Event Code"
3. Enters 6-digit code → form access
4. Completes form → pending verification
5. Receives verification email → clicks to verify

## 🔧 Event Code Management

Admins can create event codes through the API:

```bash
# Create event code
curl -X POST /events/{event_id}/codes \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "max_uses": 1000,
    "valid_days": 7,
    "metadata": {"location": "College Fair"}
  }'

# Response: {"code": "123456", "valid_until": "2024-01-01T00:00:00Z", ...}
```

## 📊 Analytics & Monitoring

### Metrics Tracked
- Email starts, magic link clicks, form opens
- Code verification attempts, form submissions
- Email verification completions
- Drop-off points in funnel

### Log Monitoring
- Rate limit violations
- CAPTCHA failures  
- Invalid tokens/codes
- Form validation errors

## 🧪 Testing

### Run Test Suite
```bash
cd card-capture-api
python test_registration.py
```

### Manual Testing

1. **Email Path**:
   - Visit `/register`
   - Enter valid email
   - Check email for magic link
   - Complete form

2. **Event Code Path**:
   - Create event code via API
   - Visit `/register`
   - Enter event code
   - Complete form
   - Verify via email

## 🔍 Troubleshooting

### Common Issues

**"Session expired"**
- Sessions expire after 30 minutes
- Clear cookies and restart flow

**"Rate limit exceeded"** 
- Wait for rate limit window to reset
- Check IP/email attempt counts in `registration_attempts`

**"CAPTCHA verification failed"**
- Ensure CAPTCHA provider is configured
- Check network connectivity
- Falls back to noop in dev

**Magic link expired**
- Links expire after 24 hours
- Request new link from `/register`

**Event code invalid**
- Check code is active and not expired
- Verify max usage limits
- Ensure code belongs to valid event

## 🔄 Migration from Legacy System

The old `/register` route now points to the new system. Legacy route is available at `/register-legacy` for backward compatibility.

### Data Migration
Existing students are compatible - the new system extends the existing `students` table with `verified` and `source_method` fields.

## 🎛️ Configuration Options

### CAPTCHA Providers
- **noop**: Development mode (always passes)
- **hcaptcha**: Invisible hCaptcha
- **recaptcha**: Google reCAPTCHA v3

### Rate Limits
Configurable in `app/core/rate_limiter.py`:
- Adjust limits per endpoint
- Modify time windows
- Add new rate limiters

### Session TTL
Configurable in `app/core/session_manager.py`:
- Default: 30 minutes
- Adjust for user experience vs security

## 📚 Development

### Adding New Fields
1. Add to `students` table schema
2. Update `RegistrationFormData` interface  
3. Add to frontend form
4. Update validation in service

### New Registration Paths
1. Create session type in `form_sessions`
2. Add API endpoint in `registration.py`
3. Implement service method
4. Add frontend flow

### Custom Validation
Add validators in `registration_service.py`:
```python
def _validate_custom_field(self, value: str) -> bool:
    # Custom validation logic
    return True
```

This system provides a secure, scalable foundation for student registration that protects privacy while enabling smooth user experiences.