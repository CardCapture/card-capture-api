-- Fix log_table_changes trigger to not break on CASCADE deletes.
-- When auth.users is deleted, CASCADE deletes the profile, which fires
-- this trigger. The INSERT into audit_log fails because audit_log.user_id
-- has a FK to profiles(id), and the profile is being deleted in the same
-- transaction. This caused Supabase Admin API to return 500 on user deletion.
-- Fix: skip audit logging for DELETE operations entirely.

CREATE OR REPLACE FUNCTION public.log_table_changes()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    -- Skip audit logging for DELETE operations triggered by CASCADE
    -- (e.g., when auth.users deletion cascades to profiles).
    -- The FK audit_log.user_id -> profiles.id would fail mid-cascade.
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;

    INSERT INTO public.audit_log (
        user_id,
        action_type,
        table_name,
        row_id,
        before_data,
        after_data
    )
    VALUES (
        auth.uid(),
        TG_OP,
        TG_TABLE_NAME,
        NEW.id,
        CASE
            WHEN TG_OP = 'UPDATE' THEN to_jsonb(OLD)
            ELSE NULL
        END,
        to_jsonb(NEW)
    );

    RETURN NEW;
END;
$$;
