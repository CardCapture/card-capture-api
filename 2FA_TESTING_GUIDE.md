# CardCapture 2FA Testing Guide

## 🎯 Test Environment Setup

### Prerequisites
- ✅ Database migration applied to staging
- ✅ Twilio credentials configured in Supabase Auth settings
- ✅ Backend MFA API endpoints deployed
- ✅ Frontend components integrated

### Test Phone Number
Use your personal phone number for testing, or use Twilio's test numbers:
- Format: +1 (555) 555-5555 for US testing

## 📋 Test Scenarios

### 1. New User Magic Link Signup → First Password Login
**Expected Flow:**
1. User signs up with magic link via email ✨
2. User logs in with email/password for the first time
3. System prompts for MFA enrollment
4. User enters phone number, receives SMS
5. User enters 6-digit code → MFA enabled
6. User can check "Remember this device for 30 days"

**Test Steps:**
```bash
# 1. Create new user account via magic link
# 2. Set password during signup process
# 3. Login with email/password
# 4. Should show MFA enrollment modal
# 5. Enter phone: +1 (your-number)
# 6. Check SMS for 6-digit code
# 7. Enter code in auto-advancing inputs
# 8. Save backup codes shown
# 9. Check "Remember device" checkbox
```

### 2. Existing User with MFA - New Device
**Expected Flow:**
1. User logs in from new device/browser
2. Password accepted → MFA challenge appears
3. SMS sent to enrolled phone
4. User enters 6-digit code
5. Option to remember new device

**Test Steps:**
```bash
# 1. Clear browser data/use incognito
# 2. Login with MFA-enabled account
# 3. Should show 6-digit input immediately
# 4. Check SMS for code
# 5. Enter code → should login successfully
```

### 3. Existing User with MFA - Trusted Device
**Expected Flow:**
1. User logs in from trusted device (< 30 days)
2. Password accepted → direct login (skip MFA)

**Test Steps:**
```bash
# 1. Login on device used within 30 days
# 2. Should skip MFA challenge entirely
```

### 4. MFA Settings Management
**Expected Flow:**
1. Navigate to `/settings/security`
2. See current MFA status
3. Can view trusted devices
4. Can revoke device access
5. Can update phone number
6. Can disable MFA

**Test Steps:**
```bash
# 1. Go to /settings/security
# 2. Toggle MFA on/off
# 3. Update phone number
# 4. View trusted devices list
# 5. Revoke a device → test re-auth needed
```

## 🐛 Common Issues & Debugging

### SMS Not Received
1. Check Twilio console logs
2. Verify phone number format (+1XXXXXXXXXX)
3. Check Twilio balance
4. Verify Messaging Service configuration

### Code Verification Fails
1. Ensure code is entered within 5 minutes
2. Check for typos in 6-digit input
3. Verify factor_id matches in API calls
4. Check Supabase Auth logs

### Database Errors
```sql
-- Check if MFA tables exist
SELECT table_name FROM information_schema.tables 
WHERE table_name LIKE 'user_%fa%';

-- Check MFA settings for user
SELECT * FROM user_mfa_settings WHERE user_id = 'user-uuid';

-- Check trusted devices
SELECT * FROM user_trusted_devices WHERE user_id = 'user-uuid';
```

### API Errors
- Check `/api/mfa/settings` endpoint returns user MFA status
- Verify JWT tokens are passed correctly
- Check CORS settings for MFA endpoints

## 🔧 Development Testing

### Backend API Testing
```bash
# Test MFA enrollment
curl -X POST /api/mfa/enroll \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+15555555555"}'

# Test challenge creation  
curl -X POST /api/mfa/challenge \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user-uuid"}'
```

### Frontend Component Testing
- OTPInput: Paste functionality, auto-advance, resend timer
- MFAEnrollmentModal: Phone validation, country codes
- MFALoginFlow: Error handling, loading states
- MFASettingsPage: Device management, toggle switches

## ✅ Success Criteria

### User Experience
- [ ] Smooth 6-digit code entry (auto-advance, mobile keyboard)
- [ ] Clear error messages for invalid codes
- [ ] 30-second resend timer works
- [ ] Remember device reduces auth friction
- [ ] Settings page is intuitive

### Security
- [ ] Device tokens are cryptographically secure
- [ ] Expired devices require re-authentication
- [ ] Backup codes work for account recovery
- [ ] No sensitive data in browser storage
- [ ] Rate limiting prevents SMS abuse

### Performance
- [ ] SMS delivery within 30 seconds
- [ ] Code verification responds quickly
- [ ] Trusted device check is fast
- [ ] Database queries are optimized

## 🚀 Production Deployment Checklist

- [ ] Twilio production credentials configured
- [ ] Rate limiting implemented (5 SMS/hour per user)
- [ ] Monitoring for failed SMS deliveries
- [ ] Backup codes secure generation
- [ ] Device cleanup job scheduled (expired tokens)
- [ ] User education materials ready
- [ ] Support team trained on 2FA issues

## 📊 Metrics to Monitor

### Usage
- MFA enrollment rate (target: >80% of password logins)
- Device trust usage (should reduce SMS by ~90%)
- Settings page engagement

### Support
- 2FA-related support tickets
- SMS delivery failures
- Code verification failures

### Security
- Failed MFA attempts per user
- Device token usage patterns
- Backup code usage frequency

---
**Note:** Test thoroughly in staging before production deployment. SMS costs ~$0.0075 per authentication.