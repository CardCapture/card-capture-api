-- Migration: Fix ACU duplicate fields
-- Description: Removes duplicate fields (preferred_name, cell_phone) from ACU's configuration
-- Date: 2025-08-28
-- Author: System Migration

-- This migration removes duplicate field entries for Abilene Christian University:
-- 1. Removes 'preferred_name' (keeping 'preferred_first_name' as canonical)
-- 2. Removes 'cell_phone' (keeping 'cell' as canonical)

DO $$
DECLARE
    school_record RECORD;
    updated_fields JSONB;
    removed_count INTEGER;
BEGIN
    -- Get ACU's current configuration
    SELECT * INTO school_record 
    FROM schools 
    WHERE name = 'Abilene Christian University' 
    LIMIT 1;
    
    IF school_record IS NULL THEN
        RAISE NOTICE 'Abilene Christian University not found - skipping migration';
        RETURN;
    END IF;
    
    -- Count fields to be removed
    SELECT COUNT(*) INTO removed_count
    FROM jsonb_array_elements(school_record.card_fields) AS field
    WHERE field->>'key' IN ('preferred_name', 'cell_phone');
    
    IF removed_count = 0 THEN
        RAISE NOTICE 'No duplicate fields found for ACU - migration may have already been applied';
        RETURN;
    END IF;
    
    RAISE NOTICE 'Found ACU (ID: %) with % fields', school_record.id, jsonb_array_length(school_record.card_fields);
    
    -- Filter out the duplicate fields
    SELECT jsonb_agg(field ORDER BY ordinality) INTO updated_fields
    FROM jsonb_array_elements(school_record.card_fields) WITH ORDINALITY AS field(field, ordinality)
    WHERE field.field->>'key' NOT IN ('preferred_name', 'cell_phone');
    
    -- Update the school's card_fields
    UPDATE schools
    SET 
        card_fields = updated_fields,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = school_record.id;
    
    RAISE NOTICE 'Successfully removed % duplicate fields from ACU configuration', removed_count;
    RAISE NOTICE 'New field count: %', jsonb_array_length(updated_fields);
END $$;

-- Add a comment to document this migration
COMMENT ON TABLE schools IS 'Schools table with cleaned field configurations - duplicate fields removed for ACU on 2025-08-28';