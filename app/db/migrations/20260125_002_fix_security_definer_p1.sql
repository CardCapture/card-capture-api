-- ============================================
-- Migration: Fix P1 SECURITY DEFINER Functions
-- Author: CardCapture Team
-- Date: 2026-01-25
-- Description: Add search_path protection to prevent function hijacking
-- Risk: LOW - Only adding security layer, not changing logic
-- Rollback: 20260125_002_rollback_security_definer_p1.sql
--
-- TESTING: Apply to dev project (ftlweumoajawitlszpqx) FIRST
-- ============================================

BEGIN;

-- ============================================
-- 1. handle_new_user() - Auth trigger function
-- ============================================

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
  INSERT INTO public.profiles (id, email, first_name, last_name, school_id)
  VALUES (
    new.id,
    new.email,
    COALESCE(new.raw_user_meta_data->>'first_name', ''),
    COALESCE(new.raw_user_meta_data->>'last_name', ''),
    CASE
      WHEN new.raw_user_meta_data->>'school_id' = '' THEN NULL
      ELSE (new.raw_user_meta_data->>'school_id')::uuid
    END
  );
  RETURN new;
END;
$function$;

COMMENT ON FUNCTION public.handle_new_user() IS
'Auth trigger: creates profile for new users. SECURITY DEFINER with search_path protection (2026-01-25).';

-- ============================================
-- 2. has_event_access(uuid, uuid) - Access control
-- ============================================

