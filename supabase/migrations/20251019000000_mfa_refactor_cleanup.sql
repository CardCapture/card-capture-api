-- MFA Refactor: Add constraints, cleanup data, and create rate limiting table
-- This migration ensures data integrity and prevents future issues

-- Step 1: Clean up bad data - users with MFA enabled but no phone number
UPDATE public.user_mfa_settings
SET mfa_enabled = false,
    phone_verified = false,
    enrollment_completed_at = NULL
WHERE mfa_enabled = true
  AND (phone_number IS NULL OR phone_number = '');

-- Step 2: Create mfa_rate_limits table for rate limiting protection
CREATE TABLE IF NOT EXISTS public.mfa_rate_limits (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    attempt_type VARCHAR(50) NOT NULL, -- 'challenge', 'verify', 'enroll'
    attempt_count INTEGER NOT NULL DEFAULT 0,
    window_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, attempt_type)
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_mfa_rate_limits_user_id ON public.mfa_rate_limits(user_id);
CREATE INDEX IF NOT EXISTS idx_mfa_rate_limits_window_start ON public.mfa_rate_limits(window_start);

-- Enable Row Level Security
ALTER TABLE public.mfa_rate_limits ENABLE ROW LEVEL SECURITY;

-- Service role can manage all rate limits
CREATE POLICY "Service role can manage all rate limits" ON public.mfa_rate_limits
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- Step 3: Add CHECK constraint to prevent mfa_enabled=true without phone_number
-- First drop the constraint if it exists
ALTER TABLE public.user_mfa_settings
DROP CONSTRAINT IF EXISTS phone_required_when_mfa_enabled;

-- Add the constraint
ALTER TABLE public.user_mfa_settings
ADD CONSTRAINT phone_required_when_mfa_enabled
CHECK (
    NOT mfa_enabled OR
    (phone_number IS NOT NULL AND phone_number != '')
);

-- Step 4: Create function to clean up old rate limit records (older than 1 hour)
DROP FUNCTION IF EXISTS public.cleanup_old_rate_limits();

CREATE FUNCTION public.cleanup_old_rate_limits()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  DELETE FROM public.mfa_rate_limits
  WHERE window_start < NOW() - INTERVAL '1 hour';
END;
$$;

-- Step 5: Create trigger to update updated_at on mfa_rate_limits
DROP TRIGGER IF EXISTS update_mfa_rate_limits_updated_at ON public.mfa_rate_limits;

CREATE TRIGGER update_mfa_rate_limits_updated_at
  BEFORE UPDATE ON public.mfa_rate_limits
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at_column();

-- Step 6: Clean up expired trusted devices (housekeeping)
SELECT public.cleanup_expired_device_tokens();

-- Step 7: Add comments for documentation
COMMENT ON TABLE public.mfa_rate_limits IS 'Rate limiting for MFA operations to prevent brute force attacks';
COMMENT ON COLUMN public.mfa_rate_limits.attempt_type IS 'Type of MFA operation: challenge, verify, enroll';
COMMENT ON COLUMN public.mfa_rate_limits.attempt_count IS 'Number of attempts in current window';
COMMENT ON COLUMN public.mfa_rate_limits.window_start IS 'Start of the current rate limit window';
COMMENT ON CONSTRAINT phone_required_when_mfa_enabled ON public.user_mfa_settings IS 'Ensures users cannot have MFA enabled without a valid phone number';
