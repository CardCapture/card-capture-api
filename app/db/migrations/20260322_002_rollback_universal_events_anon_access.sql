-- Rollback: Restore universal_events public read access
-- WARNING: This re-exposes organizer PII to anonymous users

BEGIN;

DROP POLICY IF EXISTS "universal_events_authenticated_select" ON public.universal_events;

CREATE POLICY "Enable read access for all users" ON public.universal_events
    FOR SELECT
    USING (true);

COMMIT;
