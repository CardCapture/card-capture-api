-- Rollback: Restore original is_superadmin() function (without NULL guard)
-- WARNING: This re-introduces the vulnerability where anon users are treated as superadmin

BEGIN;

CREATE OR REPLACE FUNCTION public.is_superadmin(user_id uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN (SELECT school_id FROM public.profiles WHERE id = user_id) IS NULL;
END;
$$;

COMMIT;
