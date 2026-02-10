-- Add CEEB code field and update source constraint for high_schools_directory table

-- Add ceeb_code column
ALTER TABLE high_schools_directory 
ADD COLUMN ceeb_code TEXT;

-- Update the source constraint to include 'ceeb'
ALTER TABLE high_schools_directory 
DROP CONSTRAINT high_schools_directory_source_check;

ALTER TABLE high_schools_directory 
ADD CONSTRAINT high_schools_directory_source_check 
CHECK (source IN ('public', 'private', 'ceeb'));

-- Create index on ceeb_code for fast lookups
CREATE INDEX IF NOT EXISTS idx_high_schools_ceeb_code 
    ON high_schools_directory(ceeb_code);

-- Update existing data to set ceeb_code from metadata if it exists
UPDATE high_schools_directory 
SET ceeb_code = metadata->>'ceeb_code'
WHERE metadata ? 'ceeb_code' AND ceeb_code IS NULL;