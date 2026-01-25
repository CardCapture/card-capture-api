-- ============================================
-- ROLLBACK Migration: Restore USING(true) RLS Policies
-- Author: CardCapture Team
-- Date: 2026-01-25
-- Description: EMERGENCY ONLY - Restores policies WITHOUT proper access controls
--
-- WARNING: This rollback REMOVES security protection!
-- Only use if the fix breaks critical functionality.
-- ============================================

BEGIN;

-- ============================================
-- 1. crm_events - Restore test policy (DANGEROUS)
-- ============================================

DROP POLICY IF EXISTS "crm_events_school_select" ON public.crm_events;
DROP POLICY IF EXISTS "crm_events_school_insert" ON public.crm_events;
DROP POLICY IF EXISTS "crm_events_school_update" ON public.crm_events;
DROP POLICY IF EXISTS "crm_events_school_delete" ON public.crm_events;
DROP POLICY IF EXISTS "crm_events_service_role" ON public.crm_events;

CREATE POLICY "Temporary allow all for testing" ON public.crm_events
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- ============================================
-- 2. events - Restore USING(true) policies
-- ============================================

CREATE POLICY "Enable insert for authenticated users" ON public.events
    FOR INSERT TO authenticated
    WITH CHECK (true);

CREATE POLICY "Enable update for authenticated users" ON public.events
    FOR UPDATE TO authenticated
    USING (true)
    WITH CHECK (true);

-- ============================================
-- 3. extracted_data - Restore USING(true) policies
-- ============================================

CREATE POLICY "Enable insert for authenticated users" ON public.extracted_data
    FOR INSERT TO authenticated
    WITH CHECK (true);

CREATE POLICY "Enable read access for authenticated users" ON public.extracted_data
    FOR SELECT TO authenticated
    USING (true);

CREATE POLICY "Enable update for authenticated users" ON public.extracted_data
    FOR UPDATE TO authenticated
    USING (true)
    WITH CHECK (true);

-- ============================================
-- 4. reviewed_data - Restore USING(true) policies
-- ============================================

CREATE POLICY "Enable insert for authenticated users" ON public.reviewed_data
    FOR INSERT TO authenticated
    WITH CHECK (true);

CREATE POLICY "Enable update for authenticated users" ON public.reviewed_data
    FOR UPDATE TO authenticated
    USING (true)
    WITH CHECK (true);

-- ============================================
-- 5. schools - Restore USING(true) policies
-- ============================================

CREATE POLICY "Allow authenticated users to insert schools" ON public.schools
    FOR INSERT TO authenticated
    WITH CHECK (true);

CREATE POLICY "Allow authenticated users to update schools" ON public.schools
    FOR UPDATE TO authenticated
    USING (true)
    WITH CHECK (true);

-- ============================================
-- 6. audit_log - Restore trigger policy
-- ============================================

DROP POLICY IF EXISTS "audit_log_insert_own" ON public.audit_log;

CREATE POLICY "Allow trigger inserts" ON public.audit_log
    FOR INSERT
    WITH CHECK (true);

-- ============================================
-- 7. profiles - Restore trigger policy
-- ============================================

DROP POLICY IF EXISTS "profiles_insert_own" ON public.profiles;

CREATE POLICY "Allow trigger inserts" ON public.profiles
    FOR INSERT TO authenticated
    WITH CHECK (true);

-- ============================================
-- Verification: Confirm rollback
-- ============================================

DO $$
BEGIN
    RAISE WARNING '================================================';
    RAISE WARNING 'ROLLBACK COMPLETE - SECURITY PROTECTION REMOVED!';
    RAISE WARNING 'RLS policies are now VULNERABLE to cross-tenant access';
    RAISE WARNING '================================================';
END $$;

COMMIT;
