-- Update is_device_trusted function to use correct table name (trusted_devices instead of user_trusted_devices)
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
    FROM public.trusted_devices
    WHERE user_id = p_user_id
      AND device_token_hash = p_device_token_hash
      AND expires_at > NOW()
  ) INTO v_is_trusted;

  -- Update last verified timestamp if device is trusted
  IF v_is_trusted THEN
    UPDATE public.trusted_devices
    SET updated_at = NOW()
    WHERE user_id = p_user_id
      AND device_token_hash = p_device_token_hash;
  END IF;

  RETURN v_is_trusted;
END;
$$;

-- Drop and recreate cleanup function to ensure correct signature
DROP FUNCTION IF EXISTS public.cleanup_expired_device_tokens();

CREATE FUNCTION public.cleanup_expired_device_tokens()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  DELETE FROM public.trusted_devices
  WHERE expires_at < NOW();
END;
$$;
