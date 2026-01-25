-- ============================================
-- ROLLBACK Migration: Revert SuperAdmin Access Changes
-- Author: CardCapture Team
-- Date: 2026-01-26
-- Description: Removes SuperAdmin bypass from crm_events policies
-- ============================================

BEGIN;

-- ============================================
-- 1. crm_events - Remove SuperAdmin bypass
-- ============================================

DROP POLICY IF EXISTS "crm_events_school_select" ON public.crm_events;
DROP POLICY IF EXISTS "crm_events_school_insert" ON public.crm_events;
DROP POLICY IF EXISTS "crm_events_school_update" ON public.crm_events;
DROP POLICY IF EXISTS "crm_events_school_delete" ON public.crm_events;

-- Recreate without SuperAdmin bypass (original Phase 4 state)
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

-- ============================================
-- 2. extracted_data - Remove DELETE policy
-- ============================================

DROP POLICY IF EXISTS "extracted_data_admin_delete" ON public.extracted_data;

COMMIT;
