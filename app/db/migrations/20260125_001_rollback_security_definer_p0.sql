-- ============================================
-- ROLLBACK Migration: Restore P0 SECURITY DEFINER Functions
-- Author: CardCapture Team
-- Date: 2026-01-25
-- Description: EMERGENCY ONLY - Restores functions WITHOUT search_path protection
--
-- WARNING: This rollback REMOVES security protection!
-- Only use if the fix breaks critical functionality.
-- ============================================

BEGIN;

-- ============================================
-- 1. is_admin(uuid) - Restore original (vulnerable)
-- ============================================

CREATE OR REPLACE FUNCTION public.is_admin(user_id uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM profiles
        WHERE id = user_id
        AND 'admin' = ANY(role)
    );
END;
$$;

-- ============================================
-- 2. is_superadmin(uuid) - Restore original (vulnerable)
-- ============================================

CREATE OR REPLACE FUNCTION public.is_superadmin(user_id uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN (SELECT school_id FROM public.profiles WHERE id = user_id) IS NULL;
END;
$$;

-- ============================================
-- 3. has_role(uuid, text) - Restore original (vulnerable)
-- ============================================

CREATE OR REPLACE FUNCTION public.has_role(user_id uuid, role_name text)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM profiles
        WHERE id = user_id
        AND role_name::user_role = ANY(role)
    );
END;
$$;

-- ============================================
-- 4. current_user_school_id() - Restore original (vulnerable)
-- ============================================

CREATE OR REPLACE FUNCTION public.current_user_school_id()
RETURNS uuid
LANGUAGE sql
SECURITY DEFINER
AS $$
    SELECT school_id FROM public.profiles WHERE id = auth.uid();
$$;

-- ============================================
-- Verification: Confirm rollback
-- ============================================

DO $$
BEGIN
    RAISE WARNING '================================================';
    RAISE WARNING 'ROLLBACK COMPLETE - SECURITY PROTECTION REMOVED!';
    RAISE WARNING 'P0 functions are now VULNERABLE to search_path attacks';
    RAISE WARNING '================================================';
END $$;

COMMIT;
