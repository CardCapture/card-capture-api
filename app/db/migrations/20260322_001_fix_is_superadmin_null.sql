-- ============================================
-- Migration: Fix is_superadmin() NULL handling
-- Author: CardCapture Team
-- Date: 2026-03-22
-- Description: Add NULL guard to is_superadmin() function.
--   When user_id is NULL (anonymous users), the current logic returns TRUE
--   because (SELECT school_id FROM profiles WHERE id = NULL) returns no rows,
--   which evaluates to NULL, and NULL IS NULL = TRUE.
--   This means every anonymous user passes the superadmin check.
-- Risk: CRITICAL - Apply to staging AND production immediately
-- Rollback: 20260322_001_rollback_fix_is_superadmin_null.sql
--
-- APPLY TO: staging (ftlweumoajawitlszpqx) AND production (pkpcqmlswrwsefxqhfuf)
-- ============================================

BEGIN;

CREATE OR REPLACE FUNCTION public.is_superadmin(user_id uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    -- NULL guard: anonymous/unauthenticated users are never superadmin
    IF user_id IS NULL THEN
        RETURN FALSE;
    END IF;

    -- A superadmin has no school_id in their profile (they operate across all schools)
    RETURN (SELECT school_id FROM public.profiles WHERE id = user_id) IS NULL;
END;
$$;

-- Verify the fix works correctly
DO $$
BEGIN
    -- NULL input should return FALSE (was returning TRUE before)
    IF public.is_superadmin(NULL) THEN
        RAISE EXCEPTION 'FAILED: is_superadmin(NULL) still returns TRUE';
    ELSE
        RAISE NOTICE 'PASS: is_superadmin(NULL) returns FALSE';
    END IF;
END $$;

COMMIT;
