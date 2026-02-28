-- SMS Registration Support
-- Adds phone column to registration_attempts for SMS rate limiting,
-- updates attempt_type constraint, and adds index for phone-based queries.

-- Add phone column (nullable) for SMS-based rate limiting
ALTER TABLE registration_attempts ADD COLUMN IF NOT EXISTS phone TEXT;

-- Drop existing attempt_type constraint and recreate with sms_start
ALTER TABLE registration_attempts DROP CONSTRAINT IF EXISTS registration_attempts_attempt_type_check;
ALTER TABLE registration_attempts ADD CONSTRAINT registration_attempts_attempt_type_check
    CHECK (attempt_type IN ('email_start', 'code_verify', 'form_submit', 'resend_verification', 'sms_start'));

-- Update form_sessions session_type constraint to include sms_link
ALTER TABLE form_sessions DROP CONSTRAINT IF EXISTS form_sessions_session_type_check;
ALTER TABLE form_sessions ADD CONSTRAINT form_sessions_session_type_check
    CHECK (session_type IN ('magic_link', 'event_code', 'sms_link'));

-- Index for phone-based rate limiting queries
CREATE INDEX IF NOT EXISTS idx_registration_attempts_phone_created
    ON registration_attempts (phone, created_at DESC)
    WHERE phone IS NOT NULL;
