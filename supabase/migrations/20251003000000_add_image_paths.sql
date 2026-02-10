-- Add image_path column to student_school_interactions table
-- This allows the UI to display the card image even for existing students
ALTER TABLE student_school_interactions
ADD COLUMN IF NOT EXISTS image_path TEXT;

-- Add image_url column to students table
-- This stores the original card image URL from the first capture
ALTER TABLE students
ADD COLUMN IF NOT EXISTS image_url TEXT;

-- Add comment to describe the purpose
COMMENT ON COLUMN student_school_interactions.image_path IS 'Path to the card image in storage for this specific interaction';
COMMENT ON COLUMN students.image_url IS 'URL of the original card image from first capture (for reference)';
