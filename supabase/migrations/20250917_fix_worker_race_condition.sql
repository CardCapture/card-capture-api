-- Migration: Fix worker race condition and add job deduplication
-- Date: 2025-09-17
-- Purpose: Prevent duplicate processing when cards are scanned rapidly

-- 1. Add new columns to processing_jobs table
ALTER TABLE processing_jobs
ADD COLUMN IF NOT EXISTS worker_id TEXT,
ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS processing_completed_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS image_hash TEXT,
ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0;

-- 2. Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_processing_jobs_status_created
ON processing_jobs(status, created_at)
WHERE status IN ('queued', 'processing');

CREATE INDEX IF NOT EXISTS idx_processing_jobs_image_hash
ON processing_jobs(image_hash, event_id);

CREATE INDEX IF NOT EXISTS idx_processing_jobs_worker
ON processing_jobs(worker_id, status)
WHERE status = 'processing';

-- 3. Create atomic job claiming function
CREATE OR REPLACE FUNCTION claim_next_job(
    p_worker_id TEXT,
    p_stale_minutes INTEGER DEFAULT 5
)
RETURNS TABLE (
    id UUID,
    user_id UUID,
    school_id UUID,
    event_id UUID,
    file_url TEXT,
    image_path TEXT,
    status TEXT,
    retry_count INTEGER,
    created_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    -- First, reset any stale "processing" jobs back to "queued"
    UPDATE processing_jobs
    SET status = 'queued',
        worker_id = NULL,
        claimed_at = NULL,
        retry_count = COALESCE(retry_count, 0) + 1
    WHERE status = 'processing'
      AND claimed_at < NOW() - INTERVAL '1 minute' * p_stale_minutes
      AND COALESCE(retry_count, 0) < 3;

    -- Atomically claim the next available job
    RETURN QUERY
    UPDATE processing_jobs pj
    SET status = 'processing',
        worker_id = p_worker_id,
        claimed_at = NOW(),
        processing_started_at = NOW(),
        retry_count = COALESCE(pj.retry_count, 0)
    WHERE pj.id = (
        SELECT pj2.id
        FROM processing_jobs pj2
        WHERE pj2.status = 'queued'
          AND (pj2.retry_count IS NULL OR pj2.retry_count < 3)
        ORDER BY pj2.created_at
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING
        pj.id,
        pj.user_id,
        pj.school_id,
        pj.event_id,
        pj.file_url,
        pj.image_path,
        pj.status,
        pj.retry_count,
        pj.created_at;
END;
$$;

-- 4. Create duplicate detection function
CREATE OR REPLACE FUNCTION check_duplicate_job(
    p_image_hash TEXT,
    p_event_id UUID,
    p_window_minutes INTEGER DEFAULT 5
)
RETURNS TABLE (
    is_duplicate BOOLEAN,
    existing_job_id UUID,
    existing_status TEXT
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN QUERY
    SELECT
        TRUE as is_duplicate,
        pj.id as existing_job_id,
        pj.status as existing_status
    FROM processing_jobs pj
    WHERE pj.image_hash = p_image_hash
      AND pj.event_id = p_event_id
      AND pj.created_at > NOW() - INTERVAL '1 minute' * p_window_minutes
      AND pj.status IN ('queued', 'processing', 'complete')
    ORDER BY pj.created_at DESC
    LIMIT 1;

    -- Return false if no duplicate found
    IF NOT FOUND THEN
        RETURN QUERY SELECT FALSE::BOOLEAN, NULL::UUID, NULL::TEXT;
    END IF;
END;
$$;

-- 5. Create job statistics function for monitoring
CREATE OR REPLACE FUNCTION get_job_statistics(p_hours INTEGER DEFAULT 1)
RETURNS TABLE (
    status TEXT,
    count BIGINT,
    oldest_job TIMESTAMPTZ,
    max_retries INTEGER,
    avg_processing_time_seconds NUMERIC
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN QUERY
    SELECT
        pj.status,
        COUNT(*)::BIGINT as count,
        MIN(pj.created_at) as oldest_job,
        MAX(pj.retry_count) as max_retries,
        AVG(
            EXTRACT(EPOCH FROM (
                COALESCE(pj.processing_completed_at, NOW()) - pj.processing_started_at
            ))
        )::NUMERIC as avg_processing_time_seconds
    FROM processing_jobs pj
    WHERE pj.created_at > NOW() - INTERVAL '1 hour' * p_hours
    GROUP BY pj.status;
END;
$$;

-- 6. Create function to find stuck jobs
CREATE OR REPLACE FUNCTION find_stuck_jobs(p_minutes INTEGER DEFAULT 5)
RETURNS TABLE (
    id UUID,
    worker_id TEXT,
    claimed_at TIMESTAMPTZ,
    retry_count INTEGER,
    file_url TEXT
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN QUERY
    SELECT
        pj.id,
        pj.worker_id,
        pj.claimed_at,
        pj.retry_count,
        pj.file_url
    FROM processing_jobs pj
    WHERE pj.status = 'processing'
      AND pj.claimed_at < NOW() - INTERVAL '1 minute' * p_minutes
    ORDER BY pj.claimed_at;
END;
$$;

-- 7. Add new status values for better tracking
-- Note: Check if we need to update any constraints on status column
DO $$
BEGIN
    -- Add check constraint if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.check_constraints
        WHERE constraint_name = 'processing_jobs_status_check'
    ) THEN
        ALTER TABLE processing_jobs
        ADD CONSTRAINT processing_jobs_status_check
        CHECK (status IN (
            'queued',
            'processing',
            'complete',
            'failed',
            'permanently_failed',
            'skipped_duplicate',
            'cancelled'
        ));
    END IF;
END $$;

-- 8. Grant necessary permissions (adjust based on your roles)
GRANT EXECUTE ON FUNCTION claim_next_job TO authenticated;
GRANT EXECUTE ON FUNCTION check_duplicate_job TO authenticated;
GRANT EXECUTE ON FUNCTION get_job_statistics TO authenticated;
GRANT EXECUTE ON FUNCTION find_stuck_jobs TO authenticated;