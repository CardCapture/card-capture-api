-- Create table for storing trusted device tokens (30-day remember me)
CREATE TABLE IF NOT EXISTS public.user_trusted_devices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  device_token_hash TEXT NOT NULL UNIQUE,
  device_name TEXT,
  device_fingerprint TEXT,
  user_agent TEXT,
  ip_address INET,
  last_verified_at TIMESTAMPTZ DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT user_trusted_devices_user_id_device_token_hash_key UNIQUE(user_id, device_token_hash)
);

-- Create table for tracking MFA enrollment status
CREATE TABLE IF NOT EXISTS public.user_mfa_settings (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  mfa_enabled BOOLEAN DEFAULT false,
  phone_verified BOOLEAN DEFAULT false,
  phone_number TEXT,
  enrollment_completed_at TIMESTAMPTZ,
  last_challenge_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create table for MFA bypass codes (backup codes)
CREATE TABLE IF NOT EXISTS public.user_mfa_backup_codes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  code_hash TEXT NOT NULL,
  used BOOLEAN DEFAULT false,
  used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT user_mfa_backup_codes_user_id_code_hash_key UNIQUE(user_id, code_hash)
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_user_trusted_devices_user_id ON public.user_trusted_devices(user_id);
CREATE INDEX IF NOT EXISTS idx_user_trusted_devices_expires_at ON public.user_trusted_devices(expires_at);
CREATE INDEX IF NOT EXISTS idx_user_trusted_devices_device_token_hash ON public.user_trusted_devices(device_token_hash);
CREATE INDEX IF NOT EXISTS idx_user_mfa_settings_user_id ON public.user_mfa_settings(user_id);
CREATE INDEX IF NOT EXISTS idx_user_mfa_backup_codes_user_id ON public.user_mfa_backup_codes(user_id);

-- Add RLS policies for user_trusted_devices
ALTER TABLE public.user_trusted_devices ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own trusted devices"
  ON public.user_trusted_devices
  FOR SELECT
  TO authenticated
  USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their own trusted devices"
  ON public.user_trusted_devices
  FOR DELETE
  TO authenticated
  USING (auth.uid() = user_id);

-- Service role can manage all trusted devices
CREATE POLICY "Service role can manage all trusted devices"
  ON public.user_trusted_devices
  FOR ALL
  TO service_role
  USING (true);

-- Add RLS policies for user_mfa_settings
ALTER TABLE public.user_mfa_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own MFA settings"
  ON public.user_mfa_settings
  FOR SELECT
  TO authenticated
  USING (auth.uid() = user_id);

CREATE POLICY "Users can update their own MFA settings"
  ON public.user_mfa_settings
  FOR UPDATE
  TO authenticated
  USING (auth.uid() = user_id);

-- Service role can manage all MFA settings
CREATE POLICY "Service role can manage all MFA settings"
  ON public.user_mfa_settings
  FOR ALL
  TO service_role
  USING (true);

-- Add RLS policies for user_mfa_backup_codes
ALTER TABLE public.user_mfa_backup_codes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own backup codes"
  ON public.user_mfa_backup_codes
  FOR SELECT
  TO authenticated
  USING (auth.uid() = user_id);

-- Service role can manage all backup codes
CREATE POLICY "Service role can manage all backup codes"
  ON public.user_mfa_backup_codes
  FOR ALL
  TO service_role
  USING (true);

-- Function to clean up expired device tokens
CREATE OR REPLACE FUNCTION public.cleanup_expired_device_tokens()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  DELETE FROM public.user_trusted_devices
  WHERE expires_at < NOW();
END;
$$;

-- Function to check if device is trusted
CREATE OR REPLACE FUNCTION public.is_device_trusted(
  p_user_id UUID,
  p_device_token_hash TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_is_trusted BOOLEAN;
BEGIN
  SELECT EXISTS (
    SELECT 1
    FROM public.user_trusted_devices
    WHERE user_id = p_user_id
      AND device_token_hash = p_device_token_hash
      AND expires_at > NOW()
  ) INTO v_is_trusted;
  
  -- Update last verified timestamp if device is trusted
  IF v_is_trusted THEN
    UPDATE public.user_trusted_devices
    SET last_verified_at = NOW()
    WHERE user_id = p_user_id
      AND device_token_hash = p_device_token_hash;
  END IF;
  
  RETURN v_is_trusted;
END;
$$;

-- Add trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_user_mfa_settings_updated_at
  BEFORE UPDATE ON public.user_mfa_settings
  FOR EACH ROW
  EXECUTE FUNCTION public.update_updated_at_column();