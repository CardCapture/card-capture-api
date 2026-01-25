-- ============================================
-- Migration: Fix RLS Policies with USING(true)
-- Author: CardCapture Team
-- Date: 2026-01-25
-- Description: Replace dangerous USING(true) policies with proper access controls
-- Risk: MEDIUM - Changes access patterns, test thoroughly
-- Rollback: 20260125_004_rollback_rls_using_true.sql
--
-- TESTING: Apply to dev project (ftlweumoajawitlszpqx) FIRST
-- ============================================

BEGIN;

-- ============================================
-- 1. crm_events - CRITICAL: Remove test policy
-- ============================================

-- Drop the dangerous test policy
DROP POLICY IF EXISTS "Temporary allow all for testing" ON public.crm_events;

-- Add proper school-based policies
CREATE POLICY "crm_events_school_select" ON public.crm_events
    FOR SELECT
    USING (school_id IN (
        SELECT school_id FROM public.profiles WHERE id = auth.uid()
    ));

CREATE POLICY "crm_events_school_insert" ON public.crm_events
    FOR INSERT
    WITH CHECK (school_id IN (
        SELECT school_id FROM public.profiles WHERE id = auth.uid()
    ));

CREATE POLICY "crm_events_school_update" ON public.crm_events
    FOR UPDATE
    USING (school_id IN (
        SELECT school_id FROM public.profiles WHERE id = auth.uid()
    ))
    WITH CHECK (school_id IN (
        SELECT school_id FROM public.profiles WHERE id = auth.uid()
    ));

CREATE POLICY "crm_events_school_delete" ON public.crm_events
    FOR DELETE
    USING (school_id IN (
        SELECT school_id FROM public.profiles WHERE id = auth.uid()
    ));

CREATE POLICY "crm_events_service_role" ON public.crm_events
    FOR ALL
    USING (auth.role() = 'service_role');

-- ============================================
-- 2. events - Remove redundant USING(true) policies
-- (school_insert, school_select, school_update already exist)
-- ============================================

DROP POLICY IF EXISTS "Enable insert for authenticated users" ON public.events;
DROP POLICY IF EXISTS "Enable update for authenticated users" ON public.events;

-- ============================================
-- 3. extracted_data - Remove redundant USING(true) policies
-- (school_insert, school_select, school_update already exist)
-- ============================================

DROP POLICY IF EXISTS "Enable insert for authenticated users" ON public.extracted_data;
DROP POLICY IF EXISTS "Enable read access for authenticated users" ON public.extracted_data;
DROP POLICY IF EXISTS "Enable update for authenticated users" ON public.extracted_data;

-- ============================================
-- 4. reviewed_data - Remove redundant USING(true) policies
-- (school_insert, school_select, school_update already exist)
-- ============================================

DROP POLICY IF EXISTS "Enable insert for authenticated users" ON public.reviewed_data;
DROP POLICY IF EXISTS "Enable update for authenticated users" ON public.reviewed_data;

-- ============================================
-- 5. schools - Fix INSERT/UPDATE policies
-- Keep SELECT as-is (schools list is intentionally viewable)
-- ============================================

-- Drop overly permissive policies
DROP POLICY IF EXISTS "Allow authenticated users to insert schools" ON public.schools;
DROP POLICY IF EXISTS "Allow authenticated users to update schools" ON public.schools;

-- Note: Keeping these SELECT policies as schools list may need to be viewable:
-- - "Allow authenticated users to view schools"
-- - "Authenticated users can read schools"
-- And these proper policies already exist:
-- - "SuperAdmins can create schools"
-- - "SuperAdmins can update schools"

-- ============================================
-- 6. audit_log - Fix trigger insert policy
-- ============================================

DROP POLICY IF EXISTS "Allow trigger inserts" ON public.audit_log;

-- Allow inserts where user_id matches current user OR via service_role
CREATE POLICY "audit_log_insert_own" ON public.audit_log
    FOR INSERT
    WITH CHECK (
        user_id = auth.uid()
        OR auth.role() = 'service_role'
    );

-- ============================================
-- 7. profiles - Fix trigger insert policy
-- ============================================

DROP POLICY IF EXISTS "Allow trigger inserts" ON public.profiles;

-- Allow inserts where id matches current user (for auth trigger)
-- OR via service_role (for admin operations)
CREATE POLICY "profiles_insert_own" ON public.profiles
    FOR INSERT
    WITH CHECK (
        id = auth.uid()
        OR auth.role() = 'service_role'
    );

-- ============================================
-- Verification: Check for remaining USING(true) policies
-- ============================================

DO $$
DECLARE
    policy_rec RECORD;
    vulnerable_count int := 0;
    acceptable_tables text[] := ARRAY[
        'universal_events',  -- Intentionally public
        'user_mfa_backup_codes',  -- service_role only
        'user_mfa_settings'  -- service_role only
    ];
BEGIN
    FOR policy_rec IN
        SELECT tablename, policyname, cmd, roles, qual, with_check
        FROM pg_policies
        WHERE schemaname = 'public'
        AND (qual = 'true' OR with_check = 'true')
        AND NOT (tablename = ANY(acceptable_tables))
        AND NOT (roles::text LIKE '%service_role%' AND NOT roles::text LIKE '%public%')
    LOOP
        -- Check if it's a service_role only policy (acceptable)
        IF policy_rec.roles::text = '{service_role}' THEN
            RAISE NOTICE 'Acceptable service_role policy: %.%', policy_rec.tablename, policy_rec.policyname;
        -- Check if it's a schools SELECT policy (intentionally public)
        ELSIF policy_rec.tablename = 'schools' AND policy_rec.cmd = 'SELECT' THEN
            RAISE NOTICE 'Acceptable schools SELECT policy: %', policy_rec.policyname;
        ELSE
            RAISE WARNING 'VULNERABLE policy remains: %.% (%, roles=%, qual=%, with_check=%)',
                policy_rec.tablename, policy_rec.policyname, policy_rec.cmd,
                policy_rec.roles, policy_rec.qual, policy_rec.with_check;
            vulnerable_count := vulnerable_count + 1;
        END IF;
    END LOOP;

    IF vulnerable_count > 0 THEN
        RAISE WARNING 'Migration complete but % potentially vulnerable policies remain (may be intentional)', vulnerable_count;
    ELSE
        RAISE NOTICE 'SUCCESS: All critical USING(true) vulnerabilities fixed';
    END IF;
END $$;

COMMIT;
