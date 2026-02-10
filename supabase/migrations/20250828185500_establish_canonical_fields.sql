-- Migration: Establish canonical fields for all schools (FIXED VERSION)
-- Description: Ensures all schools use canonical field names and removes duplicates
-- Date: 2025-08-28
-- Author: System Migration

-- This migration establishes canonical field naming across all schools:
-- - Consolidates phone fields to 'cell' (removes: cell_phone, mobile, phone_number)
-- - Consolidates preferred name to 'preferred_first_name' (removes: preferred_name)
-- - Removes non-canonical fields like class_rank, students_in_class (unless specifically needed)

DO $$
DECLARE
    school_record RECORD;
    field_record RECORD;
    updated_fields JSONB;
    field_mapping JSONB;
    changes_made BOOLEAN;
    field_key TEXT;
    canonical_key TEXT;
    existing_canonical BOOLEAN;
BEGIN
    -- Define field mappings from non-canonical to canonical
    field_mapping := '{
        "cell_phone": "cell",
        "mobile": "cell",
        "phone_number": "cell",
        "cellphone": "cell",
        "preferred_name": "preferred_first_name",
        "dob": "date_of_birth",
        "birthdate": "date_of_birth",
        "birth_date": "date_of_birth",
        "birthday": "date_of_birth",
        "zip": "zip_code",
        "zipcode": "zip_code",
        "postal_code": "zip_code",
        "highschool": "high_school",
        "high_school_name": "high_school",
        "school_name": "high_school",
        "studenttype": "student_type",
        "student_category": "student_type",
        "entryterm": "entry_term",
        "start_term": "entry_term",
        "entry_semester": "entry_term"
    }'::jsonb;
    
    -- Process each school
    FOR school_record IN SELECT * FROM schools LOOP
        changes_made := FALSE;
        updated_fields := '[]'::jsonb;
        
        -- Process each field using a different approach
        FOR field_record IN 
            SELECT value as field_data 
            FROM jsonb_array_elements(school_record.card_fields) AS value
        LOOP
            field_key := field_record.field_data->>'key';
            canonical_key := field_mapping->>field_key;
            
            IF canonical_key IS NOT NULL THEN
                -- Check if canonical field already exists
                SELECT EXISTS(
                    SELECT 1 FROM jsonb_array_elements(school_record.card_fields) AS f 
                    WHERE f->>'key' = canonical_key
                ) INTO existing_canonical;
                
                IF existing_canonical THEN
                    -- Skip this duplicate field
                    RAISE NOTICE 'School %: Removing duplicate field % (canonical % exists)', 
                        school_record.name, field_key, canonical_key;
                    changes_made := TRUE;
                    CONTINUE;
                ELSE
                    -- Rename to canonical
                    field_record.field_data := jsonb_set(field_record.field_data, '{key}', to_jsonb(canonical_key));
                    RAISE NOTICE 'School %: Renaming field % to %', 
                        school_record.name, field_key, canonical_key;
                    changes_made := TRUE;
                END IF;
            END IF;
            
            -- Add field to updated list
            updated_fields := updated_fields || field_record.field_data;
        END LOOP;
        
        -- Update school if changes were made
        IF changes_made THEN
            UPDATE schools
            SET 
                card_fields = updated_fields,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = school_record.id;
            
            RAISE NOTICE 'Updated school %: % fields', school_record.name, jsonb_array_length(updated_fields);
        END IF;
    END LOOP;
END $$;

-- Add comment documenting the canonical field standardization
COMMENT ON TABLE schools IS 'Schools table with standardized canonical field names - migrated 2025-08-28';