CREATE OR REPLACE FUNCTION public.has_event_access(p_user_id uuid, p_universal_event_id uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
    -- Check for completed purchase
    IF EXISTS (
        SELECT 1 FROM public.event_purchases
        WHERE user_id = p_user_id
        AND universal_event_id = p_universal_event_id
        AND status = 'completed'
    ) THEN
        RETURN TRUE;
    END IF;

    -- Check if user's school has legacy unlimited access
    IF EXISTS (
        SELECT 1 FROM public.profiles p
        JOIN public.schools s ON s.id = p.school_id
        WHERE p.id = p_user_id
        AND s.is_legacy_unlimited = TRUE
    ) THEN
        RETURN TRUE;
    END IF;

    -- Check if user's school has credits
    IF EXISTS (
        SELECT 1 FROM public.profiles p
        JOIN public.schools s ON s.id = p.school_id
        WHERE p.id = p_user_id
        AND s.credits_balance > 0
    ) THEN
        RETURN TRUE;
    END IF;

    RETURN FALSE;
END;
$function$;

COMMENT ON FUNCTION public.has_event_access(uuid, uuid) IS
'Check if user has access to event. SECURITY DEFINER with search_path protection (2026-01-25).';

-- ============================================
-- 3. invite_school_admin(...) - Admin operations
-- ============================================

CREATE OR REPLACE FUNCTION public.invite_school_admin(
    invitee_email text,
    invitee_first_name text DEFAULT ''::text,
    invitee_last_name text DEFAULT ''::text,
    target_school_id uuid DEFAULT NULL::uuid
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
  invitation_id uuid;
BEGIN
  -- Check if current user is SuperAdmin
  IF NOT public.is_superadmin(auth.uid()) THEN
    RAISE EXCEPTION 'Only SuperAdmins can invite school administrators';
  END IF;

  -- Check if school exists
  IF target_school_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.schools WHERE id = target_school_id) THEN
    RAISE EXCEPTION 'School not found';
  END IF;

  -- For now, we'll just create a record to track the invitation
  -- In a real implementation, you'd integrate with an email service
  INSERT INTO public.audit_log (user_id, action, details)
  VALUES (
    auth.uid(),
    'invite_school_admin',
    jsonb_build_object(
      'invitee_email', invitee_email,
      'invitee_first_name', invitee_first_name,
      'invitee_last_name', invitee_last_name,
      'target_school_id', target_school_id
    )
  );
END;
$function$;

COMMENT ON FUNCTION public.invite_school_admin(text, text, text, uuid) IS
'Invite school admin (SuperAdmin only). SECURITY DEFINER with search_path protection (2026-01-25).';

-- ============================================
-- 4. invite_user(text, user_type) - User management
-- ============================================

CREATE OR REPLACE FUNCTION public.invite_user(
    invitee_email text,
    invited_user_type user_type DEFAULT 'user'::user_type
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
    -- Check if the current user is an admin
    IF NOT public.is_admin(auth.uid()) THEN
        RAISE EXCEPTION 'Only admins can invite users';
    END IF;

    -- The actual invitation will be handled by Supabase Auth UI
    -- This function is mainly for validation and future extensibility
    RETURN;
END;
$function$;

COMMENT ON FUNCTION public.invite_user(text, user_type) IS
'Invite user (Admin only). SECURITY DEFINER with search_path protection (2026-01-25).';

-- ============================================
-- 5. make_user_admin(uuid) - Privilege escalation
-- ============================================

CREATE OR REPLACE FUNCTION public.make_user_admin(target_user_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
    -- Check if the current user is an admin
    IF NOT public.is_admin(auth.uid()) THEN
        RAISE EXCEPTION 'Only admins can promote users to admin';
    END IF;

    -- Add admin role if not already present
    UPDATE public.profiles
    SET roles = array_append(roles, 'admin'::user_role)
    WHERE id = target_user_id
    AND NOT ('admin' = ANY(roles));
END;
$function$;

COMMENT ON FUNCTION public.make_user_admin(uuid) IS
'Promote user to admin. SECURITY DEFINER with search_path protection (2026-01-25).';

-- ============================================
-- 6. remove_admin_status(uuid) - Privilege management
-- ============================================

CREATE OR REPLACE FUNCTION public.remove_admin_status(target_user_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
BEGIN
    -- Check if the current user is an admin
    IF NOT public.is_admin(auth.uid()) THEN
        RAISE EXCEPTION 'Only admins can demote other admins';
    END IF;

    -- Prevent removing the last admin
    IF (SELECT count(*) FROM public.profiles WHERE 'admin' = ANY(roles)) <= 1 THEN
        RAISE EXCEPTION 'Cannot remove the last admin';
    END IF;

    -- Remove admin role
    UPDATE public.profiles
    SET roles = array_remove(roles, 'admin'::user_role)
    WHERE id = target_user_id;
END;
$function$;

COMMENT ON FUNCTION public.remove_admin_status(uuid) IS
'Demote admin to user. SECURITY DEFINER with search_path protection (2026-01-25).';

-- ============================================
-- 7. is_device_trusted(uuid, text) - Security feature
-- ============================================

CREATE OR REPLACE FUNCTION public.is_device_trusted(p_user_id uuid, p_device_token_hash text)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $function$
DECLARE
  v_is_trusted BOOLEAN;
BEGIN
  SELECT EXISTS (
    SELECT 1
    FROM public.trusted_devices
    WHERE user_id = p_user_id
      AND device_token_hash = p_device_token_hash
      AND expires_at > NOW()
  ) INTO v_is_trusted;

  -- Update last verified timestamp if device is trusted
  IF v_is_trusted THEN
    UPDATE public.trusted_devices
    SET updated_at = NOW()
    WHERE user_id = p_user_id
      AND device_token_hash = p_device_token_hash;
  END IF;

  RETURN v_is_trusted;
END;
$function$;

COMMENT ON FUNCTION public.is_device_trusted(uuid, text) IS
'Check if device is trusted. SECURITY DEFINER with search_path protection (2026-01-25).';

-- ============================================
-- Verification: Ensure all P1 functions are protected
-- ============================================

DO $$
DECLARE
    func_name text;
    func_def text;
    vulnerable_count int := 0;
    p1_functions text[] := ARRAY[
        'handle_new_user',
        'has_event_access',
        'invite_school_admin',
        'invite_user',
        'make_user_admin',
        'remove_admin_status',
        'is_device_trusted'
    ];
BEGIN
    FOR func_name, func_def IN
        SELECT p.proname, pg_get_functiondef(p.oid)
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'public'
        AND p.prosecdef = true
        AND p.proname = ANY(p1_functions)
    LOOP
        IF func_def NOT LIKE '%search_path%' THEN
            RAISE WARNING 'Function % still vulnerable!', func_name;
            vulnerable_count := vulnerable_count + 1;
        ELSE
            RAISE NOTICE 'Function % is now protected', func_name;
        END IF;
    END LOOP;

    IF vulnerable_count > 0 THEN
        RAISE EXCEPTION 'Migration failed: % P1 functions still vulnerable', vulnerable_count;
    ELSE
        RAISE NOTICE 'SUCCESS: All 7 P1 functions now have search_path protection';
    END IF;
END $$;

COMMIT;
