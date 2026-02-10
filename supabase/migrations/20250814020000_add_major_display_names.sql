-- Add display_name column for student-friendly major names
ALTER TABLE majors_cip ADD COLUMN IF NOT EXISTS display_name TEXT;

-- Create index for search on display_name
CREATE INDEX IF NOT EXISTS idx_majors_cip_display_name_gin ON majors_cip USING gin(to_tsvector('english', display_name));

-- Populate display_name with student-friendly names for common majors
UPDATE majors_cip SET display_name = CASE
    -- Computer/Technology Fields
    WHEN cip_title ILIKE '%Computer Science%' AND cip_code = '="11.0701"' THEN 'Computer Science'
    WHEN cip_title ILIKE '%Computer Engineering%' AND cip_code = '="14.0901"' THEN 'Computer Engineering'
    WHEN cip_title ILIKE '%Information Technology%' AND cip_code = '="11.0103"' THEN 'Information Technology'
    WHEN cip_title ILIKE '%Computer Programming%' AND cip_code = '="11.0201"' THEN 'Computer Programming'
    WHEN cip_title ILIKE '%Software Engineering%' AND cip_code = '="14.0903"' THEN 'Software Engineering'
    WHEN cip_title ILIKE '%Cybersecurity%' OR cip_title ILIKE '%Information Systems Security%' THEN 'Cybersecurity'
    WHEN cip_title ILIKE '%Data Science%' OR cip_title ILIKE '%Data Analytics%' THEN 'Data Science'
    WHEN cip_title ILIKE '%Artificial Intelligence%' THEN 'Artificial Intelligence'
    WHEN cip_title ILIKE '%Web Development%' OR cip_title ILIKE '%Web/Multimedia Management%' THEN 'Web Development'
    
    -- Business Fields  
    WHEN cip_title ILIKE '%Business Administration%' AND cip_code = '="52.0201"' THEN 'Business Administration'
    WHEN cip_title ILIKE '%Accounting%' AND cip_code = '="52.0301"' THEN 'Accounting'
    WHEN cip_title ILIKE '%Marketing%' AND cip_code = '="52.1401"' THEN 'Marketing'
    WHEN cip_title ILIKE '%Finance%' AND cip_code = '="52.0801"' THEN 'Finance'
    WHEN cip_title ILIKE '%Management%' AND cip_code = '="52.1301"' THEN 'Management'
    WHEN cip_title ILIKE '%Economics%' AND cip_code = '="45.0601"' THEN 'Economics'
    
    -- STEM Fields
    WHEN cip_title ILIKE '%Biology%' AND cip_code = '="26.0101"' THEN 'Biology'
    WHEN cip_title ILIKE '%Chemistry%' AND cip_code = '="40.0501"' THEN 'Chemistry'
    WHEN cip_title ILIKE '%Physics%' AND cip_code = '="40.0801"' THEN 'Physics'
    WHEN cip_title ILIKE '%Mathematics%' AND cip_code = '="27.0101"' THEN 'Mathematics'
    WHEN cip_title ILIKE '%Engineering%' AND cip_title ILIKE '%Mechanical%' THEN 'Mechanical Engineering'
    WHEN cip_title ILIKE '%Engineering%' AND cip_title ILIKE '%Electrical%' THEN 'Electrical Engineering'
    WHEN cip_title ILIKE '%Engineering%' AND cip_title ILIKE '%Civil%' THEN 'Civil Engineering'
    WHEN cip_title ILIKE '%Engineering%' AND cip_title ILIKE '%Chemical%' THEN 'Chemical Engineering'
    
    -- Health Sciences
    WHEN cip_title ILIKE '%Nursing%' AND cip_code = '="51.3801"' THEN 'Nursing'
    WHEN cip_title ILIKE '%Psychology%' AND cip_code = '="42.0101"' THEN 'Psychology'
    WHEN cip_title ILIKE '%Pre-Med%' OR cip_title ILIKE '%Pre-Medicine%' THEN 'Pre-Medicine'
    WHEN cip_title ILIKE '%Kinesiology%' OR cip_title ILIKE '%Exercise Science%' THEN 'Kinesiology'
    
    -- Liberal Arts
    WHEN cip_title ILIKE '%English%' AND cip_code = '="23.0101"' THEN 'English'
    WHEN cip_title ILIKE '%History%' AND cip_code = '="54.0101"' THEN 'History'  
    WHEN cip_title ILIKE '%Political Science%' AND cip_code = '="45.1001"' THEN 'Political Science'
    WHEN cip_title ILIKE '%Sociology%' AND cip_code = '="45.1101"' THEN 'Sociology'
    WHEN cip_title ILIKE '%Communications%' AND cip_code = '="09.0101"' THEN 'Communications'
    WHEN cip_title ILIKE '%Journalism%' AND cip_code = '="09.0401"' THEN 'Journalism'
    
    -- Creative Fields
    WHEN cip_title ILIKE '%Graphic Design%' OR cip_title ILIKE '%Visual Communications%' THEN 'Graphic Design'
    WHEN cip_title ILIKE '%Art%' AND cip_code = '="50.0701"' THEN 'Art'
    WHEN cip_title ILIKE '%Music%' AND cip_code = '="50.0901"' THEN 'Music'
    WHEN cip_title ILIKE '%Theatre%' OR cip_title ILIKE '%Theater%' THEN 'Theatre'
    
    -- Education
    WHEN cip_title ILIKE '%Education%' AND cip_title ILIKE '%Elementary%' THEN 'Elementary Education'
    WHEN cip_title ILIKE '%Education%' AND cip_title ILIKE '%Secondary%' THEN 'Secondary Education'
    
    -- Other Popular Fields
    WHEN cip_title ILIKE '%Criminal Justice%' THEN 'Criminal Justice'
    WHEN cip_title ILIKE '%Social Work%' THEN 'Social Work'
    WHEN cip_title ILIKE '%Undecided%' OR cip_title ILIKE '%Undeclared%' THEN 'Undecided'
    
    -- Fallback - clean up the original title
    ELSE TRIM(REPLACE(REPLACE(REPLACE(cip_title, '.', ''), '="', ''), '"', ''))
END;

-- Set priority weights for common undergraduate majors (higher = more likely to appear first)
ALTER TABLE majors_cip ADD COLUMN IF NOT EXISTS search_priority INTEGER DEFAULT 1;

UPDATE majors_cip SET search_priority = CASE
    WHEN display_name IN (
        'Computer Science', 'Business Administration', 'Biology', 'Psychology', 'Engineering',
        'Nursing', 'Communications', 'Marketing', 'Accounting', 'English', 'History',
        'Criminal Justice', 'Education', 'Art', 'Music', 'Mathematics', 'Chemistry', 'Physics'
    ) THEN 10
    WHEN display_name IN (
        'Computer Engineering', 'Information Technology', 'Mechanical Engineering', 
        'Electrical Engineering', 'Finance', 'Management', 'Political Science', 'Sociology',
        'Journalism', 'Economics', 'Kinesiology', 'Social Work'
    ) THEN 8
    WHEN display_name IN (
        'Software Engineering', 'Cybersecurity', 'Data Science', 'Web Development',
        'Graphic Design', 'Theatre', 'Civil Engineering', 'Chemical Engineering'
    ) THEN 6
    ELSE 1
END;

-- Clean up any remaining problematic formatting
UPDATE majors_cip SET display_name = 
    REGEXP_REPLACE(
        REGEXP_REPLACE(display_name, '^[^A-Za-z]*', ''), 
        '[^A-Za-z0-9 /&,-]', '', 'g'
    )
WHERE display_name IS NOT NULL;