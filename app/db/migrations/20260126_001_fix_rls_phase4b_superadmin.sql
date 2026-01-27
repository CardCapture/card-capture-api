-- ============================================
-- Migration: Fix RLS Policies Phase 4B - SuperAdmin Access
-- Author: CardCapture Team
-- Date: 2026-01-26
-- Description: Add SuperAdmin bypass to crm_events and add missing DELETE policy
-- Risk: LOW - Adds access for SuperAdmins, doesn't remove any security
-- Rollback: 20260126_001_rollback_rls_phase4b_superadmin.sql
--
-- TESTING: Apply to dev project (ftlweumoajawitlszpqx) FIRST
-- ============================================

BEGIN;

-- ============================================
-- 1. crm_events - Add SuperAdmin bypass to all policies
-- SuperAdmins (users with school_id IS NULL) need cross-tenant access
-- ============================================

-- Drop existing policies
DROP POLICY IF EXISTS "crm_events_school_select" ON public.crm_events;
DROP POLICY IF EXISTS "crm_events_school_insert" ON public.crm_events;
DROP POLICY IF EXISTS "crm_events_school_update" ON public.crm_events;
DROP POLICY IF EXISTS "crm_events_school_delete" ON public.crm_events;

-- Recreate with SuperAdmin bypass
CREATE POLICY "crm_events_school_select" ON public.crm_events
    FOR SELECT
    USING (
        school_id IN (SELECT school_id FROM public.profiles WHERE id = auth.uid())
        OR public.is_superadmin(auth.uid())
    );

CREATE POLICY "crm_events_school_insert" ON public.crm_events
    FOR INSERT
    WITH CHECK (
        school_id IN (SELECT school_id FROM public.profiles WHERE id = auth.uid())
        OR public.is_superadmin(auth.uid())
    );

CREATE POLICY "crm_events_school_update" ON public.crm_events
    FOR UPDATE
    USING (
        school_id IN (SELECT school_id FROM public.profiles WHERE id = auth.uid())
        OR public.is_superadmin(auth.uid())
    )
    WITH CHECK (
        school_id IN (SELECT school_id FROM public.profiles WHERE id = auth.uid())
        OR public.is_superadmin(auth.uid())
    );

CREATE POLICY "crm_events_school_delete" ON public.crm_events
    FOR DELETE
    USING (
        school_id IN (SELECT school_id FROM public.profiles WHERE id = auth.uid())
        OR public.is_superadmin(auth.uid())
    );

-- ============================================
-- 2. extracted_data - Add missing DELETE policy
-- ============================================

CREATE POLICY "extracted_data_admin_delete" ON public.extracted_data
    FOR DELETE
    USING (
        EXISTS (
            SELECT 1 FROM public.profiles
            WHERE id = auth.uid()
            AND 'admin' = ANY(role)
        )
    );

-- ============================================
-- Verification
-- ============================================

DO $$
DECLARE
    crm_policy_count int;
    extracted_delete_exists boolean;
BEGIN
    -- Verify crm_events has 5 policies (4 school + 1 service_role)
    SELECT COUNT(*) INTO crm_policy_count
    FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'crm_events';

    IF crm_policy_count < 5 THEN
        RAISE WARNING 'crm_events should have 5 policies, found %', crm_policy_count;
    ELSE
        RAISE NOTICE 'SUCCESS: crm_events has % policies', crm_policy_count;
    END IF;

    -- Verify extracted_data has DELETE policy
    SELECT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
        AND tablename = 'extracted_data'
        AND cmd = 'DELETE'
    ) INTO extracted_delete_exists;

    IF NOT extracted_delete_exists THEN
        RAISE WARNING 'extracted_data still missing DELETE policy';
    ELSE
        RAISE NOTICE 'SUCCESS: extracted_data DELETE policy exists';
    END IF;
END $$;

COMMIT;
