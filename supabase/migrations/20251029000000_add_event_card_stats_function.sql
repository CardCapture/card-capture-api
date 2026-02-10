-- Create function to get event card statistics efficiently
-- This function aggregates card counts from both V1 (reviewed_data) and V2 (student_school_interactions) tables
-- by doing the aggregation in the database instead of fetching all rows to Python
CREATE OR REPLACE FUNCTION get_event_card_stats(event_ids UUID[])
RETURNS TABLE (
    event_id UUID,
    review_status TEXT,
    card_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    -- Combine V1 and V2 cards, then aggregate
    WITH combined_cards AS (
        -- V1 cards from reviewed_data (exclude deleted)
        SELECT
            rd.event_id,
            rd.review_status
        FROM reviewed_data rd
        WHERE rd.event_id = ANY(event_ids)
          AND rd.review_status != 'deleted'

        UNION ALL

        -- V2 cards from student_school_interactions (exclude archived)
        SELECT
            ssi.event_id,
            ssi.review_status
        FROM student_school_interactions ssi
        WHERE ssi.event_id = ANY(event_ids)
          AND ssi.review_status != 'archived'
    )
    SELECT
        cc.event_id,
        cc.review_status,
        COUNT(*)::BIGINT as card_count
    FROM combined_cards cc
    GROUP BY cc.event_id, cc.review_status
    ORDER BY cc.event_id, cc.review_status;
END;
$$ LANGUAGE plpgsql STABLE;

-- Add comment for documentation
COMMENT ON FUNCTION get_event_card_stats IS
'Aggregates card counts by event_id and review_status from both V1 (reviewed_data) and V2 (student_school_interactions) tables. Returns counts grouped by event and status, performing aggregation in database to avoid PostgREST row limits.';
