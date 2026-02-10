-- Add notification settings to schools table
-- This enables schools to receive hourly digest emails when events have new card scans

-- Add notification email and enabled flag to schools table
ALTER TABLE schools
ADD COLUMN IF NOT EXISTS notification_email TEXT,
ADD COLUMN IF NOT EXISTS notifications_enabled BOOLEAN DEFAULT false;

-- Add comment for documentation
COMMENT ON COLUMN schools.notification_email IS 'Email address to receive card scan notifications (e.g., admissions@school.edu)';
COMMENT ON COLUMN schools.notifications_enabled IS 'Whether to send hourly digest emails for new card scans';

-- Create index for efficient querying of schools with notifications enabled
CREATE INDEX IF NOT EXISTS idx_schools_notifications_enabled
ON schools(notifications_enabled)
WHERE notifications_enabled = true;

-- Create index for efficient querying of cards by school and creation time
-- This optimizes the hourly notification query
CREATE INDEX IF NOT EXISTS idx_reviewed_data_created_at_school
ON reviewed_data(school_id, created_at DESC)
WHERE created_at IS NOT NULL;
