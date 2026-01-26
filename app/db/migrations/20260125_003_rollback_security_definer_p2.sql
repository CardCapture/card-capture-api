-- ============================================
-- ROLLBACK Migration: Restore P2 SECURITY DEFINER Functions
-- Author: CardCapture Team
-- Date: 2026-01-25
-- Description: EMERGENCY ONLY - Restores functions WITHOUT search_path protection
--
-- WARNING: This rollback REMOVES security protection!
-- Only use if the fix breaks critical functionality.
-- ============================================

BEGIN;

-- ============================================
-- 1. check_duplicate_job - Restore original (vulnerable)
-- ============================================

CREATE OR REPLACE FUNCTION public.check_duplicate_job(
    p_image_hash text,
    p_event_id uuid,
    p_window_minutes integer DEFAULT 5
)
RETURNS TABLE(is_duplicate boolean, existing_job_id uuid, existing_status text)
LANGUAGE plpgsql
SECURITY DEFINER
AS $function$
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

    IF NOT FOUND THEN
        RETURN QUERY SELECT FALSE::BOOLEAN, NULL::UUID, NULL::TEXT;
    END IF;
END;
$function$;

-- ============================================
-- 2. claim_next_job - Restore original (vulnerable)
-- ============================================

CREATE OR REPLACE FUNCTION public.claim_next_job(
    p_worker_id text,
    p_stale_minutes integer DEFAULT 5
)
RETURNS TABLE(id uuid, user_id uuid, school_id uuid, event_id uuid, file_url text, image_path text, status text, retry_count integer, created_at timestamp with time zone)
LANGUAGE plpgsql
SECURITY DEFINER
AS $function$
BEGIN
    UPDATE processing_jobs
    SET status = 'queued',
        worker_id = NULL,
        claimed_at = NULL,
        retry_count = COALESCE(retry_count, 0) + 1
    WHERE status = 'processing'
      AND claimed_at < NOW() - INTERVAL '1 minute' * p_stale_minutes
      AND COALESCE(retry_count, 0) < 3;

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
$function$;

-- ============================================
-- 3. cleanup_expired_device_tokens - Restore original (vulnerable)
-- ============================================

CREATE OR REPLACE FUNCTION public.cleanup_expired_device_tokens()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $function$
BEGIN
  DELETE FROM public.trusted_devices
  WHERE expires_at < NOW();
END;
$function$;

-- ============================================
-- 4. cleanup_expired_magic_links - Restore original (vulnerable)
-- ============================================

CREATE OR REPLACE FUNCTION public.cleanup_expired_magic_links()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
AS $function$
DECLARE
  deleted_count INTEGER;
BEGIN
  DELETE FROM magic_links
  WHERE (expires_at < NOW() - INTERVAL '7 days')
     OR (used = TRUE AND used_at < NOW() - INTERVAL '1 day');

  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RETURN deleted_count;
END;
$function$;

-- ============================================
-- 5. cleanup_old_rate_limits - Restore original (vulnerable)
-- ============================================

CREATE OR REPLACE FUNCTION public.cleanup_old_rate_limits()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $function$
BEGIN
  DELETE FROM public.mfa_rate_limits
  WHERE window_start < NOW() - INTERVAL '1 hour';
END;
$function$;

-- ============================================
-- 6. find_stuck_jobs - Restore original (vulnerable)
-- ============================================

CREATE OR REPLACE FUNCTION public.find_stuck_jobs(p_minutes integer DEFAULT 5)
RETURNS TABLE(id uuid, worker_id text, claimed_at timestamp with time zone, retry_count integer, file_url text)
LANGUAGE plpgsql
SECURITY DEFINER
AS $function$
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
$function$;

-- ============================================
-- 7. get_job_statistics - Restore original (vulnerable)
-- ============================================

CREATE OR REPLACE FUNCTION public.get_job_statistics(p_hours integer DEFAULT 1)
RETURNS TABLE(status text, count bigint, oldest_job timestamp with time zone, max_retries integer, avg_processing_time_seconds numeric)
LANGUAGE plpgsql
SECURITY DEFINER
AS $function$
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
$function$;

-- ============================================
-- 8. get_pending_link_requests_count - Restore original (vulnerable)
-- ============================================

CREATE OR REPLACE FUNCTION public.get_pending_link_requests_count(p_school_id uuid)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
AS $function$
BEGIN
    RETURN (
        SELECT COUNT(*)::INTEGER
        FROM public.account_link_requests
        WHERE target_school_id = p_school_id
        AND status = 'pending'
    );
END;
$function$;

-- ============================================
-- 9. get_user_activity - Restore original (vulnerable)
-- ============================================

CREATE OR REPLACE FUNCTION public.get_user_activity(
    target_user_id uuid,
    time_period interval DEFAULT '30 days'::interval
)
RETURNS TABLE(action_type text, action_count bigint)
LANGUAGE plpgsql
SECURITY DEFINER
AS $function$
BEGIN
    IF NOT (is_admin(auth.uid()) OR auth.uid() = target_user_id) THEN
        RAISE EXCEPTION 'Unauthorized to view user activity';
    END IF;

    RETURN QUERY
    SELECT
        ca.action_type,
        COUNT(*) as action_count
    FROM card_actions ca
    WHERE ca.user_id = target_user_id
    AND ca.created_at > NOW() - time_period
    GROUP BY ca.action_type;
END;
$function$;

-- ============================================
-- Verification: Confirm rollback
-- ============================================

DO $$
BEGIN
    RAISE WARNING '================================================';
    RAISE WARNING 'ROLLBACK COMPLETE - SECURITY PROTECTION REMOVED!';
    RAISE WARNING 'P2 functions are now VULNERABLE to search_path attacks';
    RAISE WARNING '================================================';
END $$;

COMMIT;
