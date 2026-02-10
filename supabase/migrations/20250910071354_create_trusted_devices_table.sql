-- Create trusted_devices table for MFA device trust
CREATE TABLE IF NOT EXISTS public.trusted_devices (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    device_token_hash VARCHAR(255) NOT NULL,
    device_name VARCHAR(255),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, device_token_hash)
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_trusted_devices_user_id ON public.trusted_devices(user_id);
CREATE INDEX IF NOT EXISTS idx_trusted_devices_token_hash ON public.trusted_devices(device_token_hash);

-- Enable Row Level Security
ALTER TABLE public.trusted_devices ENABLE ROW LEVEL SECURITY;

-- Drop existing policies if they exist
DROP POLICY IF EXISTS "Users can manage their own trusted devices" ON public.trusted_devices;
DROP POLICY IF EXISTS "Service role can manage all trusted devices" ON public.trusted_devices;

-- Create policy to allow users to manage their own trusted devices
CREATE POLICY "Users can manage their own trusted devices" ON public.trusted_devices
    FOR ALL 
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Create policy for service role to manage all trusted devices
CREATE POLICY "Service role can manage all trusted devices" ON public.trusted_devices
    FOR ALL 
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');