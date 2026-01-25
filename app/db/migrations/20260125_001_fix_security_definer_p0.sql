-- ============================================
-- Migration: Fix P0 SECURITY DEFINER Functions
-- Author: CardCapture Team
-- Date: 2026-01-25
-- Description: Add search_path protection to prevent function hijacking
-- Risk: LOW - Only adding security layer, not changing logic
-- Rollback: 20260125_001_rollback_security_definer_p0.sql
--
-- TESTING: Apply to dev project (ftlweumoajawitlszpqx) FIRST
-- ============================================

BEGIN;

-- ============================================
-- 1. is_admin(uuid) - Used in RLS policies
-- ============================================

CREATE OR REPLACE FUNCTION public.is_admin(user_id uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM public.profiles
        WHERE id = user_id
        AND 'admin' = ANY(role)
    );
END;
$$;

COMMENT ON FUNCTION public.is_admin(uuid) IS
'Check if user has admin role. SECURITY DEFINER with search_path protection (2026-01-25).';

-- ============================================
-- 2. is_superadmin(uuid) - Used in RLS policies
-- ============================================

CREATE OR REPLACE FUNCTION public.is_superadmin(user_id uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    RETURN (SELECT school_id FROM public.profiles WHERE id = user_id) IS NULL;
END;
$$;

COMMENT ON FUNCTION public.is_superadmin(uuid) IS
'Check if user is superadmin (no school_id). SECURITY DEFINER with search_path protection (2026-01-25).';

-- ============================================
-- 3. has_role(uuid, text) - Generic role checker
-- ============================================

CREATE OR REPLACE FUNCTION public.has_role(user_id uuid, role_name text)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM public.profiles
        WHERE id = user_id
        AND role_name::user_role = ANY(role)
    );
END;
$$;

COMMENT ON FUNCTION public.has_role(uuid, text) IS
'Check if user has specific role. SECURITY DEFINER with search_path protection (2026-01-25).';

-- ============================================
-- 4. current_user_school_id() - Critical for tenant isolation
-- ============================================

CREATE OR REPLACE FUNCTION public.current_user_school_id()
RETURNS uuid
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT school_id FROM public.profiles WHERE id = auth.uid();
$$;

COMMENT ON FUNCTION public.current_user_school_id() IS
'Get current user school_id for RLS. SECURITY DEFINER with search_path protection (2026-01-25).';

-- ============================================
-- Verification: Ensure all P0 functions are protected
-- ============================================

DO $$
DECLARE
    func_name text;
    func_def text;
    vulnerable_count int := 0;
BEGIN
    FOR func_name, func_def IN
        SELECT p.proname, pg_get_functiondef(p.oid)
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'public'
        AND p.prosecdef = true
        AND p.proname IN ('is_admin', 'is_superadmin', 'has_role', 'current_user_school_id')
    LOOP
        IF func_def NOT LIKE '%search_path%' THEN
            RAISE WARNING 'Function % still vulnerable!', func_name;
            vulnerable_count := vulnerable_count + 1;
        ELSE
            RAISE NOTICE 'Function % is now protected', func_name;
        END IF;
    END LOOP;

    IF vulnerable_count > 0 THEN
        RAISE EXCEPTION 'Migration failed: % P0 functions still vulnerable', vulnerable_count;
    ELSE
        RAISE NOTICE 'SUCCESS: All 4 P0 functions now have search_path protection';
    END IF;
END $$;

COMMIT;
