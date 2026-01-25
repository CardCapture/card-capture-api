-- ============================================
-- ROLLBACK Migration: Restore P1 SECURITY DEFINER Functions
-- Author: CardCapture Team
-- Date: 2026-01-25
-- Description: EMERGENCY ONLY - Restores functions WITHOUT search_path protection
--
-- WARNING: This rollback REMOVES security protection!
-- Only use if the fix breaks critical functionality.
-- ============================================

BEGIN;

-- ============================================
-- 1. handle_new_user() - Restore original (vulnerable)
-- ============================================

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
AS $function$
begin
  insert into public.profiles (id, email, first_name, last_name, school_id)
  values (
    new.id,
    new.email,
    COALESCE(new.raw_user_meta_data->>'first_name', ''),
    COALESCE(new.raw_user_meta_data->>'last_name', ''),
    CASE
      WHEN new.raw_user_meta_data->>'school_id' = '' THEN NULL
      ELSE (new.raw_user_meta_data->>'school_id')::uuid
    END
  );
  return new;
end;
$function$;

-- ============================================
-- 2. has_event_access(uuid, uuid) - Restore original (vulnerable)
-- ============================================

CREATE OR REPLACE FUNCTION public.has_event_access(p_user_id uuid, p_universal_event_id uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
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

-- ============================================
-- 3. invite_school_admin(...) - Restore original (vulnerable)
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

-- ============================================
-- 4. invite_user(text, user_type) - Restore original (vulnerable)
-- ============================================

CREATE OR REPLACE FUNCTION public.invite_user(
    invitee_email text,
    invited_user_type user_type DEFAULT 'user'::user_type
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $function$
begin
    -- Check if the current user is an admin
    if not is_admin(auth.uid()) then
        raise exception 'Only admins can invite users';
    end if;

    return;
end;
$function$;

-- ============================================
-- 5. make_user_admin(uuid) - Restore original (vulnerable)
-- ============================================

CREATE OR REPLACE FUNCTION public.make_user_admin(target_user_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $function$
begin
    -- Check if the current user is an admin
    if not is_admin(auth.uid()) then
        raise exception 'Only admins can promote users to admin';
    end if;

    -- Add admin role if not already present
    update profiles
    set roles = array_append(roles, 'admin'::user_role)
    where id = target_user_id
    and not ('admin' = ANY(roles));
end;
$function$;

-- ============================================
-- 6. remove_admin_status(uuid) - Restore original (vulnerable)
-- ============================================

CREATE OR REPLACE FUNCTION public.remove_admin_status(target_user_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $function$
begin
    -- Check if the current user is an admin
    if not is_admin(auth.uid()) then
        raise exception 'Only admins can demote other admins';
    end if;

    -- Prevent removing the last admin
    if (select count(*) from profiles where 'admin' = ANY(roles)) <= 1 then
        raise exception 'Cannot remove the last admin';
    end if;

    -- Remove admin role
    update profiles
    set roles = array_remove(roles, 'admin'::user_role)
    where id = target_user_id;
end;
$function$;

-- ============================================
-- 7. is_device_trusted(uuid, text) - Restore original (vulnerable)
-- ============================================

CREATE OR REPLACE FUNCTION public.is_device_trusted(p_user_id uuid, p_device_token_hash text)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
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

-- ============================================
-- Verification: Confirm rollback
-- ============================================

DO $$
BEGIN
    RAISE WARNING '================================================';
    RAISE WARNING 'ROLLBACK COMPLETE - SECURITY PROTECTION REMOVED!';
    RAISE WARNING 'P1 functions are now VULNERABLE to search_path attacks';
    RAISE WARNING '================================================';
END $$;

COMMIT;
