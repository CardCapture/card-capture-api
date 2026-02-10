-- Add verified and source_method columns to students table
ALTER TABLE students 
ADD COLUMN IF NOT EXISTS verified BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS source_method TEXT CHECK (source_method IN ('magic_link', 'event_code', 'qr_self_signup', 'admin_import'));

-- Create event_codes table for registration gate
CREATE TABLE IF NOT EXISTS event_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code TEXT UNIQUE NOT NULL CHECK (LENGTH(code) = 6 AND code ~ '^[0-9]+$'),
    event_id UUID REFERENCES events(id) ON DELETE CASCADE,
    active BOOLEAN DEFAULT true,
    max_uses INTEGER DEFAULT 1000,
    current_uses INTEGER DEFAULT 0,
    valid_from TIMESTAMPTZ DEFAULT NOW(),
    valid_until TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '7 days'),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create form_sessions table for protected form access
CREATE TABLE IF NOT EXISTS form_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token TEXT UNIQUE NOT NULL,
    session_type TEXT NOT NULL CHECK (session_type IN ('magic_link', 'event_code')),
    email TEXT,
    event_code_id UUID REFERENCES event_codes(id) ON DELETE SET NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed BOOLEAN DEFAULT false,
    consumed_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create registration_attempts table for rate limiting
CREATE TABLE IF NOT EXISTS registration_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ip_address INET NOT NULL,
    email TEXT,
    attempt_type TEXT NOT NULL CHECK (attempt_type IN ('email_start', 'code_verify', 'form_submit')),
    success BOOLEAN DEFAULT false,
    error_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create registration_metrics table for analytics
CREATE TABLE IF NOT EXISTS registration_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES form_sessions(id) ON DELETE SET NULL,
    student_id UUID REFERENCES students(id) ON DELETE SET NULL,
    event_code_id UUID REFERENCES event_codes(id) ON DELETE SET NULL,
    funnel_step TEXT NOT NULL,
    source_method TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_event_codes_code ON event_codes(code) WHERE active = true;
CREATE INDEX IF NOT EXISTS idx_event_codes_event_id ON event_codes(event_id);
CREATE INDEX IF NOT EXISTS idx_form_sessions_token ON form_sessions(token) WHERE consumed = false;
CREATE INDEX IF NOT EXISTS idx_form_sessions_expires ON form_sessions(expires_at) WHERE consumed = false;
CREATE INDEX IF NOT EXISTS idx_registration_attempts_ip_created ON registration_attempts(ip_address, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_registration_attempts_email_created ON registration_attempts(email, created_at DESC) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_registration_metrics_session ON registration_metrics(session_id);
CREATE INDEX IF NOT EXISTS idx_registration_metrics_student ON registration_metrics(student_id);
CREATE INDEX IF NOT EXISTS idx_students_verified ON students(verified);
CREATE INDEX IF NOT EXISTS idx_students_email_verified ON students(email, verified);

-- RLS Policies for event_codes
ALTER TABLE event_codes ENABLE ROW LEVEL SECURITY;

-- Only authenticated users with appropriate roles can read event codes
CREATE POLICY "Event codes viewable by authenticated users" ON event_codes
    FOR SELECT
    USING (auth.role() = 'authenticated');

-- Only service role can modify event codes
CREATE POLICY "Event codes modifiable by service role" ON event_codes
    FOR ALL
    USING (auth.role() = 'service_role');

-- RLS Policies for form_sessions
ALTER TABLE form_sessions ENABLE ROW LEVEL SECURITY;

-- Only service role can access form sessions
CREATE POLICY "Form sessions only for service role" ON form_sessions
    FOR ALL
    USING (auth.role() = 'service_role');

-- RLS Policies for registration_attempts
ALTER TABLE registration_attempts ENABLE ROW LEVEL SECURITY;

-- Only service role can access registration attempts
CREATE POLICY "Registration attempts only for service role" ON registration_attempts
    FOR ALL
    USING (auth.role() = 'service_role');

-- RLS Policies for registration_metrics
ALTER TABLE registration_metrics ENABLE ROW LEVEL SECURITY;

-- Service role and authenticated users can read metrics
CREATE POLICY "Registration metrics readable by authenticated" ON registration_metrics
    FOR SELECT
    USING (auth.role() IN ('authenticated', 'service_role'));

-- Only service role can write metrics
CREATE POLICY "Registration metrics writable by service role" ON registration_metrics
    FOR INSERT
    WITH CHECK (auth.role() = 'service_role');

-- Function to generate a unique 6-digit event code
CREATE OR REPLACE FUNCTION generate_event_code()
RETURNS TEXT AS $$
DECLARE
    new_code TEXT;
    code_exists BOOLEAN;
BEGIN
    LOOP
        -- Generate random 6-digit code
        new_code := LPAD(FLOOR(RANDOM() * 1000000)::TEXT, 6, '0');
        
        -- Check if code already exists
        SELECT EXISTS(SELECT 1 FROM event_codes WHERE code = new_code) INTO code_exists;
        
        -- Exit loop if code is unique
        EXIT WHEN NOT code_exists;
    END LOOP;
    
    RETURN new_code;
END;
$$ LANGUAGE plpgsql;

-- Function to clean up expired form sessions
CREATE OR REPLACE FUNCTION cleanup_expired_sessions()
RETURNS void AS $$
BEGIN
    DELETE FROM form_sessions 
    WHERE expires_at < NOW() 
    AND consumed = false;
END;
$$ LANGUAGE plpgsql;

-- Updated timestamp trigger
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_event_codes_updated_at BEFORE UPDATE ON event_codes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();