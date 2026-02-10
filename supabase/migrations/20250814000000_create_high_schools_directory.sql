-- Create high_schools_directory table for typeahead search
CREATE TABLE IF NOT EXISTS high_schools_directory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Core identifiers
    nces_id TEXT UNIQUE, -- National school ID (from NCESSCH column)
    name TEXT NOT NULL,
    
    -- Contact info
    phone TEXT,
    website TEXT,
    
    -- Mailing address
    address_line1 TEXT,
    address_line2 TEXT,
    address_line3 TEXT,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    zip_code TEXT,
    zip_plus4 TEXT,
    
    -- Location address (if different from mailing)
    location_address TEXT,
    location_city TEXT,
    location_state TEXT,
    location_zip TEXT,
    
    -- School info
    district_name TEXT,
    school_type TEXT,
    is_charter BOOLEAN DEFAULT false,
    level TEXT, -- High, Secondary, Elementary, etc.
    grades_offered TEXT[], -- ['9','10','11','12']
    
    -- Metadata
    source TEXT DEFAULT 'public' CHECK (source IN ('public', 'private')),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create majors_cip table for typeahead search
CREATE TABLE IF NOT EXISTS majors_cip (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cip_code TEXT UNIQUE NOT NULL,
    cip_title TEXT NOT NULL,
    cip_definition TEXT,
    cip_family TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for fast typeahead search
-- Using GIN indexes with trigram for fuzzy text search
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Full-text search indexes
CREATE INDEX IF NOT EXISTS idx_high_schools_name_gin 
    ON high_schools_directory USING gin(to_tsvector('english', name));

-- Trigram indexes for fuzzy matching
CREATE INDEX IF NOT EXISTS idx_high_schools_name_trgm 
    ON high_schools_directory USING gin(name gin_trgm_ops);

-- Regular indexes for filtering
CREATE INDEX IF NOT EXISTS idx_high_schools_state 
    ON high_schools_directory(state);
CREATE INDEX IF NOT EXISTS idx_high_schools_source 
    ON high_schools_directory(source);
CREATE INDEX IF NOT EXISTS idx_high_schools_level 
    ON high_schools_directory(level);

-- Majors indexes
CREATE INDEX IF NOT EXISTS idx_majors_title_gin 
    ON majors_cip USING gin(to_tsvector('english', cip_title));
CREATE INDEX IF NOT EXISTS idx_majors_title_trgm 
    ON majors_cip USING gin(cip_title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_majors_cip_code 
    ON majors_cip(cip_code);

-- RLS Policies
ALTER TABLE high_schools_directory ENABLE ROW LEVEL SECURITY;
ALTER TABLE majors_cip ENABLE ROW LEVEL SECURITY;

-- Allow authenticated users to read the directories
CREATE POLICY "High schools directory readable by authenticated users" 
    ON high_schools_directory FOR SELECT 
    USING (auth.role() = 'authenticated' OR auth.role() = 'anon');

CREATE POLICY "Majors directory readable by authenticated users" 
    ON majors_cip FOR SELECT 
    USING (auth.role() = 'authenticated' OR auth.role() = 'anon');

-- Only service role can modify the directories
CREATE POLICY "High schools directory modifiable by service role" 
    ON high_schools_directory FOR ALL 
    USING (auth.role() = 'service_role');

CREATE POLICY "Majors directory modifiable by service role" 
    ON majors_cip FOR ALL 
    USING (auth.role() = 'service_role');

-- Updated timestamp trigger
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply triggers
CREATE TRIGGER update_high_schools_directory_updated_at 
    BEFORE UPDATE ON high_schools_directory 
    FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();

CREATE TRIGGER update_majors_cip_updated_at 
    BEFORE UPDATE ON majors_cip 
    FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();