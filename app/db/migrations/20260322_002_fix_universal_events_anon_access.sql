-- ============================================
-- Migration: Restrict universal_events SELECT to authenticated users
-- Author: CardCapture Team
-- Date: 2026-03-22
-- Description: Change universal_events SELECT policy from USING(true) to
--   require authenticated users. The public search endpoint still works
--   because the FastAPI backend uses the service_role key.
--   Currently, anon key returns organizer PII (names, .edu emails, phone numbers).
-- Risk: HIGH - Verify public search endpoint still works after applying
-- Rollback: 20260322_002_rollback_universal_events_anon_access.sql
--
-- APPLY TO: production (pkpcqmlswrwsefxqhfuf)
-- ============================================

BEGIN;

-- Drop existing overly-permissive SELECT policy
DROP POLICY IF EXISTS "Enable read access for all users" ON public.universal_events;
DROP POLICY IF EXISTS "universal_events_select" ON public.universal_events;

-- Create new policy: only authenticated users and service_role can SELECT
CREATE POLICY "universal_events_authenticated_select" ON public.universal_events
    FOR SELECT
    USING (
        auth.role() = 'authenticated'
        OR auth.role() = 'service_role'
    );

-- Verify: anon role should NOT be able to read
DO $$
DECLARE
    policy_rec RECORD;
BEGIN
    FOR policy_rec IN
        SELECT policyname, roles, qual
        FROM pg_policies
        WHERE schemaname = 'public'
        AND tablename = 'universal_events'
        AND cmd = 'SELECT'
    LOOP
        RAISE NOTICE 'Policy: % | roles: % | qual: %', policy_rec.policyname, policy_rec.roles, policy_rec.qual;
    END LOOP;
END $$;

COMMIT;
