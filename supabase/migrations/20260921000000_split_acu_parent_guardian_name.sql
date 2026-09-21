-- Migration: Split ACU's combined parent/guardian name field
-- Description: Replaces `parent_guardian_name` with `parent_guardian_first_name`
--              and `parent_guardian_last_name` in Abilene Christian University's
--              card_fields, keeping the original position in the field order.
-- Date: 2026-09-21
--
-- ACU asked for the parent name to arrive as two columns instead of one. The
-- school is on vision-only extraction, where the prompt's field list is built
-- verbatim from the enabled entries in card_fields (see
-- app/core/streamlined_prompt.py::_build_field_list). Splitting the field here
-- therefore splits it everywhere downstream at once: the model extracts two
-- values, the review modal renders two inputs the reviewer can correct, and
-- both the CSV download and the Slate/SFTP export produce two columns. No
-- application code has to special-case the field.
--
-- Cards scanned before this migration keep the combined `parent_guardian_name`
-- in their stored data. Both export paths fall back to splitting that value so
-- historical cards still fill the two columns; their stored data is left
-- untouched.
--
-- Idempotent: re-running after the split is a no-op.

DO $$
DECLARE
    school_record RECORD;
    updated_fields JSONB := '[]'::jsonb;
    field JSONB;
    has_combined BOOLEAN := FALSE;
    has_split BOOLEAN := FALSE;
    suggestions JSONB;
BEGIN
    SELECT * INTO school_record
    FROM schools
    WHERE name = 'Abilene Christian University'
    LIMIT 1;

    IF school_record IS NULL THEN
        RAISE NOTICE 'Abilene Christian University not found - skipping migration';
        RETURN;
    END IF;

    SELECT EXISTS (
        SELECT 1 FROM jsonb_array_elements(COALESCE(school_record.card_fields, '[]'::jsonb)) f
        WHERE f->>'key' = 'parent_guardian_name'
    ) INTO has_combined;

    SELECT EXISTS (
        SELECT 1 FROM jsonb_array_elements(COALESCE(school_record.card_fields, '[]'::jsonb)) f
        WHERE f->>'key' = 'parent_guardian_first_name'
    ) INTO has_split;

    IF has_split THEN
        RAISE NOTICE 'ACU parent name is already split - skipping migration';
        RETURN;
    END IF;

    IF NOT has_combined THEN
        RAISE NOTICE 'ACU has no parent_guardian_name field configured - skipping migration';
        RETURN;
    END IF;

    -- Rebuild card_fields in order, expanding the combined field into two.
    -- The replacements inherit the original field's enabled/required settings
    -- so the migration does not quietly turn the field on or make it required.
    FOR field IN
        SELECT t.value
        FROM jsonb_array_elements(school_record.card_fields) WITH ORDINALITY AS t(value, ord)
        ORDER BY t.ord
    LOOP
        IF field->>'key' = 'parent_guardian_name' THEN
            updated_fields := updated_fields
                || jsonb_build_object(
                    'key', 'parent_guardian_first_name',
                    'label', 'Parent Guardian First Name',
                    'enabled', COALESCE(field->'enabled', 'true'::jsonb),
                    'required', COALESCE(field->'required', 'false'::jsonb),
                    'field_type', 'text'
                )
                || jsonb_build_object(
                    'key', 'parent_guardian_last_name',
                    'label', 'Parent Guardian Last Name',
                    'enabled', COALESCE(field->'enabled', 'true'::jsonb),
                    'required', COALESCE(field->'required', 'false'::jsonb),
                    'field_type', 'text'
                );
        ELSE
            updated_fields := updated_fields || field;
        END IF;
    END LOOP;

    -- The vision model had already discovered parent_guardian_first_name on some
    -- cards, so drop the now-configured keys from the suggestions banner.
    SELECT COALESCE(jsonb_agg(t.value ORDER BY t.ord), '[]'::jsonb) INTO suggestions
    FROM jsonb_array_elements(COALESCE(school_record.suggested_card_fields, '[]'::jsonb))
        WITH ORDINALITY AS t(value, ord)
    WHERE t.value->>'key' NOT IN ('parent_guardian_first_name', 'parent_guardian_last_name');

    UPDATE schools
    SET
        card_fields = updated_fields,
        suggested_card_fields = suggestions,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = school_record.id;

    RAISE NOTICE 'Split parent_guardian_name for ACU: % fields before, % after',
        jsonb_array_length(school_record.card_fields),
        jsonb_array_length(updated_fields);
END $$;
