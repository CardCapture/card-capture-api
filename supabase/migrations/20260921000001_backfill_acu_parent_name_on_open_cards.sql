-- Migration: Backfill split parent names on ACU's open cards
-- Description: For Abilene Christian University cards that are still in the
--              review queue, derive parent_guardian_first_name and
--              parent_guardian_last_name from the combined
--              parent_guardian_name already stored on the card.
-- Date: 2026-09-21
--
-- Companion to 20260921000000_split_acu_parent_guardian_name.sql. Once the
-- combined field is no longer configured, the review modal stops rendering it
-- and renders the two split fields instead. Cards already in the queue have no
-- values for those, so without this backfill a reviewer would see two empty
-- boxes for a parent name the card clearly shows.
--
-- Scope and safety:
--   * Only cards that still need review are touched. Exported and archived
--     cards are left exactly as they are, so nothing already delivered to the
--     customer changes.
--   * The change is additive. The combined parent_guardian_name stays on the
--     card, and any card that somehow already has a split value is skipped.
--   * The derived fields are marked as needing review, because a split of a
--     handwritten name is a guess the reviewer should confirm.
--
-- Skipping this migration is safe: both export paths fall back to splitting
-- the combined value, so the CSV is correct either way. This is about what the
-- reviewer sees on screen.
--
-- Idempotent: re-running skips cards that already have the split fields.

DO $$
DECLARE
    acu_id UUID;
    updated_count INTEGER := 0;
BEGIN
    SELECT id INTO acu_id
    FROM schools
    WHERE name = 'Abilene Christian University'
    LIMIT 1;

    IF acu_id IS NULL THEN
        RAISE NOTICE 'Abilene Christian University not found - skipping migration';
        RETURN;
    END IF;

    WITH open_cards AS (
        SELECT
            r.document_id,
            r.fields,
            trim(r.fields->'parent_guardian_name'->>'value') AS combined
        FROM reviewed_data r
        JOIN events e ON e.id = r.event_id
        WHERE e.school_id = acu_id
          AND r.review_status NOT IN ('exported', 'archived')
          AND COALESCE(trim(r.fields->'parent_guardian_name'->>'value'), '') <> ''
          AND NOT (r.fields ? 'parent_guardian_first_name')
          AND NOT (r.fields ? 'parent_guardian_last_name')
    ),
    split AS (
        SELECT
            document_id,
            fields,
            split_part(combined, ' ', 1) AS first_name,
            -- Everything after the first word, so multi-word surnames stay whole.
            NULLIF(trim(substring(combined FROM position(' ' IN combined) + 1)), '')
                AS last_name,
            combined
        FROM open_cards
    )
    UPDATE reviewed_data r
    SET fields = r.fields
        || jsonb_build_object(
            'parent_guardian_first_name', jsonb_build_object(
                'value', s.first_name,
                'source', 'derived_from_parent_guardian_name',
                'enabled', true,
                'required', false,
                'confidence', 0,
                'review_notes', 'Split from the combined parent/guardian name - please confirm',
                'requires_human_review', true,
                'reviewed', false
            ),
            'parent_guardian_last_name', jsonb_build_object(
                -- A single-word parent name leaves the last name blank.
                'value', COALESCE(CASE WHEN position(' ' IN s.combined) > 0
                                       THEN s.last_name END, ''),
                'source', 'derived_from_parent_guardian_name',
                'enabled', true,
                'required', false,
                'confidence', 0,
                'review_notes', 'Split from the combined parent/guardian name - please confirm',
                'requires_human_review', true,
                'reviewed', false
            )
        ),
        updated_at = CURRENT_TIMESTAMP
    FROM split s
    WHERE r.document_id = s.document_id;

    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RAISE NOTICE 'Backfilled split parent names on % open ACU card(s)', updated_count;
END $$;
