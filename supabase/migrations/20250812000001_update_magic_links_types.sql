-- Update magic_links table to support new registration types
ALTER TABLE magic_links 
DROP CONSTRAINT magic_links_type_check;

-- Add updated constraint with new types
ALTER TABLE magic_links 
ADD CONSTRAINT magic_links_type_check 
CHECK (type IN ('password_reset', 'invite', 'registration', 'email_verification'));