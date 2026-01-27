

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;


CREATE EXTENSION IF NOT EXISTS "pg_cron" WITH SCHEMA "pg_catalog";






COMMENT ON SCHEMA "public" IS 'Updated with recruiter self-service tables (universal_events, event_purchases, account_link_requests) and profile/school extensions for self-signup flow';



CREATE EXTENSION IF NOT EXISTS "pg_net" WITH SCHEMA "public";






CREATE EXTENSION IF NOT EXISTS "pgsodium";






CREATE EXTENSION IF NOT EXISTS "http" WITH SCHEMA "public";






CREATE EXTENSION IF NOT EXISTS "pg_graphql" WITH SCHEMA "graphql";






CREATE EXTENSION IF NOT EXISTS "pg_stat_statements" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "pg_trgm" WITH SCHEMA "public";






CREATE EXTENSION IF NOT EXISTS "pgcrypto" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "pgjwt" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "supabase_vault" WITH SCHEMA "vault";






CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA "extensions";






CREATE TYPE "public"."card_orientation" AS ENUM (
    'auto',
    'portrait',
    'landscape'
);


ALTER TYPE "public"."card_orientation" OWNER TO "postgres";


CREATE TYPE "public"."user_role" AS ENUM (
    'admin',
    'recruiter',
    'reviewer'
);


ALTER TYPE "public"."user_role" OWNER TO "postgres";


CREATE TYPE "public"."user_type" AS ENUM (
    'admin',
    'user'
);


ALTER TYPE "public"."user_type" OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."check_duplicate_job"("p_image_hash" "text", "p_event_id" "uuid", "p_window_minutes" integer DEFAULT 5) RETURNS TABLE("is_duplicate" boolean, "existing_job_id" "uuid", "existing_status" "text")
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        TRUE as is_duplicate,
        pj.id as existing_job_id,
        pj.status as existing_status
    FROM public.processing_jobs pj
    WHERE pj.image_hash = p_image_hash
      AND pj.event_id = p_event_id
      AND pj.created_at > NOW() - INTERVAL '1 minute' * p_window_minutes
      AND pj.status IN ('queued', 'processing', 'complete')
    ORDER BY pj.created_at DESC
    LIMIT 1;

    IF NOT FOUND THEN
        RETURN QUERY SELECT FALSE::BOOLEAN, NULL::UUID, NULL::TEXT;
    END IF;
END;
$$;


ALTER FUNCTION "public"."check_duplicate_job"("p_image_hash" "text", "p_event_id" "uuid", "p_window_minutes" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."claim_next_job"("p_worker_id" "text", "p_stale_minutes" integer DEFAULT 5) RETURNS TABLE("id" "uuid", "user_id" "uuid", "school_id" "uuid", "event_id" "uuid", "file_url" "text", "image_path" "text", "status" "text", "retry_count" integer, "created_at" timestamp with time zone)
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
    UPDATE public.processing_jobs
    SET status = 'queued',
        worker_id = NULL,
        claimed_at = NULL,
        retry_count = COALESCE(retry_count, 0) + 1
    WHERE status = 'processing'
      AND claimed_at < NOW() - INTERVAL '1 minute' * p_stale_minutes
      AND COALESCE(retry_count, 0) < 3;

    RETURN QUERY
    UPDATE public.processing_jobs pj
    SET status = 'processing',
        worker_id = p_worker_id,
        claimed_at = NOW(),
        processing_started_at = NOW(),
        retry_count = COALESCE(pj.retry_count, 0)
    WHERE pj.id = (
        SELECT pj2.id
        FROM public.processing_jobs pj2
        WHERE pj2.status = 'queued'
          AND (pj2.retry_count IS NULL OR pj2.retry_count < 3)
        ORDER BY pj2.created_at
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING
        pj.id,
        pj.user_id,
        pj.school_id,
        pj.event_id,
        pj.file_url,
        pj.image_path,
        pj.status,
        pj.retry_count,
        pj.created_at;
END;
$$;


ALTER FUNCTION "public"."claim_next_job"("p_worker_id" "text", "p_stale_minutes" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."cleanup_expired_device_tokens"() RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
  DELETE FROM public.trusted_devices
  WHERE expires_at < NOW();
END;
$$;


ALTER FUNCTION "public"."cleanup_expired_device_tokens"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."cleanup_expired_magic_links"() RETURNS integer
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
DECLARE
  deleted_count INTEGER;
BEGIN
  DELETE FROM public.magic_links
  WHERE (expires_at < NOW() - INTERVAL '7 days')
     OR (used = TRUE AND used_at < NOW() - INTERVAL '1 day');

  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RETURN deleted_count;
END;
$$;


ALTER FUNCTION "public"."cleanup_expired_magic_links"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."cleanup_expired_sessions"() RETURNS "void"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    DELETE FROM form_sessions 
    WHERE expires_at < NOW() 
    AND consumed = false;
END;
$$;


ALTER FUNCTION "public"."cleanup_expired_sessions"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."cleanup_old_rate_limits"() RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
  DELETE FROM public.mfa_rate_limits
  WHERE window_start < NOW() - INTERVAL '1 hour';
END;
$$;


ALTER FUNCTION "public"."cleanup_old_rate_limits"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."current_user_school_id"() RETURNS "uuid"
    LANGUAGE "sql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
    SELECT school_id FROM public.profiles WHERE id = auth.uid();
$$;


ALTER FUNCTION "public"."current_user_school_id"() OWNER TO "postgres";


COMMENT ON FUNCTION "public"."current_user_school_id"() IS 'Get current user school_id for RLS. SECURITY DEFINER with search_path protection (2026-01-25).';



CREATE OR REPLACE FUNCTION "public"."find_stuck_jobs"("p_minutes" integer DEFAULT 5) RETURNS TABLE("id" "uuid", "worker_id" "text", "claimed_at" timestamp with time zone, "retry_count" integer, "file_url" "text")
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        pj.id,
        pj.worker_id,
        pj.claimed_at,
        pj.retry_count,
        pj.file_url
    FROM public.processing_jobs pj
    WHERE pj.status = 'processing'
      AND pj.claimed_at < NOW() - INTERVAL '1 minute' * p_minutes
    ORDER BY pj.claimed_at;
END;
$$;


ALTER FUNCTION "public"."find_stuck_jobs"("p_minutes" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."generate_event_code"() RETURNS "text"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    new_code TEXT;
    code_exists BOOLEAN;
BEGIN
    LOOP
        -- Generate random 6-digit code
        new_code := LPAD(FLOOR(RANDOM() * 1000000)::TEXT, 6, '0');
        
        -- Check if code already exists
        SELECT EXISTS(SELECT 1 FROM event_codes WHERE code = new_code) INTO code_exists;
        
        -- Exit loop if code is unique
        EXIT WHEN NOT code_exists;
    END LOOP;
    
    RETURN new_code;
END;
$$;


ALTER FUNCTION "public"."generate_event_code"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_event_card_stats"("event_ids" "uuid"[]) RETURNS TABLE("event_id" "uuid", "review_status" "text", "card_count" bigint)
    LANGUAGE "plpgsql" STABLE
    AS $$
BEGIN
    RETURN QUERY
    -- Combine V1 and V2 cards, then aggregate
    WITH combined_cards AS (
        -- V1 cards from reviewed_data (exclude deleted)
        SELECT
            rd.event_id,
            rd.review_status
        FROM reviewed_data rd
        WHERE rd.event_id = ANY(event_ids)
          AND rd.review_status != 'deleted'

        UNION ALL

        -- V2 cards from student_school_interactions (exclude archived)
        SELECT
            ssi.event_id,
            ssi.review_status
        FROM student_school_interactions ssi
        WHERE ssi.event_id = ANY(event_ids)
          AND ssi.review_status != 'archived'
    )
    SELECT
        cc.event_id,
        cc.review_status,
        COUNT(*)::BIGINT as card_count
    FROM combined_cards cc
    GROUP BY cc.event_id, cc.review_status
    ORDER BY cc.event_id, cc.review_status;
END;
$$;


ALTER FUNCTION "public"."get_event_card_stats"("event_ids" "uuid"[]) OWNER TO "postgres";


COMMENT ON FUNCTION "public"."get_event_card_stats"("event_ids" "uuid"[]) IS 'Aggregates card counts by event_id and review_status from both V1 (reviewed_data) and V2 (student_school_interactions) tables. Returns counts grouped by event and status, performing aggregation in database to avoid PostgREST row limits.';



CREATE OR REPLACE FUNCTION "public"."get_job_statistics"("p_hours" integer DEFAULT 1) RETURNS TABLE("status" "text", "count" bigint, "oldest_job" timestamp with time zone, "max_retries" integer, "avg_processing_time_seconds" numeric)
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        pj.status,
        COUNT(*)::BIGINT as count,
        MIN(pj.created_at) as oldest_job,
        MAX(pj.retry_count) as max_retries,
        AVG(
            EXTRACT(EPOCH FROM (
                COALESCE(pj.processing_completed_at, NOW()) - pj.processing_started_at
            ))
        )::NUMERIC as avg_processing_time_seconds
    FROM public.processing_jobs pj
    WHERE pj.created_at > NOW() - INTERVAL '1 hour' * p_hours
    GROUP BY pj.status;
END;
$$;


ALTER FUNCTION "public"."get_job_statistics"("p_hours" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_pending_link_requests_count"("p_school_id" "uuid") RETURNS integer
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
    RETURN (
        SELECT COUNT(*)::INTEGER
        FROM public.account_link_requests
        WHERE target_school_id = p_school_id
        AND status = 'pending'
    );
END;
$$;


ALTER FUNCTION "public"."get_pending_link_requests_count"("p_school_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."get_pending_link_requests_count"("p_school_id" "uuid") IS 'Get count of pending link requests for admin dashboard';



CREATE OR REPLACE FUNCTION "public"."get_user_activity"("target_user_id" "uuid", "time_period" interval DEFAULT '30 days'::interval) RETURNS TABLE("action_type" "text", "action_count" bigint)
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
    IF NOT (public.is_admin(auth.uid()) OR auth.uid() = target_user_id) THEN
        RAISE EXCEPTION 'Unauthorized to view user activity';
    END IF;

    RETURN QUERY
    SELECT
        ca.action_type,
        COUNT(*) as action_count
    FROM public.card_actions ca
    WHERE ca.user_id = target_user_id
    AND ca.created_at > NOW() - time_period
    GROUP BY ca.action_type;
END;
$$;


ALTER FUNCTION "public"."get_user_activity"("target_user_id" "uuid", "time_period" interval) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_user_mfa_factors"("p_user_id" "uuid") RETURNS TABLE("id" "uuid", "user_id" "uuid", "factor_type" "text", "status" "text", "friendly_name" "text", "phone" "text", "created_at" timestamp with time zone, "updated_at" timestamp with time zone)
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO 'auth', 'public', 'pg_temp'
    AS $$
BEGIN
    RETURN QUERY
    SELECT
        f.id,
        f.user_id,
        f.factor_type::TEXT,
        f.status::TEXT,
        f.friendly_name,
        f.phone,
        f.created_at,
        f.updated_at
    FROM auth.mfa_factors f
    WHERE f.user_id = p_user_id;
END;
$$;


ALTER FUNCTION "public"."get_user_mfa_factors"("p_user_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."get_user_mfa_factors"("p_user_id" "uuid") IS 'Returns MFA factors for a user from auth.mfa_factors table. Used to bypass /auth/v1/user endpoint issues.';



CREATE OR REPLACE FUNCTION "public"."handle_new_user"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
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
$$;


ALTER FUNCTION "public"."handle_new_user"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."handle_processing_jobs_insert"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$BEGIN
  PERFORM net.http_post(
    url     := 'https://ftlweumoajawitlszpqx.supabase.co/functions/v1/process-job-trigger',
    body    := jsonb_build_object('record', to_jsonb(NEW)),
    headers := jsonb_build_object(
      'Content-Type',  'application/json',
      'Authorization', 'Bearer ' || current_setting('app.settings.service_role_key', true)
    )
  );
  RETURN NEW;
END;$$;


ALTER FUNCTION "public"."handle_processing_jobs_insert"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."handle_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."handle_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."has_event_access"("p_user_id" "uuid", "p_universal_event_id" "uuid") RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.event_purchases
        WHERE user_id = p_user_id
        AND universal_event_id = p_universal_event_id
        AND status = 'completed'
    ) THEN
        RETURN TRUE;
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.profiles p
        JOIN public.schools s ON s.id = p.school_id
        WHERE p.id = p_user_id
        AND s.is_legacy_unlimited = TRUE
    ) THEN
        RETURN TRUE;
    END IF;

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
$$;


ALTER FUNCTION "public"."has_event_access"("p_user_id" "uuid", "p_universal_event_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."has_event_access"("p_user_id" "uuid", "p_universal_event_id" "uuid") IS 'Check if a user has access to a universal event (via purchase, legacy plan, or credits)';



CREATE OR REPLACE FUNCTION "public"."has_role"("user_id" "uuid", "role_name" "text") RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM public.profiles
        WHERE id = user_id
        AND role_name::user_role = ANY(role)
    );
END;
$$;


ALTER FUNCTION "public"."has_role"("user_id" "uuid", "role_name" "text") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."has_role"("user_id" "uuid", "role_name" "text") IS 'Check if user has specific role. SECURITY DEFINER with search_path protection (2026-01-25).';



CREATE OR REPLACE FUNCTION "public"."invite_school_admin"("invitee_email" "text", "invitee_first_name" "text" DEFAULT ''::"text", "invitee_last_name" "text" DEFAULT ''::"text", "target_school_id" "uuid" DEFAULT NULL::"uuid") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
DECLARE
  invitation_id uuid;
BEGIN
  IF NOT public.is_superadmin(auth.uid()) THEN
    RAISE EXCEPTION 'Only SuperAdmins can invite school administrators';
  END IF;

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
$$;


ALTER FUNCTION "public"."invite_school_admin"("invitee_email" "text", "invitee_first_name" "text", "invitee_last_name" "text", "target_school_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."invite_school_admin"("invitee_email" "text", "invitee_first_name" "text", "invitee_last_name" "text", "target_school_id" "uuid") IS 'Allows SuperAdmins to invite school administrators';



CREATE OR REPLACE FUNCTION "public"."invite_user"("invitee_email" "text", "invited_user_type" "public"."user_type" DEFAULT 'user'::"public"."user_type") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
    IF NOT public.is_admin(auth.uid()) THEN
        RAISE EXCEPTION 'Only admins can invite users';
    END IF;
    RETURN;
END;
$$;


ALTER FUNCTION "public"."invite_user"("invitee_email" "text", "invited_user_type" "public"."user_type") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."is_admin"("user_id" "uuid") RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM public.profiles
        WHERE id = user_id
        AND 'admin' = ANY(role)
    );
END;
$$;


ALTER FUNCTION "public"."is_admin"("user_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."is_admin"("user_id" "uuid") IS 'Check if user has admin role. SECURITY DEFINER with search_path protection (2026-01-25).';



CREATE OR REPLACE FUNCTION "public"."is_device_trusted"("p_user_id" "uuid", "p_device_token_hash" "text") RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
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

  IF v_is_trusted THEN
    UPDATE public.trusted_devices
    SET updated_at = NOW()
    WHERE user_id = p_user_id
      AND device_token_hash = p_device_token_hash;
  END IF;

  RETURN v_is_trusted;
END;
$$;


ALTER FUNCTION "public"."is_device_trusted"("p_user_id" "uuid", "p_device_token_hash" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."is_superadmin"("user_id" "uuid") RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
    RETURN (SELECT school_id FROM public.profiles WHERE id = user_id) IS NULL;
END;
$$;


ALTER FUNCTION "public"."is_superadmin"("user_id" "uuid") OWNER TO "postgres";


COMMENT ON FUNCTION "public"."is_superadmin"("user_id" "uuid") IS 'Check if user is superadmin (no school_id). SECURITY DEFINER with search_path protection (2026-01-25).';



CREATE OR REPLACE FUNCTION "public"."log_table_changes"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
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
        TG_OP, -- 'INSERT', 'UPDATE', or 'DELETE'
        TG_TABLE_NAME,
        CASE 
            WHEN TG_OP = 'DELETE' THEN OLD.id
            ELSE NEW.id
        END,
        CASE 
            WHEN TG_OP IN ('UPDATE', 'DELETE') THEN to_jsonb(OLD)
            ELSE NULL
        END,
        CASE 
            WHEN TG_OP IN ('INSERT', 'UPDATE') THEN to_jsonb(NEW)
            ELSE NULL
        END
    );
    
    RETURN CASE 
        WHEN TG_OP = 'DELETE' THEN OLD
        ELSE NEW
    END;
END;
$$;


ALTER FUNCTION "public"."log_table_changes"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."make_user_admin"("target_user_id" "uuid") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
    IF NOT public.is_admin(auth.uid()) THEN
        RAISE EXCEPTION 'Only admins can promote users to admin';
    END IF;

    UPDATE public.profiles
    SET roles = array_append(roles, 'admin'::user_role)
    WHERE id = target_user_id
    AND NOT ('admin' = ANY(roles));
END;
$$;


ALTER FUNCTION "public"."make_user_admin"("target_user_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."remove_admin_status"("target_user_id" "uuid") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    SET "search_path" TO ''
    AS $$
BEGIN
    IF NOT public.is_admin(auth.uid()) THEN
        RAISE EXCEPTION 'Only admins can demote other admins';
    END IF;

    IF (SELECT count(*) FROM public.profiles WHERE 'admin' = ANY(roles)) <= 1 THEN
        RAISE EXCEPTION 'Cannot remove the last admin';
    END IF;

    UPDATE public.profiles
    SET roles = array_remove(roles, 'admin'::user_role)
    WHERE id = target_user_id;
END;
$$;


ALTER FUNCTION "public"."remove_admin_status"("target_user_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_bulk_uploads_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_bulk_uploads_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_integration_credentials_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_integration_credentials_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_settings_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_settings_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_updated_at_column"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_updated_at_column"() OWNER TO "postgres";

SET default_tablespace = '';

SET default_table_access_method = "heap";


CREATE TABLE IF NOT EXISTS "public"."account_link_requests" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "requester_user_id" "uuid" NOT NULL,
    "target_school_id" "uuid" NOT NULL,
    "universal_event_id" "uuid" NOT NULL,
    "event_purchase_id" "uuid",
    "status" "text" DEFAULT 'pending'::"text",
    "requester_message" "text",
    "admin_notes" "text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "reviewed_at" timestamp with time zone,
    "reviewed_by" "uuid",
    "expires_at" timestamp with time zone DEFAULT ("now"() + '30 days'::interval),
    CONSTRAINT "account_link_requests_status_check" CHECK (("status" = ANY (ARRAY['pending'::"text", 'approved'::"text", 'rejected'::"text", 'expired'::"text", 'cancelled'::"text"])))
);


ALTER TABLE "public"."account_link_requests" OWNER TO "postgres";


COMMENT ON TABLE "public"."account_link_requests" IS 'Admin approval workflow for linking standalone recruiter accounts to schools';



CREATE TABLE IF NOT EXISTS "public"."admin_invites" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "school_id" "uuid" NOT NULL,
    "inviter_user_id" "uuid" NOT NULL,
    "invited_admin_email" "text" NOT NULL,
    "status" "text" DEFAULT 'pending'::"text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "completed_at" timestamp with time zone,
    CONSTRAINT "admin_invites_status_check" CHECK (("status" = ANY (ARRAY['pending'::"text", 'completed'::"text", 'expired'::"text"])))
);


ALTER TABLE "public"."admin_invites" OWNER TO "postgres";


COMMENT ON TABLE "public"."admin_invites" IS 'Tracks admin invites from recruiters who create new schools';



COMMENT ON COLUMN "public"."admin_invites"."inviter_user_id" IS 'The recruiter who created the school and will be demoted when admin accepts';



COMMENT ON COLUMN "public"."admin_invites"."invited_admin_email" IS 'Email of the admin being invited';



COMMENT ON COLUMN "public"."admin_invites"."status" IS 'pending=waiting for admin, completed=admin accepted, expired=invite expired';



CREATE TABLE IF NOT EXISTS "public"."audit_log" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "action_timestamp" timestamp with time zone DEFAULT "now"() NOT NULL,
    "user_id" "uuid",
    "action_type" "text" NOT NULL,
    "table_name" "text" NOT NULL,
    "row_id" "uuid",
    "before_data" "jsonb",
    "after_data" "jsonb",
    "extra_info" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."audit_log" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."card_actions" (
    "id" "uuid" DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "card_id" "uuid",
    "user_id" "uuid",
    "action_type" "text" NOT NULL,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "school_id" "uuid" NOT NULL,
    CONSTRAINT "card_actions_action_type_check" CHECK (("action_type" = ANY (ARRAY['upload'::"text", 'review'::"text", 'export'::"text", 'archive'::"text"])))
);


ALTER TABLE "public"."card_actions" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."cards" (
    "id" "uuid" DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "created_by" "uuid",
    "name" "text",
    "image_url" "text",
    "status" "text" DEFAULT 'pending'::"text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "school_id" "uuid" NOT NULL,
    CONSTRAINT "cards_status_check" CHECK (("status" = ANY (ARRAY['pending'::"text", 'reviewed'::"text", 'archived'::"text"])))
);


ALTER TABLE "public"."cards" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."crm_events" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "school_id" "uuid" NOT NULL,
    "crm_event_id" character varying(255) NOT NULL,
    "name" character varying(255) NOT NULL,
    "event_date" "date" NOT NULL,
    "source" character varying(50) DEFAULT 'csv'::character varying,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "last_synced_at" timestamp with time zone DEFAULT "now"(),
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "crm_events_source_check" CHECK ((("source")::"text" = ANY ((ARRAY['csv'::character varying, 'manual'::character varying, 'api'::character varying])::"text"[])))
);


ALTER TABLE "public"."crm_events" OWNER TO "postgres";


COMMENT ON TABLE "public"."crm_events" IS 'Stores CRM event templates for mapping to CardCapture events';



COMMENT ON COLUMN "public"."crm_events"."crm_event_id" IS 'Unique identifier from the external CRM system';



COMMENT ON COLUMN "public"."crm_events"."source" IS 'How the event was created: csv, manual, or api';



COMMENT ON COLUMN "public"."crm_events"."metadata" IS 'Additional flexible data storage for future 
  extensions';



COMMENT ON COLUMN "public"."crm_events"."last_synced_at" IS 'Last time this record was synchronized with 
  external system';



CREATE TABLE IF NOT EXISTS "public"."event_codes" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "code" "text" NOT NULL,
    "event_id" "uuid",
    "active" boolean DEFAULT true,
    "max_uses" integer DEFAULT 1000,
    "current_uses" integer DEFAULT 0,
    "valid_from" timestamp with time zone DEFAULT "now"(),
    "valid_until" timestamp with time zone DEFAULT ("now"() + '7 days'::interval),
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "event_codes_code_check" CHECK ((("length"("code") = 6) AND ("code" ~ '^[0-9]+$'::"text")))
);


ALTER TABLE "public"."event_codes" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."event_purchases" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "universal_event_id" "uuid" NOT NULL,
    "amount" integer DEFAULT 2500 NOT NULL,
    "currency" "text" DEFAULT 'usd'::"text",
    "stripe_payment_intent_id" "text",
    "stripe_checkout_session_id" "text",
    "stripe_customer_id" "text",
    "status" "text" DEFAULT 'pending'::"text",
    "purchased_at" timestamp with time zone DEFAULT "now"(),
    "completed_at" timestamp with time zone,
    "refunded_at" timestamp with time zone,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "event_id" "uuid",
    CONSTRAINT "event_purchases_status_check" CHECK (("status" = ANY (ARRAY['pending'::"text", 'completed'::"text", 'refunded'::"text", 'failed'::"text", 'expired'::"text"])))
);


ALTER TABLE "public"."event_purchases" OWNER TO "postgres";


COMMENT ON TABLE "public"."event_purchases" IS 'Financial tracking for per-event purchases by recruiters';



COMMENT ON COLUMN "public"."event_purchases"."event_id" IS 'Reference to the event created when purchase was completed';



CREATE TABLE IF NOT EXISTS "public"."events" (
    "id" "uuid" DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "name" "text" NOT NULL,
    "description" "text",
    "date" "date" NOT NULL,
    "status" "text" DEFAULT 'active'::"text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "school_id" "uuid" NOT NULL,
    "slate_event_id" character varying(255),
    "universal_event_id" "uuid",
    "event_purchase_id" "uuid",
    CONSTRAINT "events_status_check" CHECK (("status" = ANY (ARRAY['active'::"text", 'archived'::"text"])))
);


ALTER TABLE "public"."events" OWNER TO "postgres";


COMMENT ON COLUMN "public"."events"."slate_event_id" IS 'Optional Slate Event ID for integration purposes';



COMMENT ON COLUMN "public"."events"."universal_event_id" IS 'Reference to universal event catalog entry';



COMMENT ON COLUMN "public"."events"."event_purchase_id" IS 'Reference to the purchase that created this event (self-service flow)';



CREATE TABLE IF NOT EXISTS "public"."extracted_data" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "document_id" "uuid" NOT NULL,
    "image_path" "text",
    "fields" "jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "event_id" "uuid",
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "trimmed_image_path" "text",
    "school_id" "uuid" NOT NULL
);


ALTER TABLE "public"."extracted_data" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."form_sessions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "token" "text" NOT NULL,
    "session_type" "text" NOT NULL,
    "email" "text",
    "event_code_id" "uuid",
    "expires_at" timestamp with time zone NOT NULL,
    "consumed" boolean DEFAULT false,
    "consumed_at" timestamp with time zone,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "form_sessions_session_type_check" CHECK (("session_type" = ANY (ARRAY['magic_link'::"text", 'event_code'::"text"])))
);


ALTER TABLE "public"."form_sessions" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."high_schools_directory" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "nces_id" "text",
    "name" "text" NOT NULL,
    "phone" "text",
    "website" "text",
    "address_line1" "text",
    "address_line2" "text",
    "address_line3" "text",
    "city" "text" NOT NULL,
    "state" "text" NOT NULL,
    "zip_code" "text",
    "zip_plus4" "text",
    "location_address" "text",
    "location_city" "text",
    "location_state" "text",
    "location_zip" "text",
    "district_name" "text",
    "school_type" "text",
    "is_charter" boolean DEFAULT false,
    "level" "text",
    "grades_offered" "text"[],
    "source" "text" DEFAULT 'public'::"text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "ceeb_code" "text",
    CONSTRAINT "high_schools_directory_source_check" CHECK (("source" = ANY (ARRAY['public'::"text", 'private'::"text", 'ceeb'::"text"])))
);


ALTER TABLE "public"."high_schools_directory" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."magic_links" (
    "id" integer NOT NULL,
    "token" character varying(255) NOT NULL,
    "email" character varying(255) NOT NULL,
    "type" character varying(50) NOT NULL,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "expires_at" timestamp with time zone NOT NULL,
    "used" boolean DEFAULT false,
    "used_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "magic_links_type_check" CHECK ((("type")::"text" = ANY ((ARRAY['password_reset'::character varying, 'invite'::character varying, 'registration'::character varying, 'email_verification'::character varying])::"text"[])))
);


ALTER TABLE "public"."magic_links" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."magic_links_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE "public"."magic_links_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."magic_links_id_seq" OWNED BY "public"."magic_links"."id";



CREATE TABLE IF NOT EXISTS "public"."majors_cip" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "cip_code" "text" NOT NULL,
    "cip_title" "text" NOT NULL,
    "cip_definition" "text",
    "cip_family" "text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "display_name" "text",
    "search_priority" integer DEFAULT 1
);


ALTER TABLE "public"."majors_cip" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."mfa_events" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "event_type" "text" NOT NULL,
    "device_token_hash" "text",
    "ip_address" "inet",
    "user_agent" "text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."mfa_events" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."mfa_rate_limits" (
    "user_id" "uuid" NOT NULL,
    "attempt_type" "text" NOT NULL,
    "attempt_count" integer DEFAULT 1 NOT NULL,
    "window_start" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."mfa_rate_limits" OWNER TO "postgres";


COMMENT ON TABLE "public"."mfa_rate_limits" IS 'Rate limiting for MFA operations to prevent brute force attacks';



COMMENT ON COLUMN "public"."mfa_rate_limits"."attempt_type" IS 'Type of MFA operation: challenge, verify, enroll';



COMMENT ON COLUMN "public"."mfa_rate_limits"."attempt_count" IS 'Number of attempts in current window';



COMMENT ON COLUMN "public"."mfa_rate_limits"."window_start" IS 'Start of the current rate limit window';



CREATE TABLE IF NOT EXISTS "public"."processing_jobs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid",
    "school_id" "uuid" NOT NULL,
    "file_url" "text" NOT NULL,
    "status" "text" NOT NULL,
    "result_json" "jsonb",
    "error_message" "text",
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "retries" integer DEFAULT 0,
    "event_id" "uuid",
    "image_path" "text",
    "worker_id" "text",
    "claimed_at" timestamp with time zone,
    "processing_started_at" timestamp with time zone,
    "processing_completed_at" timestamp with time zone,
    "image_hash" "text",
    "retry_count" integer DEFAULT 0,
    CONSTRAINT "processing_jobs_status_check" CHECK (("status" = ANY (ARRAY['queued'::"text", 'processing'::"text", 'complete'::"text", 'failed'::"text"])))
);


ALTER TABLE "public"."processing_jobs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."profiles" (
    "id" "uuid" NOT NULL,
    "email" "text" NOT NULL,
    "role_old" "public"."user_type" DEFAULT 'user'::"public"."user_type",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "first_name" "text",
    "last_name" "text",
    "school_id" "uuid",
    "role" "public"."user_role"[] DEFAULT ARRAY[]::"public"."user_role"[],
    "mfa_verified_at" timestamp with time zone,
    "account_status" "text" DEFAULT 'linked'::"text",
    "parent_school_id" "uuid",
    "is_self_registered" boolean DEFAULT false,
    CONSTRAINT "profiles_account_status_check" CHECK (("account_status" = ANY (ARRAY['standalone'::"text", 'linked'::"text", 'pending_link'::"text"])))
);


ALTER TABLE "public"."profiles" OWNER TO "postgres";


COMMENT ON COLUMN "public"."profiles"."mfa_verified_at" IS 'Timestamp when user last completed MFA verification in current session. NULL means MFA not yet verified.';



COMMENT ON COLUMN "public"."profiles"."account_status" IS 'standalone: self-signup not linked, linked: approved by school admin, pending_link: awaiting approval';



COMMENT ON COLUMN "public"."profiles"."parent_school_id" IS 'School selected during self-signup, before linking is approved';



COMMENT ON COLUMN "public"."profiles"."is_self_registered" IS 'True if user signed up themselves, false if invited by admin';



CREATE TABLE IF NOT EXISTS "public"."registration_attempts" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "ip_address" "inet" NOT NULL,
    "email" "text",
    "attempt_type" "text" NOT NULL,
    "success" boolean DEFAULT false,
    "error_reason" "text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "registration_attempts_attempt_type_check" CHECK (("attempt_type" = ANY (ARRAY['email_start'::"text", 'code_verify'::"text", 'form_submit'::"text"])))
);


ALTER TABLE "public"."registration_attempts" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."registration_metrics" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "session_id" "uuid",
    "student_id" "uuid",
    "event_code_id" "uuid",
    "funnel_step" "text" NOT NULL,
    "source_method" "text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."registration_metrics" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."reviewed_data" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "document_id" "uuid" NOT NULL,
    "fields" "jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "reviewed_at" timestamp with time zone,
    "exported_at" timestamp with time zone,
    "event_id" "uuid",
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "review_status" "text",
    "school_id" "uuid" NOT NULL,
    "user_id" "uuid",
    "image_path" "text",
    "trimmed_image_path" "text",
    "upload_type" character varying(50) DEFAULT 'inquiry_card'::character varying
);


ALTER TABLE "public"."reviewed_data" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."schools" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "pricing_tier" "text",
    "stripe_price_id" "text",
    "has_paid" boolean DEFAULT false,
    "docai_processor_id" "text",
    "card_fields" "jsonb",
    "stripe_customer_id" "text",
    "majors" "text"[] DEFAULT '{Undecided}'::"text"[],
    "card_fields_backup" "jsonb",
    "enable_signup_sheets" boolean DEFAULT false,
    "card_orientation" "public"."card_orientation" DEFAULT 'auto'::"public"."card_orientation" NOT NULL,
    "enable_qr_scanning" boolean DEFAULT false,
    "notification_email" "text",
    "notifications_enabled" boolean DEFAULT false,
    "is_virtual_school" boolean DEFAULT false,
    "credits_balance" integer DEFAULT 0,
    "is_legacy_unlimited" boolean DEFAULT false
);


ALTER TABLE "public"."schools" OWNER TO "postgres";


COMMENT ON TABLE "public"."schools" IS 'Schools table with standardized canonical field names - migrated 2025-08-28';



COMMENT ON COLUMN "public"."schools"."notification_email" IS 'Email address to receive card scan notifications (e.g., admissions@school.edu)';



COMMENT ON COLUMN "public"."schools"."notifications_enabled" IS 'Whether to send hourly digest emails for new card scans';



COMMENT ON COLUMN "public"."schools"."is_virtual_school" IS 'True for auto-created schools for standalone recruiters';



COMMENT ON COLUMN "public"."schools"."credits_balance" IS 'Number of event credits remaining for bulk purchase plans';



COMMENT ON COLUMN "public"."schools"."is_legacy_unlimited" IS 'True for existing subscription customers with unlimited events';



CREATE TABLE IF NOT EXISTS "public"."sftp_configs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "school_id" "uuid",
    "host" "text" NOT NULL,
    "port" integer DEFAULT 22,
    "username" "text" NOT NULL,
    "password" "text" NOT NULL,
    "remote_path" "text" NOT NULL,
    "enabled" boolean DEFAULT true,
    "last_sent_at" timestamp without time zone,
    "created_at" timestamp without time zone DEFAULT "now"(),
    "updated_at" timestamp without time zone DEFAULT "now"()
);


ALTER TABLE "public"."sftp_configs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."student_identifiers" (
    "token" "text" NOT NULL,
    "student_id" "uuid" NOT NULL,
    "active" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "expires_at" timestamp with time zone
);


ALTER TABLE "public"."student_identifiers" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."student_school_interactions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "student_id" "uuid" NOT NULL,
    "school_id" "uuid" NOT NULL,
    "event_id" "uuid",
    "user_id" "uuid",
    "fields" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "review_status" "text" DEFAULT 'reviewed'::"text",
    "source_method" "text",
    "reviewed_at" timestamp with time zone,
    "exported_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "image_path" "text",
    "rating" integer,
    "notes" "text",
    CONSTRAINT "student_school_interactions_review_status_check" CHECK (("review_status" = ANY (ARRAY['reviewed'::"text", 'needs_review'::"text", 'exported'::"text", 'archived'::"text"]))),
    CONSTRAINT "student_school_interactions_source_method_check" CHECK (("source_method" = ANY (ARRAY['qr_code'::"text", 'universal_card'::"text"])))
);


ALTER TABLE "public"."student_school_interactions" OWNER TO "postgres";


COMMENT ON TABLE "public"."student_school_interactions" IS 'V2: Each school''s editable version of a student for an event. Replaces reviewed_data for universal cards and QR codes.';



COMMENT ON COLUMN "public"."student_school_interactions"."image_path" IS 'Path to the card image in storage for this specific interaction';



CREATE TABLE IF NOT EXISTS "public"."students" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "first_name" "text" NOT NULL,
    "last_name" "text" NOT NULL,
    "email" "text",
    "cell" "text",
    "email_opt_in" boolean DEFAULT true,
    "permission_to_text" boolean DEFAULT false,
    "date_of_birth" "date",
    "address" "text",
    "address_2" "text",
    "city" "text",
    "state" "text",
    "zip_code" "text",
    "high_school" "text",
    "grade_level" "text",
    "grad_year" "text",
    "entry_term" "text",
    "entry_year" integer,
    "gpa" numeric,
    "gpa_scale" numeric,
    "sat_score" integer,
    "act_score" integer,
    "academic_interests" "text"[],
    "intended_majors" "text"[],
    "extras" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "preferred_first_name" "text",
    "student_type" "text",
    "major" "text",
    "verified" boolean DEFAULT false,
    "source_method" "text",
    "serial_number" "text",
    "image_url" "text",
    CONSTRAINT "students_source_method_check" CHECK (("source_method" = ANY (ARRAY['magic_link'::"text", 'qr_code'::"text", 'universal_card'::"text"])))
);


ALTER TABLE "public"."students" OWNER TO "postgres";


COMMENT ON COLUMN "public"."students"."image_url" IS 'URL of the original card image from first capture (for reference)';



CREATE TABLE IF NOT EXISTS "public"."trusted_devices" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "device_token_hash" character varying(255) NOT NULL,
    "device_name" character varying(255),
    "expires_at" timestamp with time zone NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "ip_address" "text"
);


ALTER TABLE "public"."trusted_devices" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."universal_events" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "event_date" "date" NOT NULL,
    "start_time" time without time zone,
    "end_time" time without time zone,
    "location" "text",
    "address" "text",
    "city" "text",
    "state" "text" DEFAULT 'TX'::"text",
    "zip" "text",
    "venue" "text",
    "description" "text",
    "student_population" "text",
    "contact_name" "text",
    "contact_email" "text",
    "contact_phone" "text",
    "contact_name_secondary" "text",
    "contact_email_secondary" "text",
    "contact_phone_secondary" "text",
    "registration_url" "text",
    "region" "text",
    "status" "text" DEFAULT 'active'::"text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "needs_inquiry_cards" boolean DEFAULT false,
    "expected_students" integer,
    "inquiry_cards_same_as_event_address" boolean DEFAULT true,
    "inquiry_cards_address" "text",
    "inquiry_cards_city" "text",
    "inquiry_cards_state" "text",
    "inquiry_cards_zip" "text",
    "inquiry_cards_attention" "text",
    CONSTRAINT "universal_events_status_check" CHECK (("status" = ANY (ARRAY['active'::"text", 'past'::"text", 'cancelled'::"text"])))
);


ALTER TABLE "public"."universal_events" OWNER TO "postgres";


COMMENT ON TABLE "public"."universal_events" IS 'Centralized catalog of college fair events that all schools/recruiters can reference';



COMMENT ON COLUMN "public"."universal_events"."needs_inquiry_cards" IS 'Whether the event organizer has requested paper inquiry cards';



COMMENT ON COLUMN "public"."universal_events"."expected_students" IS 'Expected number of students attending (used for inquiry card quantity)';



COMMENT ON COLUMN "public"."universal_events"."inquiry_cards_same_as_event_address" IS 'If true, use event address for mailing inquiry cards';



COMMENT ON COLUMN "public"."universal_events"."inquiry_cards_address" IS 'Street address for mailing inquiry cards (if different from event)';



COMMENT ON COLUMN "public"."universal_events"."inquiry_cards_city" IS 'City for mailing inquiry cards';



COMMENT ON COLUMN "public"."universal_events"."inquiry_cards_state" IS 'State for mailing inquiry cards';



COMMENT ON COLUMN "public"."universal_events"."inquiry_cards_zip" IS 'ZIP code for mailing inquiry cards';



COMMENT ON COLUMN "public"."universal_events"."inquiry_cards_attention" IS 'Attention/recipient name for mailing inquiry cards';



CREATE TABLE IF NOT EXISTS "public"."user_actions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid",
    "action" "text" NOT NULL,
    "target_type" "text",
    "target_id" "uuid",
    "timestamp" timestamp with time zone DEFAULT "now"() NOT NULL,
    "details" "jsonb",
    "school_id" "uuid" NOT NULL
);


ALTER TABLE "public"."user_actions" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."user_mfa_backup_codes" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "code_hash" "text" NOT NULL,
    "used" boolean DEFAULT false,
    "used_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."user_mfa_backup_codes" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."user_mfa_settings" (
    "user_id" "uuid" NOT NULL,
    "mfa_enabled" boolean DEFAULT true,
    "phone_verified" boolean DEFAULT false,
    "phone_number" "text",
    "enrollment_completed_at" timestamp with time zone,
    "last_challenge_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "mfa_enrolled_at" timestamp with time zone,
    "mfa_exempt" boolean DEFAULT false,
    CONSTRAINT "mfa_requires_phone" CHECK ((("mfa_enabled" = false) OR ("mfa_enabled" IS NULL) OR (("mfa_enabled" = true) AND ("phone_number" IS NOT NULL) AND (TRIM(BOTH FROM "phone_number") <> ''::"text")))),
    CONSTRAINT "phone_required_when_mfa_enabled" CHECK (((NOT "mfa_enabled") OR (("phone_number" IS NOT NULL) AND ("phone_number" <> ''::"text"))))
);


ALTER TABLE "public"."user_mfa_settings" OWNER TO "postgres";


COMMENT ON COLUMN "public"."user_mfa_settings"."mfa_exempt" IS 'Set to TRUE to completely exempt user from MFA requirements. Used for shared accounts like admissions@mc.edu';



COMMENT ON CONSTRAINT "phone_required_when_mfa_enabled" ON "public"."user_mfa_settings" IS 'Ensures users cannot have MFA enabled without a valid phone number';



CREATE OR REPLACE VIEW "public"."user_profiles_with_login" AS
 SELECT "p"."id",
    "p"."email",
    "p"."first_name",
    "p"."last_name",
    "p"."role",
    "p"."school_id",
    "u"."last_sign_in_at"
   FROM ("public"."profiles" "p"
     LEFT JOIN "auth"."users" "u" ON (("p"."id" = "u"."id")));


ALTER TABLE "public"."user_profiles_with_login" OWNER TO "postgres";


ALTER TABLE ONLY "public"."magic_links" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."magic_links_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."account_link_requests"
    ADD CONSTRAINT "account_link_requests_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."account_link_requests"
    ADD CONSTRAINT "account_link_requests_requester_user_id_target_school_id_un_key" UNIQUE ("requester_user_id", "target_school_id", "universal_event_id");



ALTER TABLE ONLY "public"."admin_invites"
    ADD CONSTRAINT "admin_invites_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."admin_invites"
    ADD CONSTRAINT "admin_invites_school_id_invited_admin_email_key" UNIQUE ("school_id", "invited_admin_email");



ALTER TABLE ONLY "public"."audit_log"
    ADD CONSTRAINT "audit_log_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."card_actions"
    ADD CONSTRAINT "card_actions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."cards"
    ADD CONSTRAINT "cards_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."crm_events"
    ADD CONSTRAINT "crm_events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."event_codes"
    ADD CONSTRAINT "event_codes_code_key" UNIQUE ("code");



ALTER TABLE ONLY "public"."event_codes"
    ADD CONSTRAINT "event_codes_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."event_purchases"
    ADD CONSTRAINT "event_purchases_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."event_purchases"
    ADD CONSTRAINT "event_purchases_user_id_universal_event_id_key" UNIQUE ("user_id", "universal_event_id");



ALTER TABLE ONLY "public"."events"
    ADD CONSTRAINT "events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."extracted_data"
    ADD CONSTRAINT "extracted_data_document_id_key" UNIQUE ("document_id");



ALTER TABLE ONLY "public"."extracted_data"
    ADD CONSTRAINT "extracted_data_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."form_sessions"
    ADD CONSTRAINT "form_sessions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."form_sessions"
    ADD CONSTRAINT "form_sessions_token_key" UNIQUE ("token");



ALTER TABLE ONLY "public"."high_schools_directory"
    ADD CONSTRAINT "high_schools_directory_nces_id_key" UNIQUE ("nces_id");



ALTER TABLE ONLY "public"."high_schools_directory"
    ADD CONSTRAINT "high_schools_directory_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."magic_links"
    ADD CONSTRAINT "magic_links_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."magic_links"
    ADD CONSTRAINT "magic_links_token_key" UNIQUE ("token");



ALTER TABLE ONLY "public"."majors_cip"
    ADD CONSTRAINT "majors_cip_cip_code_key" UNIQUE ("cip_code");



ALTER TABLE ONLY "public"."majors_cip"
    ADD CONSTRAINT "majors_cip_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."mfa_events"
    ADD CONSTRAINT "mfa_events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."mfa_rate_limits"
    ADD CONSTRAINT "mfa_rate_limits_pkey" PRIMARY KEY ("user_id", "attempt_type");



ALTER TABLE ONLY "public"."processing_jobs"
    ADD CONSTRAINT "processing_jobs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."profiles"
    ADD CONSTRAINT "profiles_email_key" UNIQUE ("email");



ALTER TABLE ONLY "public"."profiles"
    ADD CONSTRAINT "profiles_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."registration_attempts"
    ADD CONSTRAINT "registration_attempts_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."registration_metrics"
    ADD CONSTRAINT "registration_metrics_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."reviewed_data"
    ADD CONSTRAINT "reviewed_data_document_id_key" UNIQUE ("document_id");



ALTER TABLE ONLY "public"."reviewed_data"
    ADD CONSTRAINT "reviewed_data_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."schools"
    ADD CONSTRAINT "schools_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."sftp_configs"
    ADD CONSTRAINT "sftp_configs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."sftp_configs"
    ADD CONSTRAINT "sftp_configs_school_id_unique" UNIQUE ("school_id");



ALTER TABLE ONLY "public"."student_identifiers"
    ADD CONSTRAINT "student_identifiers_pkey" PRIMARY KEY ("token");



ALTER TABLE ONLY "public"."student_school_interactions"
    ADD CONSTRAINT "student_school_interactions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."student_school_interactions"
    ADD CONSTRAINT "student_school_interactions_student_id_school_id_event_id_key" UNIQUE ("student_id", "school_id", "event_id");



ALTER TABLE ONLY "public"."students"
    ADD CONSTRAINT "students_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."students"
    ADD CONSTRAINT "students_serial_number_key" UNIQUE ("serial_number");



ALTER TABLE ONLY "public"."trusted_devices"
    ADD CONSTRAINT "trusted_devices_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."trusted_devices"
    ADD CONSTRAINT "trusted_devices_user_id_device_token_hash_key" UNIQUE ("user_id", "device_token_hash");



ALTER TABLE ONLY "public"."crm_events"
    ADD CONSTRAINT "unique_crm_event_per_school" UNIQUE ("school_id", "crm_event_id");



ALTER TABLE ONLY "public"."universal_events"
    ADD CONSTRAINT "universal_events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."user_actions"
    ADD CONSTRAINT "user_actions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."user_mfa_backup_codes"
    ADD CONSTRAINT "user_mfa_backup_codes_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."user_mfa_backup_codes"
    ADD CONSTRAINT "user_mfa_backup_codes_user_id_code_hash_key" UNIQUE ("user_id", "code_hash");



ALTER TABLE ONLY "public"."user_mfa_settings"
    ADD CONSTRAINT "user_mfa_settings_pkey" PRIMARY KEY ("user_id");



CREATE INDEX "idx_admin_invites_email_status" ON "public"."admin_invites" USING "btree" ("invited_admin_email", "status");



CREATE INDEX "idx_admin_invites_school_id" ON "public"."admin_invites" USING "btree" ("school_id");



CREATE INDEX "idx_crm_events_crm_event_id" ON "public"."crm_events" USING "btree" ("crm_event_id");



CREATE INDEX "idx_crm_events_event_date" ON "public"."crm_events" USING "btree" ("event_date");



CREATE INDEX "idx_crm_events_name" ON "public"."crm_events" USING "btree" ("name");



CREATE INDEX "idx_crm_events_school_id" ON "public"."crm_events" USING "btree" ("school_id");



CREATE INDEX "idx_event_codes_code" ON "public"."event_codes" USING "btree" ("code") WHERE ("active" = true);



CREATE INDEX "idx_event_codes_event_id" ON "public"."event_codes" USING "btree" ("event_id");



CREATE INDEX "idx_event_purchases_event_id" ON "public"."event_purchases" USING "btree" ("event_id") WHERE ("event_id" IS NOT NULL);



CREATE INDEX "idx_event_purchases_status" ON "public"."event_purchases" USING "btree" ("status");



CREATE INDEX "idx_event_purchases_stripe_intent" ON "public"."event_purchases" USING "btree" ("stripe_payment_intent_id");



CREATE INDEX "idx_event_purchases_stripe_session" ON "public"."event_purchases" USING "btree" ("stripe_checkout_session_id");



CREATE INDEX "idx_event_purchases_universal_event" ON "public"."event_purchases" USING "btree" ("universal_event_id");



CREATE INDEX "idx_event_purchases_user" ON "public"."event_purchases" USING "btree" ("user_id");



CREATE INDEX "idx_events_universal_event" ON "public"."events" USING "btree" ("universal_event_id") WHERE ("universal_event_id" IS NOT NULL);



CREATE INDEX "idx_extracted_data_event_id" ON "public"."extracted_data" USING "btree" ("event_id");



CREATE INDEX "idx_form_sessions_expires" ON "public"."form_sessions" USING "btree" ("expires_at") WHERE ("consumed" = false);



CREATE INDEX "idx_form_sessions_token" ON "public"."form_sessions" USING "btree" ("token") WHERE ("consumed" = false);



CREATE INDEX "idx_high_schools_ceeb_code" ON "public"."high_schools_directory" USING "btree" ("ceeb_code");



CREATE INDEX "idx_high_schools_level" ON "public"."high_schools_directory" USING "btree" ("level");



CREATE INDEX "idx_high_schools_name_gin" ON "public"."high_schools_directory" USING "gin" ("to_tsvector"('"english"'::"regconfig", "name"));



CREATE INDEX "idx_high_schools_name_trgm" ON "public"."high_schools_directory" USING "gin" ("name" "public"."gin_trgm_ops");



CREATE INDEX "idx_high_schools_source" ON "public"."high_schools_directory" USING "btree" ("source");



CREATE INDEX "idx_high_schools_state" ON "public"."high_schools_directory" USING "btree" ("state");



CREATE INDEX "idx_interactions_event" ON "public"."student_school_interactions" USING "btree" ("event_id");



CREATE INDEX "idx_interactions_review_status" ON "public"."student_school_interactions" USING "btree" ("review_status");



CREATE INDEX "idx_interactions_school" ON "public"."student_school_interactions" USING "btree" ("school_id");



CREATE INDEX "idx_interactions_school_event" ON "public"."student_school_interactions" USING "btree" ("school_id", "event_id");



CREATE INDEX "idx_interactions_student" ON "public"."student_school_interactions" USING "btree" ("student_id");



CREATE INDEX "idx_link_requests_pending" ON "public"."account_link_requests" USING "btree" ("target_school_id", "status") WHERE ("status" = 'pending'::"text");



CREATE INDEX "idx_link_requests_requester" ON "public"."account_link_requests" USING "btree" ("requester_user_id");



CREATE INDEX "idx_link_requests_status" ON "public"."account_link_requests" USING "btree" ("status");



CREATE INDEX "idx_link_requests_target_school" ON "public"."account_link_requests" USING "btree" ("target_school_id");



CREATE INDEX "idx_magic_links_email" ON "public"."magic_links" USING "btree" ("email");



CREATE INDEX "idx_magic_links_expires_used" ON "public"."magic_links" USING "btree" ("expires_at", "used");



CREATE INDEX "idx_magic_links_token" ON "public"."magic_links" USING "btree" ("token");



CREATE INDEX "idx_magic_links_type" ON "public"."magic_links" USING "btree" ("type");



CREATE INDEX "idx_majors_cip_code" ON "public"."majors_cip" USING "btree" ("cip_code");



CREATE INDEX "idx_majors_cip_display_name_gin" ON "public"."majors_cip" USING "gin" ("to_tsvector"('"english"'::"regconfig", "display_name"));



CREATE INDEX "idx_majors_title_gin" ON "public"."majors_cip" USING "gin" ("to_tsvector"('"english"'::"regconfig", "cip_title"));



CREATE INDEX "idx_majors_title_trgm" ON "public"."majors_cip" USING "gin" ("cip_title" "public"."gin_trgm_ops");



CREATE INDEX "idx_mfa_events_created_at" ON "public"."mfa_events" USING "btree" ("created_at");



CREATE INDEX "idx_mfa_events_type" ON "public"."mfa_events" USING "btree" ("event_type");



CREATE INDEX "idx_mfa_events_user_id" ON "public"."mfa_events" USING "btree" ("user_id");



CREATE INDEX "idx_mfa_rate_limits_user_id" ON "public"."mfa_rate_limits" USING "btree" ("user_id");



CREATE INDEX "idx_mfa_rate_limits_window" ON "public"."mfa_rate_limits" USING "btree" ("window_start");



CREATE INDEX "idx_mfa_rate_limits_window_start" ON "public"."mfa_rate_limits" USING "btree" ("window_start");



CREATE INDEX "idx_processing_jobs_image_hash" ON "public"."processing_jobs" USING "btree" ("image_hash", "event_id");



CREATE INDEX "idx_processing_jobs_status" ON "public"."processing_jobs" USING "btree" ("status");



CREATE INDEX "idx_processing_jobs_status_created" ON "public"."processing_jobs" USING "btree" ("status", "created_at") WHERE ("status" = ANY (ARRAY['queued'::"text", 'processing'::"text"]));



CREATE INDEX "idx_processing_jobs_worker" ON "public"."processing_jobs" USING "btree" ("worker_id", "status") WHERE ("status" = 'processing'::"text");



CREATE INDEX "idx_profiles_account_status" ON "public"."profiles" USING "btree" ("account_status");



CREATE INDEX "idx_profiles_mfa_verified_at" ON "public"."profiles" USING "btree" ("mfa_verified_at");



CREATE INDEX "idx_profiles_parent_school" ON "public"."profiles" USING "btree" ("parent_school_id") WHERE ("parent_school_id" IS NOT NULL);



CREATE INDEX "idx_profiles_school_id_null" ON "public"."profiles" USING "btree" ("id") WHERE ("school_id" IS NULL);



CREATE INDEX "idx_registration_attempts_email_created" ON "public"."registration_attempts" USING "btree" ("email", "created_at" DESC) WHERE ("email" IS NOT NULL);



CREATE INDEX "idx_registration_attempts_ip_created" ON "public"."registration_attempts" USING "btree" ("ip_address", "created_at" DESC);



CREATE INDEX "idx_registration_metrics_session" ON "public"."registration_metrics" USING "btree" ("session_id");



CREATE INDEX "idx_registration_metrics_student" ON "public"."registration_metrics" USING "btree" ("student_id");



CREATE INDEX "idx_reviewed_data_created_at_school" ON "public"."reviewed_data" USING "btree" ("school_id", "created_at" DESC) WHERE ("created_at" IS NOT NULL);



CREATE INDEX "idx_reviewed_data_event_id" ON "public"."reviewed_data" USING "btree" ("event_id");



CREATE INDEX "idx_reviewed_data_upload_type" ON "public"."reviewed_data" USING "btree" ("upload_type");



CREATE INDEX "idx_schools_notifications_enabled" ON "public"."schools" USING "btree" ("notifications_enabled") WHERE ("notifications_enabled" = true);



CREATE INDEX "idx_schools_virtual" ON "public"."schools" USING "btree" ("is_virtual_school") WHERE ("is_virtual_school" = true);



CREATE INDEX "idx_students_cell" ON "public"."students" USING "btree" ("cell");



CREATE INDEX "idx_students_email_lower" ON "public"."students" USING "btree" ("lower"("email"));



CREATE INDEX "idx_students_email_verified" ON "public"."students" USING "btree" ("email", "verified");



CREATE INDEX "idx_students_serial" ON "public"."students" USING "btree" ("serial_number") WHERE ("serial_number" IS NOT NULL);



CREATE INDEX "idx_students_verified" ON "public"."students" USING "btree" ("verified");



CREATE INDEX "idx_trusted_devices_ip_address" ON "public"."trusted_devices" USING "btree" ("ip_address");



CREATE INDEX "idx_trusted_devices_token_hash" ON "public"."trusted_devices" USING "btree" ("device_token_hash");



CREATE INDEX "idx_trusted_devices_user_id" ON "public"."trusted_devices" USING "btree" ("user_id");



CREATE INDEX "idx_universal_events_city" ON "public"."universal_events" USING "btree" ("city");



CREATE INDEX "idx_universal_events_date" ON "public"."universal_events" USING "btree" ("event_date");



CREATE INDEX "idx_universal_events_name" ON "public"."universal_events" USING "btree" ("name");



CREATE INDEX "idx_universal_events_needs_inquiry_cards" ON "public"."universal_events" USING "btree" ("needs_inquiry_cards") WHERE ("needs_inquiry_cards" = true);



CREATE INDEX "idx_universal_events_region" ON "public"."universal_events" USING "btree" ("region");



CREATE INDEX "idx_universal_events_search" ON "public"."universal_events" USING "gin" ("to_tsvector"('"english"'::"regconfig", ((((COALESCE("name", ''::"text") || ' '::"text") || COALESCE("city", ''::"text")) || ' '::"text") || COALESCE("location", ''::"text"))));



CREATE INDEX "idx_universal_events_state" ON "public"."universal_events" USING "btree" ("state");



CREATE INDEX "idx_universal_events_status" ON "public"."universal_events" USING "btree" ("status");



CREATE INDEX "idx_user_mfa_backup_codes_user_id" ON "public"."user_mfa_backup_codes" USING "btree" ("user_id");



CREATE INDEX "idx_user_mfa_settings_enrolled_at" ON "public"."user_mfa_settings" USING "btree" ("mfa_enrolled_at");



CREATE INDEX "idx_user_mfa_settings_mfa_exempt" ON "public"."user_mfa_settings" USING "btree" ("mfa_exempt") WHERE ("mfa_exempt" = true);



CREATE INDEX "idx_user_mfa_settings_user_id" ON "public"."user_mfa_settings" USING "btree" ("user_id");



CREATE UNIQUE INDEX "uq_students_email" ON "public"."students" USING "btree" ("lower"("email")) WHERE ("email" IS NOT NULL);



CREATE OR REPLACE TRIGGER "Process_jobs" AFTER INSERT ON "public"."processing_jobs" FOR EACH ROW EXECUTE FUNCTION "public"."handle_processing_jobs_insert"();



CREATE OR REPLACE TRIGGER "set_updated_at" BEFORE UPDATE ON "public"."schools" FOR EACH ROW EXECUTE FUNCTION "public"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "trg_log_cards_changes" AFTER INSERT OR DELETE OR UPDATE ON "public"."cards" FOR EACH ROW EXECUTE FUNCTION "public"."log_table_changes"();



CREATE OR REPLACE TRIGGER "trg_log_extracted_data_changes" AFTER INSERT OR DELETE OR UPDATE ON "public"."extracted_data" FOR EACH ROW EXECUTE FUNCTION "public"."log_table_changes"();



CREATE OR REPLACE TRIGGER "trg_log_processing_jobs_changes" AFTER INSERT OR DELETE OR UPDATE ON "public"."processing_jobs" FOR EACH ROW EXECUTE FUNCTION "public"."log_table_changes"();



CREATE OR REPLACE TRIGGER "trg_log_profiles_changes" AFTER INSERT OR DELETE OR UPDATE ON "public"."profiles" FOR EACH ROW EXECUTE FUNCTION "public"."log_table_changes"();



CREATE OR REPLACE TRIGGER "trg_log_reviewed_data_changes" AFTER INSERT OR DELETE OR UPDATE ON "public"."reviewed_data" FOR EACH ROW EXECUTE FUNCTION "public"."log_table_changes"();



CREATE OR REPLACE TRIGGER "trg_log_schools_changes" AFTER INSERT OR DELETE OR UPDATE ON "public"."schools" FOR EACH ROW EXECUTE FUNCTION "public"."log_table_changes"();



CREATE OR REPLACE TRIGGER "update_crm_events_updated_at" BEFORE UPDATE ON "public"."crm_events" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_event_codes_updated_at" BEFORE UPDATE ON "public"."event_codes" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_event_purchases_updated_at" BEFORE UPDATE ON "public"."event_purchases" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_events_updated_at" BEFORE UPDATE ON "public"."events" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_extracted_data_updated_at" BEFORE UPDATE ON "public"."extracted_data" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_high_schools_directory_updated_at" BEFORE UPDATE ON "public"."high_schools_directory" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_interactions_updated_at" BEFORE UPDATE ON "public"."student_school_interactions" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_majors_cip_updated_at" BEFORE UPDATE ON "public"."majors_cip" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_mfa_rate_limits_updated_at" BEFORE UPDATE ON "public"."mfa_rate_limits" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_reviewed_data_updated_at" BEFORE UPDATE ON "public"."reviewed_data" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_universal_events_updated_at" BEFORE UPDATE ON "public"."universal_events" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_user_mfa_settings_updated_at" BEFORE UPDATE ON "public"."user_mfa_settings" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



ALTER TABLE ONLY "public"."account_link_requests"
    ADD CONSTRAINT "account_link_requests_event_purchase_id_fkey" FOREIGN KEY ("event_purchase_id") REFERENCES "public"."event_purchases"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."account_link_requests"
    ADD CONSTRAINT "account_link_requests_requester_user_id_fkey" FOREIGN KEY ("requester_user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."account_link_requests"
    ADD CONSTRAINT "account_link_requests_reviewed_by_fkey" FOREIGN KEY ("reviewed_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."account_link_requests"
    ADD CONSTRAINT "account_link_requests_target_school_id_fkey" FOREIGN KEY ("target_school_id") REFERENCES "public"."schools"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."account_link_requests"
    ADD CONSTRAINT "account_link_requests_universal_event_id_fkey" FOREIGN KEY ("universal_event_id") REFERENCES "public"."universal_events"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."admin_invites"
    ADD CONSTRAINT "admin_invites_inviter_user_id_fkey" FOREIGN KEY ("inviter_user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."admin_invites"
    ADD CONSTRAINT "admin_invites_school_id_fkey" FOREIGN KEY ("school_id") REFERENCES "public"."schools"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."audit_log"
    ADD CONSTRAINT "audit_log_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."profiles"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."card_actions"
    ADD CONSTRAINT "card_actions_card_id_fkey" FOREIGN KEY ("card_id") REFERENCES "public"."cards"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."card_actions"
    ADD CONSTRAINT "card_actions_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."cards"
    ADD CONSTRAINT "cards_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."event_codes"
    ADD CONSTRAINT "event_codes_event_id_fkey" FOREIGN KEY ("event_id") REFERENCES "public"."events"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."event_purchases"
    ADD CONSTRAINT "event_purchases_event_id_fkey" FOREIGN KEY ("event_id") REFERENCES "public"."events"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."event_purchases"
    ADD CONSTRAINT "event_purchases_universal_event_id_fkey" FOREIGN KEY ("universal_event_id") REFERENCES "public"."universal_events"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."event_purchases"
    ADD CONSTRAINT "event_purchases_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."events"
    ADD CONSTRAINT "events_event_purchase_id_fkey" FOREIGN KEY ("event_purchase_id") REFERENCES "public"."event_purchases"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."events"
    ADD CONSTRAINT "events_universal_event_id_fkey" FOREIGN KEY ("universal_event_id") REFERENCES "public"."universal_events"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."extracted_data"
    ADD CONSTRAINT "extracted_data_event_id_fkey" FOREIGN KEY ("event_id") REFERENCES "public"."events"("id");



ALTER TABLE ONLY "public"."card_actions"
    ADD CONSTRAINT "fk_card_actions_school_id" FOREIGN KEY ("school_id") REFERENCES "public"."schools"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."cards"
    ADD CONSTRAINT "fk_cards_school_id" FOREIGN KEY ("school_id") REFERENCES "public"."schools"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."events"
    ADD CONSTRAINT "fk_events_school_id" FOREIGN KEY ("school_id") REFERENCES "public"."schools"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."extracted_data"
    ADD CONSTRAINT "fk_extracted_data_school_id" FOREIGN KEY ("school_id") REFERENCES "public"."schools"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."processing_jobs"
    ADD CONSTRAINT "fk_processing_jobs_school_id" FOREIGN KEY ("school_id") REFERENCES "public"."schools"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."reviewed_data"
    ADD CONSTRAINT "fk_reviewed_data_school_id" FOREIGN KEY ("school_id") REFERENCES "public"."schools"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."user_actions"
    ADD CONSTRAINT "fk_user_actions_school_id" FOREIGN KEY ("school_id") REFERENCES "public"."schools"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."form_sessions"
    ADD CONSTRAINT "form_sessions_event_code_id_fkey" FOREIGN KEY ("event_code_id") REFERENCES "public"."event_codes"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."mfa_events"
    ADD CONSTRAINT "mfa_events_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."mfa_rate_limits"
    ADD CONSTRAINT "mfa_rate_limits_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."processing_jobs"
    ADD CONSTRAINT "processing_jobs_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."profiles"
    ADD CONSTRAINT "profiles_id_fkey" FOREIGN KEY ("id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."profiles"
    ADD CONSTRAINT "profiles_parent_school_id_fkey" FOREIGN KEY ("parent_school_id") REFERENCES "public"."schools"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."profiles"
    ADD CONSTRAINT "profiles_school_id_fkey" FOREIGN KEY ("school_id") REFERENCES "public"."schools"("id") ON UPDATE CASCADE ON DELETE CASCADE;



ALTER TABLE ONLY "public"."registration_metrics"
    ADD CONSTRAINT "registration_metrics_event_code_id_fkey" FOREIGN KEY ("event_code_id") REFERENCES "public"."event_codes"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."registration_metrics"
    ADD CONSTRAINT "registration_metrics_session_id_fkey" FOREIGN KEY ("session_id") REFERENCES "public"."form_sessions"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."registration_metrics"
    ADD CONSTRAINT "registration_metrics_student_id_fkey" FOREIGN KEY ("student_id") REFERENCES "public"."students"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."reviewed_data"
    ADD CONSTRAINT "reviewed_data_event_id_fkey" FOREIGN KEY ("event_id") REFERENCES "public"."events"("id");



ALTER TABLE ONLY "public"."sftp_configs"
    ADD CONSTRAINT "sftp_configs_school_id_fkey" FOREIGN KEY ("school_id") REFERENCES "public"."schools"("id");



ALTER TABLE ONLY "public"."student_identifiers"
    ADD CONSTRAINT "student_identifiers_student_id_fkey" FOREIGN KEY ("student_id") REFERENCES "public"."students"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."student_school_interactions"
    ADD CONSTRAINT "student_school_interactions_event_id_fkey" FOREIGN KEY ("event_id") REFERENCES "public"."events"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."student_school_interactions"
    ADD CONSTRAINT "student_school_interactions_school_id_fkey" FOREIGN KEY ("school_id") REFERENCES "public"."schools"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."student_school_interactions"
    ADD CONSTRAINT "student_school_interactions_student_id_fkey" FOREIGN KEY ("student_id") REFERENCES "public"."students"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."student_school_interactions"
    ADD CONSTRAINT "student_school_interactions_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."profiles"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."trusted_devices"
    ADD CONSTRAINT "trusted_devices_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."user_actions"
    ADD CONSTRAINT "user_actions_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."profiles"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."user_mfa_backup_codes"
    ADD CONSTRAINT "user_mfa_backup_codes_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."user_mfa_settings"
    ADD CONSTRAINT "user_mfa_settings_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



CREATE POLICY "Account link requests modifiable by service role" ON "public"."account_link_requests" USING (("auth"."role"() = 'service_role'::"text"));



CREATE POLICY "Admins can create SFTP configs for their school" ON "public"."sftp_configs" FOR INSERT TO "authenticated" WITH CHECK (((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role")) AND ("profiles"."school_id" = "sftp_configs"."school_id")))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "Admins can delete their school's SFTP configs" ON "public"."sftp_configs" FOR DELETE TO "authenticated" USING (((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role")) AND ("profiles"."school_id" = "sftp_configs"."school_id")))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "Admins can update all cards" ON "public"."cards" FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ("profiles"."role_old" = 'admin'::"public"."user_type")))));



CREATE POLICY "Admins can update school link requests" ON "public"."account_link_requests" FOR UPDATE USING (((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role")) AND ("profiles"."school_id" = "account_link_requests"."target_school_id")))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "Admins can update their school's SFTP configs" ON "public"."sftp_configs" FOR UPDATE TO "authenticated" USING (((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role")) AND ("profiles"."school_id" = "sftp_configs"."school_id")))) OR "public"."is_superadmin"("auth"."uid"()))) WITH CHECK (((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role")) AND ("profiles"."school_id" = "sftp_configs"."school_id")))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "Admins can view all actions" ON "public"."card_actions" FOR SELECT USING ((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ("profiles"."role_old" = 'admin'::"public"."user_type")))));



CREATE POLICY "Admins can view all cards" ON "public"."cards" FOR SELECT USING ((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ("profiles"."role_old" = 'admin'::"public"."user_type")))));



CREATE POLICY "Admins can view school link requests" ON "public"."account_link_requests" FOR SELECT USING (((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role")) AND ("profiles"."school_id" = "account_link_requests"."target_school_id")))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "Admins can view school member purchases" ON "public"."event_purchases" FOR SELECT USING (((EXISTS ( SELECT 1
   FROM ("public"."profiles" "admin_profile"
     JOIN "public"."profiles" "user_profile" ON (("user_profile"."id" = "event_purchases"."user_id")))
  WHERE (("admin_profile"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("admin_profile"."role")) AND ("admin_profile"."school_id" = "user_profile"."school_id")))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "Event codes modifiable by service role" ON "public"."event_codes" USING (("auth"."role"() = 'service_role'::"text"));



CREATE POLICY "Event codes viewable by authenticated users" ON "public"."event_codes" FOR SELECT USING (("auth"."role"() = 'authenticated'::"text"));



CREATE POLICY "Event purchases modifiable by service role" ON "public"."event_purchases" USING (("auth"."role"() = 'service_role'::"text"));



CREATE POLICY "Form sessions only for service role" ON "public"."form_sessions" USING (("auth"."role"() = 'service_role'::"text"));



CREATE POLICY "High schools directory modifiable by service role" ON "public"."high_schools_directory" USING (("auth"."role"() = 'service_role'::"text"));



CREATE POLICY "High schools directory readable by authenticated users" ON "public"."high_schools_directory" FOR SELECT USING ((("auth"."role"() = 'authenticated'::"text") OR ("auth"."role"() = 'anon'::"text")));



CREATE POLICY "Majors directory modifiable by service role" ON "public"."majors_cip" USING (("auth"."role"() = 'service_role'::"text"));



CREATE POLICY "Majors directory readable by authenticated users" ON "public"."majors_cip" FOR SELECT USING ((("auth"."role"() = 'authenticated'::"text") OR ("auth"."role"() = 'anon'::"text")));



CREATE POLICY "Only admins can view audit logs" ON "public"."audit_log" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ("profiles"."role_old" = 'admin'::"public"."user_type")))));



CREATE POLICY "Registration attempts only for service role" ON "public"."registration_attempts" USING (("auth"."role"() = 'service_role'::"text"));



CREATE POLICY "Registration metrics readable by authenticated" ON "public"."registration_metrics" FOR SELECT USING (("auth"."role"() = ANY (ARRAY['authenticated'::"text", 'service_role'::"text"])));



CREATE POLICY "Registration metrics writable by service role" ON "public"."registration_metrics" FOR INSERT WITH CHECK (("auth"."role"() = 'service_role'::"text"));



CREATE POLICY "Service role can insert MFA events" ON "public"."mfa_events" FOR INSERT WITH CHECK ((("auth"."jwt"() ->> 'role'::"text") = 'service_role'::"text"));



CREATE POLICY "Service role can manage all MFA settings" ON "public"."user_mfa_settings" TO "service_role" USING (true);



CREATE POLICY "Service role can manage all backup codes" ON "public"."user_mfa_backup_codes" TO "service_role" USING (true);



CREATE POLICY "Service role can manage all profiles" ON "public"."profiles" TO "service_role" USING (true) WITH CHECK (true);



CREATE POLICY "Service role can manage all rate limits" ON "public"."mfa_rate_limits" USING (("auth"."role"() = 'service_role'::"text")) WITH CHECK (("auth"."role"() = 'service_role'::"text"));



CREATE POLICY "Service role can manage all trusted devices" ON "public"."trusted_devices" USING (("auth"."role"() = 'service_role'::"text")) WITH CHECK (("auth"."role"() = 'service_role'::"text"));



CREATE POLICY "Service role has full access to admin_invites" ON "public"."admin_invites" USING (("auth"."role"() = 'service_role'::"text"));



CREATE POLICY "Service role only" ON "public"."magic_links" USING (("auth"."role"() = 'service_role'::"text"));



CREATE POLICY "Service role only" ON "public"."mfa_rate_limits" USING ((("auth"."jwt"() ->> 'role'::"text") = 'service_role'::"text"));



CREATE POLICY "SuperAdmins can create schools" ON "public"."schools" FOR INSERT TO "authenticated" WITH CHECK ("public"."is_superadmin"("auth"."uid"()));



CREATE POLICY "SuperAdmins can delete schools" ON "public"."schools" FOR DELETE TO "authenticated" USING ("public"."is_superadmin"("auth"."uid"()));



CREATE POLICY "SuperAdmins can update schools" ON "public"."schools" FOR UPDATE TO "authenticated" USING ("public"."is_superadmin"("auth"."uid"())) WITH CHECK ("public"."is_superadmin"("auth"."uid"()));



CREATE POLICY "Universal events are publicly readable" ON "public"."universal_events" FOR SELECT USING (true);



CREATE POLICY "Universal events modifiable by service role" ON "public"."universal_events" USING (("auth"."role"() = 'service_role'::"text"));



CREATE POLICY "Users can delete processing jobs for their school events" ON "public"."processing_jobs" FOR DELETE TO "authenticated" USING (((EXISTS ( SELECT 1
   FROM "public"."events"
  WHERE (("events"."id" = "processing_jobs"."event_id") AND ("events"."school_id" = (("auth"."jwt"() ->> 'school_id'::"text"))::"uuid")))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "Users can insert their own actions" ON "public"."card_actions" FOR INSERT WITH CHECK (("auth"."uid"() = "user_id"));



CREATE POLICY "Users can insert their own cards" ON "public"."cards" FOR INSERT WITH CHECK (("auth"."uid"() = "created_by"));



CREATE POLICY "Users can manage their own trusted devices" ON "public"."trusted_devices" USING (("auth"."uid"() = "user_id")) WITH CHECK (("auth"."uid"() = "user_id"));



CREATE POLICY "Users can update processing jobs for their school events" ON "public"."processing_jobs" FOR UPDATE TO "authenticated" USING (((EXISTS ( SELECT 1
   FROM "public"."events"
  WHERE (("events"."id" = "processing_jobs"."event_id") AND ("events"."school_id" = (("auth"."jwt"() ->> 'school_id'::"text"))::"uuid")))) OR "public"."is_superadmin"("auth"."uid"()))) WITH CHECK (((EXISTS ( SELECT 1
   FROM "public"."events"
  WHERE (("events"."id" = "processing_jobs"."event_id") AND ("events"."school_id" = (("auth"."jwt"() ->> 'school_id'::"text"))::"uuid")))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "Users can update their own MFA settings" ON "public"."user_mfa_settings" FOR UPDATE TO "authenticated" USING (("auth"."uid"() = "user_id"));



CREATE POLICY "Users can update their own cards" ON "public"."cards" FOR UPDATE USING (("auth"."uid"() = "created_by"));



CREATE POLICY "Users can update their own profile" ON "public"."profiles" FOR UPDATE TO "authenticated" USING (("auth"."uid"() = "id")) WITH CHECK (("auth"."uid"() = "id"));



CREATE POLICY "Users can view cards they created" ON "public"."cards" FOR SELECT USING (("auth"."uid"() = "created_by"));



CREATE POLICY "Users can view invites they created" ON "public"."admin_invites" FOR SELECT USING (("auth"."uid"() = "inviter_user_id"));



CREATE POLICY "Users can view own link requests" ON "public"."account_link_requests" FOR SELECT USING (("auth"."uid"() = "requester_user_id"));



CREATE POLICY "Users can view own purchases" ON "public"."event_purchases" FOR SELECT USING (("auth"."uid"() = "user_id"));



CREATE POLICY "Users can view their own MFA events" ON "public"."mfa_events" FOR SELECT USING (("auth"."uid"() = "user_id"));



CREATE POLICY "Users can view their own MFA settings" ON "public"."user_mfa_settings" FOR SELECT TO "authenticated" USING (("auth"."uid"() = "user_id"));



CREATE POLICY "Users can view their own actions" ON "public"."card_actions" FOR SELECT USING (("auth"."uid"() = "user_id"));



CREATE POLICY "Users can view their own backup codes" ON "public"."user_mfa_backup_codes" FOR SELECT TO "authenticated" USING (("auth"."uid"() = "user_id"));



CREATE POLICY "Users can view their school's SFTP configs" ON "public"."sftp_configs" FOR SELECT TO "authenticated" USING (((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ("profiles"."school_id" = "sftp_configs"."school_id")))) OR "public"."is_superadmin"("auth"."uid"())));



ALTER TABLE "public"."account_link_requests" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "admin_all" ON "public"."student_school_interactions" USING (((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role"))))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "admin_delete" ON "public"."card_actions" FOR DELETE USING (((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role"))))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "admin_delete" ON "public"."cards" FOR DELETE USING (((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role"))))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "admin_delete" ON "public"."events" FOR DELETE USING (((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role"))))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "admin_delete" ON "public"."processing_jobs" FOR DELETE USING (((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role"))))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "admin_delete" ON "public"."reviewed_data" FOR DELETE USING (((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role"))))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "admin_delete" ON "public"."user_actions" FOR DELETE USING (((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role"))))) OR "public"."is_superadmin"("auth"."uid"())));



ALTER TABLE "public"."admin_invites" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."audit_log" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "audit_log_insert_own" ON "public"."audit_log" FOR INSERT WITH CHECK ((("user_id" = "auth"."uid"()) OR ("auth"."role"() = 'service_role'::"text")));



ALTER TABLE "public"."card_actions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."cards" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."crm_events" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "crm_events_school_delete" ON "public"."crm_events" FOR DELETE USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "crm_events_school_insert" ON "public"."crm_events" FOR INSERT WITH CHECK ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "crm_events_school_select" ON "public"."crm_events" FOR SELECT USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "crm_events_school_update" ON "public"."crm_events" FOR UPDATE USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"()))) WITH CHECK ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "crm_events_service_role" ON "public"."crm_events" USING (("auth"."role"() = 'service_role'::"text"));



ALTER TABLE "public"."event_codes" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."event_purchases" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."events" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."extracted_data" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "extracted_data_admin_delete" ON "public"."extracted_data" FOR DELETE USING (((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role"))))) OR "public"."is_superadmin"("auth"."uid"())));



ALTER TABLE "public"."form_sessions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."high_schools_directory" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."magic_links" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."majors_cip" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."mfa_events" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."mfa_rate_limits" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."processing_jobs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."profiles" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "profiles_admin_update" ON "public"."profiles" FOR UPDATE TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM "public"."profiles" "profiles_1"
  WHERE (("profiles_1"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles_1"."role"))))));



CREATE POLICY "profiles_insert_own" ON "public"."profiles" FOR INSERT WITH CHECK ((("id" = "auth"."uid"()) OR ("auth"."role"() = 'service_role'::"text")));



CREATE POLICY "profiles_read_own" ON "public"."profiles" FOR SELECT TO "authenticated" USING (("id" = "auth"."uid"()));



ALTER TABLE "public"."registration_attempts" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."registration_metrics" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."reviewed_data" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "school_delete" ON "public"."processing_jobs" FOR DELETE USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_delete" ON "public"."student_school_interactions" FOR DELETE USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_insert" ON "public"."card_actions" FOR INSERT WITH CHECK ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_insert" ON "public"."cards" FOR INSERT WITH CHECK ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_insert" ON "public"."events" FOR INSERT WITH CHECK ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_insert" ON "public"."extracted_data" FOR INSERT WITH CHECK ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_insert" ON "public"."processing_jobs" FOR INSERT WITH CHECK ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_insert" ON "public"."reviewed_data" FOR INSERT WITH CHECK ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_insert" ON "public"."student_school_interactions" FOR INSERT WITH CHECK ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_insert" ON "public"."user_actions" FOR INSERT WITH CHECK ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_select" ON "public"."card_actions" FOR SELECT USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_select" ON "public"."cards" FOR SELECT USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_select" ON "public"."events" FOR SELECT USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_select" ON "public"."extracted_data" FOR SELECT USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_select" ON "public"."processing_jobs" FOR SELECT USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_select" ON "public"."reviewed_data" FOR SELECT USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_select" ON "public"."student_school_interactions" FOR SELECT USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_select" ON "public"."user_actions" FOR SELECT USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_update" ON "public"."card_actions" FOR UPDATE USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"()))) WITH CHECK ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_update" ON "public"."cards" FOR UPDATE USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"()))) WITH CHECK ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_update" ON "public"."events" FOR UPDATE USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"()))) WITH CHECK ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_update" ON "public"."extracted_data" FOR UPDATE USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"()))) WITH CHECK ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_update" ON "public"."processing_jobs" FOR UPDATE USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"()))) WITH CHECK ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_update" ON "public"."reviewed_data" FOR UPDATE USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"()))) WITH CHECK ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_update" ON "public"."student_school_interactions" FOR UPDATE USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "school_update" ON "public"."user_actions" FOR UPDATE USING ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"()))) WITH CHECK ((("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



ALTER TABLE "public"."schools" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "schools_own_select" ON "public"."schools" FOR SELECT TO "authenticated" USING ((("id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))) OR "public"."is_superadmin"("auth"."uid"())));



ALTER TABLE "public"."sftp_configs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."student_identifiers" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "student_identifiers_school_delete" ON "public"."student_identifiers" FOR DELETE USING ("public"."is_superadmin"("auth"."uid"()));



CREATE POLICY "student_identifiers_school_insert" ON "public"."student_identifiers" FOR INSERT WITH CHECK (((EXISTS ( SELECT 1
   FROM (("public"."students" "s"
     JOIN "public"."student_school_interactions" "ssi" ON (("ssi"."student_id" = "s"."id")))
     JOIN "public"."profiles" "p" ON (("p"."school_id" = "ssi"."school_id")))
  WHERE (("s"."id" = "student_identifiers"."student_id") AND ("p"."id" = "auth"."uid"())))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "student_identifiers_school_select" ON "public"."student_identifiers" FOR SELECT USING (((EXISTS ( SELECT 1
   FROM (("public"."students" "s"
     JOIN "public"."student_school_interactions" "ssi" ON (("ssi"."student_id" = "s"."id")))
     JOIN "public"."profiles" "p" ON (("p"."school_id" = "ssi"."school_id")))
  WHERE (("s"."id" = "student_identifiers"."student_id") AND ("p"."id" = "auth"."uid"())))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "student_identifiers_school_update" ON "public"."student_identifiers" FOR UPDATE USING (((EXISTS ( SELECT 1
   FROM (("public"."students" "s"
     JOIN "public"."student_school_interactions" "ssi" ON (("ssi"."student_id" = "s"."id")))
     JOIN "public"."profiles" "p" ON (("p"."school_id" = "ssi"."school_id")))
  WHERE (("s"."id" = "student_identifiers"."student_id") AND ("p"."id" = "auth"."uid"())))) OR "public"."is_superadmin"("auth"."uid"())));



ALTER TABLE "public"."student_school_interactions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."students" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "students_school_delete" ON "public"."students" FOR DELETE USING ("public"."is_superadmin"("auth"."uid"()));



CREATE POLICY "students_school_insert" ON "public"."students" FOR INSERT WITH CHECK ("public"."is_superadmin"("auth"."uid"()));



CREATE POLICY "students_school_select" ON "public"."students" FOR SELECT USING (((EXISTS ( SELECT 1
   FROM ("public"."student_school_interactions" "ssi"
     JOIN "public"."profiles" "p" ON (("p"."school_id" = "ssi"."school_id")))
  WHERE (("ssi"."student_id" = "students"."id") AND ("p"."id" = "auth"."uid"())))) OR "public"."is_superadmin"("auth"."uid"())));



CREATE POLICY "students_school_update" ON "public"."students" FOR UPDATE USING (((EXISTS ( SELECT 1
   FROM ("public"."student_school_interactions" "ssi"
     JOIN "public"."profiles" "p" ON (("p"."school_id" = "ssi"."school_id")))
  WHERE (("ssi"."student_id" = "students"."id") AND ("p"."id" = "auth"."uid"())))) OR "public"."is_superadmin"("auth"."uid"())));



ALTER TABLE "public"."trusted_devices" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."universal_events" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."user_actions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."user_mfa_backup_codes" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."user_mfa_settings" ENABLE ROW LEVEL SECURITY;




ALTER PUBLICATION "supabase_realtime" OWNER TO "postgres";






ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."processing_jobs";



ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."reviewed_data";






GRANT USAGE ON SCHEMA "public" TO "postgres";
GRANT USAGE ON SCHEMA "public" TO "anon";
GRANT USAGE ON SCHEMA "public" TO "authenticated";
GRANT USAGE ON SCHEMA "public" TO "service_role";






GRANT ALL ON FUNCTION "public"."gtrgm_in"("cstring") TO "postgres";
GRANT ALL ON FUNCTION "public"."gtrgm_in"("cstring") TO "anon";
GRANT ALL ON FUNCTION "public"."gtrgm_in"("cstring") TO "authenticated";
GRANT ALL ON FUNCTION "public"."gtrgm_in"("cstring") TO "service_role";



GRANT ALL ON FUNCTION "public"."gtrgm_out"("public"."gtrgm") TO "postgres";
GRANT ALL ON FUNCTION "public"."gtrgm_out"("public"."gtrgm") TO "anon";
GRANT ALL ON FUNCTION "public"."gtrgm_out"("public"."gtrgm") TO "authenticated";
GRANT ALL ON FUNCTION "public"."gtrgm_out"("public"."gtrgm") TO "service_role";









































































































































































































GRANT ALL ON FUNCTION "public"."bytea_to_text"("data" "bytea") TO "postgres";
GRANT ALL ON FUNCTION "public"."bytea_to_text"("data" "bytea") TO "anon";
GRANT ALL ON FUNCTION "public"."bytea_to_text"("data" "bytea") TO "authenticated";
GRANT ALL ON FUNCTION "public"."bytea_to_text"("data" "bytea") TO "service_role";



GRANT ALL ON FUNCTION "public"."check_duplicate_job"("p_image_hash" "text", "p_event_id" "uuid", "p_window_minutes" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."check_duplicate_job"("p_image_hash" "text", "p_event_id" "uuid", "p_window_minutes" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."check_duplicate_job"("p_image_hash" "text", "p_event_id" "uuid", "p_window_minutes" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."claim_next_job"("p_worker_id" "text", "p_stale_minutes" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."claim_next_job"("p_worker_id" "text", "p_stale_minutes" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."claim_next_job"("p_worker_id" "text", "p_stale_minutes" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."cleanup_expired_device_tokens"() TO "anon";
GRANT ALL ON FUNCTION "public"."cleanup_expired_device_tokens"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."cleanup_expired_device_tokens"() TO "service_role";



GRANT ALL ON FUNCTION "public"."cleanup_expired_magic_links"() TO "anon";
GRANT ALL ON FUNCTION "public"."cleanup_expired_magic_links"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."cleanup_expired_magic_links"() TO "service_role";



GRANT ALL ON FUNCTION "public"."cleanup_expired_sessions"() TO "anon";
GRANT ALL ON FUNCTION "public"."cleanup_expired_sessions"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."cleanup_expired_sessions"() TO "service_role";



GRANT ALL ON FUNCTION "public"."cleanup_old_rate_limits"() TO "anon";
GRANT ALL ON FUNCTION "public"."cleanup_old_rate_limits"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."cleanup_old_rate_limits"() TO "service_role";



GRANT ALL ON FUNCTION "public"."current_user_school_id"() TO "anon";
GRANT ALL ON FUNCTION "public"."current_user_school_id"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."current_user_school_id"() TO "service_role";



GRANT ALL ON FUNCTION "public"."find_stuck_jobs"("p_minutes" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."find_stuck_jobs"("p_minutes" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."find_stuck_jobs"("p_minutes" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."generate_event_code"() TO "anon";
GRANT ALL ON FUNCTION "public"."generate_event_code"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."generate_event_code"() TO "service_role";



GRANT ALL ON FUNCTION "public"."get_event_card_stats"("event_ids" "uuid"[]) TO "anon";
GRANT ALL ON FUNCTION "public"."get_event_card_stats"("event_ids" "uuid"[]) TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_event_card_stats"("event_ids" "uuid"[]) TO "service_role";



GRANT ALL ON FUNCTION "public"."get_job_statistics"("p_hours" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."get_job_statistics"("p_hours" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_job_statistics"("p_hours" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."get_pending_link_requests_count"("p_school_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."get_pending_link_requests_count"("p_school_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_pending_link_requests_count"("p_school_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."get_user_activity"("target_user_id" "uuid", "time_period" interval) TO "anon";
GRANT ALL ON FUNCTION "public"."get_user_activity"("target_user_id" "uuid", "time_period" interval) TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_user_activity"("target_user_id" "uuid", "time_period" interval) TO "service_role";



GRANT ALL ON FUNCTION "public"."get_user_mfa_factors"("p_user_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."get_user_mfa_factors"("p_user_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_user_mfa_factors"("p_user_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."gin_extract_query_trgm"("text", "internal", smallint, "internal", "internal", "internal", "internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."gin_extract_query_trgm"("text", "internal", smallint, "internal", "internal", "internal", "internal") TO "anon";
GRANT ALL ON FUNCTION "public"."gin_extract_query_trgm"("text", "internal", smallint, "internal", "internal", "internal", "internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."gin_extract_query_trgm"("text", "internal", smallint, "internal", "internal", "internal", "internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."gin_extract_value_trgm"("text", "internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."gin_extract_value_trgm"("text", "internal") TO "anon";
GRANT ALL ON FUNCTION "public"."gin_extract_value_trgm"("text", "internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."gin_extract_value_trgm"("text", "internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."gin_trgm_consistent"("internal", smallint, "text", integer, "internal", "internal", "internal", "internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."gin_trgm_consistent"("internal", smallint, "text", integer, "internal", "internal", "internal", "internal") TO "anon";
GRANT ALL ON FUNCTION "public"."gin_trgm_consistent"("internal", smallint, "text", integer, "internal", "internal", "internal", "internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."gin_trgm_consistent"("internal", smallint, "text", integer, "internal", "internal", "internal", "internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."gin_trgm_triconsistent"("internal", smallint, "text", integer, "internal", "internal", "internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."gin_trgm_triconsistent"("internal", smallint, "text", integer, "internal", "internal", "internal") TO "anon";
GRANT ALL ON FUNCTION "public"."gin_trgm_triconsistent"("internal", smallint, "text", integer, "internal", "internal", "internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."gin_trgm_triconsistent"("internal", smallint, "text", integer, "internal", "internal", "internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."gtrgm_compress"("internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."gtrgm_compress"("internal") TO "anon";
GRANT ALL ON FUNCTION "public"."gtrgm_compress"("internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."gtrgm_compress"("internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."gtrgm_consistent"("internal", "text", smallint, "oid", "internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."gtrgm_consistent"("internal", "text", smallint, "oid", "internal") TO "anon";
GRANT ALL ON FUNCTION "public"."gtrgm_consistent"("internal", "text", smallint, "oid", "internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."gtrgm_consistent"("internal", "text", smallint, "oid", "internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."gtrgm_decompress"("internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."gtrgm_decompress"("internal") TO "anon";
GRANT ALL ON FUNCTION "public"."gtrgm_decompress"("internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."gtrgm_decompress"("internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."gtrgm_distance"("internal", "text", smallint, "oid", "internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."gtrgm_distance"("internal", "text", smallint, "oid", "internal") TO "anon";
GRANT ALL ON FUNCTION "public"."gtrgm_distance"("internal", "text", smallint, "oid", "internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."gtrgm_distance"("internal", "text", smallint, "oid", "internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."gtrgm_options"("internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."gtrgm_options"("internal") TO "anon";
GRANT ALL ON FUNCTION "public"."gtrgm_options"("internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."gtrgm_options"("internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."gtrgm_penalty"("internal", "internal", "internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."gtrgm_penalty"("internal", "internal", "internal") TO "anon";
GRANT ALL ON FUNCTION "public"."gtrgm_penalty"("internal", "internal", "internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."gtrgm_penalty"("internal", "internal", "internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."gtrgm_picksplit"("internal", "internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."gtrgm_picksplit"("internal", "internal") TO "anon";
GRANT ALL ON FUNCTION "public"."gtrgm_picksplit"("internal", "internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."gtrgm_picksplit"("internal", "internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."gtrgm_same"("public"."gtrgm", "public"."gtrgm", "internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."gtrgm_same"("public"."gtrgm", "public"."gtrgm", "internal") TO "anon";
GRANT ALL ON FUNCTION "public"."gtrgm_same"("public"."gtrgm", "public"."gtrgm", "internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."gtrgm_same"("public"."gtrgm", "public"."gtrgm", "internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."gtrgm_union"("internal", "internal") TO "postgres";
GRANT ALL ON FUNCTION "public"."gtrgm_union"("internal", "internal") TO "anon";
GRANT ALL ON FUNCTION "public"."gtrgm_union"("internal", "internal") TO "authenticated";
GRANT ALL ON FUNCTION "public"."gtrgm_union"("internal", "internal") TO "service_role";



GRANT ALL ON FUNCTION "public"."handle_new_user"() TO "anon";
GRANT ALL ON FUNCTION "public"."handle_new_user"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."handle_new_user"() TO "service_role";



GRANT ALL ON FUNCTION "public"."handle_processing_jobs_insert"() TO "anon";
GRANT ALL ON FUNCTION "public"."handle_processing_jobs_insert"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."handle_processing_jobs_insert"() TO "service_role";



GRANT ALL ON FUNCTION "public"."handle_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."handle_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."handle_updated_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."has_event_access"("p_user_id" "uuid", "p_universal_event_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."has_event_access"("p_user_id" "uuid", "p_universal_event_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."has_event_access"("p_user_id" "uuid", "p_universal_event_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."has_role"("user_id" "uuid", "role_name" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."has_role"("user_id" "uuid", "role_name" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."has_role"("user_id" "uuid", "role_name" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."http"("request" "public"."http_request") TO "postgres";
GRANT ALL ON FUNCTION "public"."http"("request" "public"."http_request") TO "anon";
GRANT ALL ON FUNCTION "public"."http"("request" "public"."http_request") TO "authenticated";
GRANT ALL ON FUNCTION "public"."http"("request" "public"."http_request") TO "service_role";



GRANT ALL ON FUNCTION "public"."http_delete"("uri" character varying) TO "postgres";
GRANT ALL ON FUNCTION "public"."http_delete"("uri" character varying) TO "anon";
GRANT ALL ON FUNCTION "public"."http_delete"("uri" character varying) TO "authenticated";
GRANT ALL ON FUNCTION "public"."http_delete"("uri" character varying) TO "service_role";



GRANT ALL ON FUNCTION "public"."http_delete"("uri" character varying, "content" character varying, "content_type" character varying) TO "postgres";
GRANT ALL ON FUNCTION "public"."http_delete"("uri" character varying, "content" character varying, "content_type" character varying) TO "anon";
GRANT ALL ON FUNCTION "public"."http_delete"("uri" character varying, "content" character varying, "content_type" character varying) TO "authenticated";
GRANT ALL ON FUNCTION "public"."http_delete"("uri" character varying, "content" character varying, "content_type" character varying) TO "service_role";



GRANT ALL ON FUNCTION "public"."http_get"("uri" character varying) TO "postgres";
GRANT ALL ON FUNCTION "public"."http_get"("uri" character varying) TO "anon";
GRANT ALL ON FUNCTION "public"."http_get"("uri" character varying) TO "authenticated";
GRANT ALL ON FUNCTION "public"."http_get"("uri" character varying) TO "service_role";



GRANT ALL ON FUNCTION "public"."http_get"("uri" character varying, "data" "jsonb") TO "postgres";
GRANT ALL ON FUNCTION "public"."http_get"("uri" character varying, "data" "jsonb") TO "anon";
GRANT ALL ON FUNCTION "public"."http_get"("uri" character varying, "data" "jsonb") TO "authenticated";
GRANT ALL ON FUNCTION "public"."http_get"("uri" character varying, "data" "jsonb") TO "service_role";



GRANT ALL ON FUNCTION "public"."http_head"("uri" character varying) TO "postgres";
GRANT ALL ON FUNCTION "public"."http_head"("uri" character varying) TO "anon";
GRANT ALL ON FUNCTION "public"."http_head"("uri" character varying) TO "authenticated";
GRANT ALL ON FUNCTION "public"."http_head"("uri" character varying) TO "service_role";



GRANT ALL ON FUNCTION "public"."http_header"("field" character varying, "value" character varying) TO "postgres";
GRANT ALL ON FUNCTION "public"."http_header"("field" character varying, "value" character varying) TO "anon";
GRANT ALL ON FUNCTION "public"."http_header"("field" character varying, "value" character varying) TO "authenticated";
GRANT ALL ON FUNCTION "public"."http_header"("field" character varying, "value" character varying) TO "service_role";



GRANT ALL ON FUNCTION "public"."http_list_curlopt"() TO "postgres";
GRANT ALL ON FUNCTION "public"."http_list_curlopt"() TO "anon";
GRANT ALL ON FUNCTION "public"."http_list_curlopt"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."http_list_curlopt"() TO "service_role";



GRANT ALL ON FUNCTION "public"."http_patch"("uri" character varying, "content" character varying, "content_type" character varying) TO "postgres";
GRANT ALL ON FUNCTION "public"."http_patch"("uri" character varying, "content" character varying, "content_type" character varying) TO "anon";
GRANT ALL ON FUNCTION "public"."http_patch"("uri" character varying, "content" character varying, "content_type" character varying) TO "authenticated";
GRANT ALL ON FUNCTION "public"."http_patch"("uri" character varying, "content" character varying, "content_type" character varying) TO "service_role";



GRANT ALL ON FUNCTION "public"."http_post"("uri" character varying, "data" "jsonb") TO "postgres";
GRANT ALL ON FUNCTION "public"."http_post"("uri" character varying, "data" "jsonb") TO "anon";
GRANT ALL ON FUNCTION "public"."http_post"("uri" character varying, "data" "jsonb") TO "authenticated";
GRANT ALL ON FUNCTION "public"."http_post"("uri" character varying, "data" "jsonb") TO "service_role";



GRANT ALL ON FUNCTION "public"."http_post"("uri" character varying, "content" character varying, "content_type" character varying) TO "postgres";
GRANT ALL ON FUNCTION "public"."http_post"("uri" character varying, "content" character varying, "content_type" character varying) TO "anon";
GRANT ALL ON FUNCTION "public"."http_post"("uri" character varying, "content" character varying, "content_type" character varying) TO "authenticated";
GRANT ALL ON FUNCTION "public"."http_post"("uri" character varying, "content" character varying, "content_type" character varying) TO "service_role";



GRANT ALL ON FUNCTION "public"."http_put"("uri" character varying, "content" character varying, "content_type" character varying) TO "postgres";
GRANT ALL ON FUNCTION "public"."http_put"("uri" character varying, "content" character varying, "content_type" character varying) TO "anon";
GRANT ALL ON FUNCTION "public"."http_put"("uri" character varying, "content" character varying, "content_type" character varying) TO "authenticated";
GRANT ALL ON FUNCTION "public"."http_put"("uri" character varying, "content" character varying, "content_type" character varying) TO "service_role";



GRANT ALL ON FUNCTION "public"."http_reset_curlopt"() TO "postgres";
GRANT ALL ON FUNCTION "public"."http_reset_curlopt"() TO "anon";
GRANT ALL ON FUNCTION "public"."http_reset_curlopt"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."http_reset_curlopt"() TO "service_role";



GRANT ALL ON FUNCTION "public"."http_set_curlopt"("curlopt" character varying, "value" character varying) TO "postgres";
GRANT ALL ON FUNCTION "public"."http_set_curlopt"("curlopt" character varying, "value" character varying) TO "anon";
GRANT ALL ON FUNCTION "public"."http_set_curlopt"("curlopt" character varying, "value" character varying) TO "authenticated";
GRANT ALL ON FUNCTION "public"."http_set_curlopt"("curlopt" character varying, "value" character varying) TO "service_role";



GRANT ALL ON FUNCTION "public"."invite_school_admin"("invitee_email" "text", "invitee_first_name" "text", "invitee_last_name" "text", "target_school_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."invite_school_admin"("invitee_email" "text", "invitee_first_name" "text", "invitee_last_name" "text", "target_school_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."invite_school_admin"("invitee_email" "text", "invitee_first_name" "text", "invitee_last_name" "text", "target_school_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."invite_user"("invitee_email" "text", "invited_user_type" "public"."user_type") TO "anon";
GRANT ALL ON FUNCTION "public"."invite_user"("invitee_email" "text", "invited_user_type" "public"."user_type") TO "authenticated";
GRANT ALL ON FUNCTION "public"."invite_user"("invitee_email" "text", "invited_user_type" "public"."user_type") TO "service_role";



GRANT ALL ON FUNCTION "public"."is_admin"("user_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."is_admin"("user_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."is_admin"("user_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."is_device_trusted"("p_user_id" "uuid", "p_device_token_hash" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."is_device_trusted"("p_user_id" "uuid", "p_device_token_hash" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."is_device_trusted"("p_user_id" "uuid", "p_device_token_hash" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."is_superadmin"("user_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."is_superadmin"("user_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."is_superadmin"("user_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."log_table_changes"() TO "anon";
GRANT ALL ON FUNCTION "public"."log_table_changes"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."log_table_changes"() TO "service_role";



GRANT ALL ON FUNCTION "public"."make_user_admin"("target_user_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."make_user_admin"("target_user_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."make_user_admin"("target_user_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."remove_admin_status"("target_user_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."remove_admin_status"("target_user_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."remove_admin_status"("target_user_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."set_limit"(real) TO "postgres";
GRANT ALL ON FUNCTION "public"."set_limit"(real) TO "anon";
GRANT ALL ON FUNCTION "public"."set_limit"(real) TO "authenticated";
GRANT ALL ON FUNCTION "public"."set_limit"(real) TO "service_role";



GRANT ALL ON FUNCTION "public"."show_limit"() TO "postgres";
GRANT ALL ON FUNCTION "public"."show_limit"() TO "anon";
GRANT ALL ON FUNCTION "public"."show_limit"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."show_limit"() TO "service_role";



GRANT ALL ON FUNCTION "public"."show_trgm"("text") TO "postgres";
GRANT ALL ON FUNCTION "public"."show_trgm"("text") TO "anon";
GRANT ALL ON FUNCTION "public"."show_trgm"("text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."show_trgm"("text") TO "service_role";



GRANT ALL ON FUNCTION "public"."similarity"("text", "text") TO "postgres";
GRANT ALL ON FUNCTION "public"."similarity"("text", "text") TO "anon";
GRANT ALL ON FUNCTION "public"."similarity"("text", "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."similarity"("text", "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."similarity_dist"("text", "text") TO "postgres";
GRANT ALL ON FUNCTION "public"."similarity_dist"("text", "text") TO "anon";
GRANT ALL ON FUNCTION "public"."similarity_dist"("text", "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."similarity_dist"("text", "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."similarity_op"("text", "text") TO "postgres";
GRANT ALL ON FUNCTION "public"."similarity_op"("text", "text") TO "anon";
GRANT ALL ON FUNCTION "public"."similarity_op"("text", "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."similarity_op"("text", "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."strict_word_similarity"("text", "text") TO "postgres";
GRANT ALL ON FUNCTION "public"."strict_word_similarity"("text", "text") TO "anon";
GRANT ALL ON FUNCTION "public"."strict_word_similarity"("text", "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."strict_word_similarity"("text", "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."strict_word_similarity_commutator_op"("text", "text") TO "postgres";
GRANT ALL ON FUNCTION "public"."strict_word_similarity_commutator_op"("text", "text") TO "anon";
GRANT ALL ON FUNCTION "public"."strict_word_similarity_commutator_op"("text", "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."strict_word_similarity_commutator_op"("text", "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."strict_word_similarity_dist_commutator_op"("text", "text") TO "postgres";
GRANT ALL ON FUNCTION "public"."strict_word_similarity_dist_commutator_op"("text", "text") TO "anon";
GRANT ALL ON FUNCTION "public"."strict_word_similarity_dist_commutator_op"("text", "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."strict_word_similarity_dist_commutator_op"("text", "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."strict_word_similarity_dist_op"("text", "text") TO "postgres";
GRANT ALL ON FUNCTION "public"."strict_word_similarity_dist_op"("text", "text") TO "anon";
GRANT ALL ON FUNCTION "public"."strict_word_similarity_dist_op"("text", "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."strict_word_similarity_dist_op"("text", "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."strict_word_similarity_op"("text", "text") TO "postgres";
GRANT ALL ON FUNCTION "public"."strict_word_similarity_op"("text", "text") TO "anon";
GRANT ALL ON FUNCTION "public"."strict_word_similarity_op"("text", "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."strict_word_similarity_op"("text", "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."text_to_bytea"("data" "text") TO "postgres";
GRANT ALL ON FUNCTION "public"."text_to_bytea"("data" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."text_to_bytea"("data" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."text_to_bytea"("data" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."update_bulk_uploads_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_bulk_uploads_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_bulk_uploads_updated_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."update_integration_credentials_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_integration_credentials_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_integration_credentials_updated_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."update_settings_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_settings_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_settings_updated_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."update_updated_at_column"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_updated_at_column"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_updated_at_column"() TO "service_role";



GRANT ALL ON FUNCTION "public"."urlencode"("string" "bytea") TO "postgres";
GRANT ALL ON FUNCTION "public"."urlencode"("string" "bytea") TO "anon";
GRANT ALL ON FUNCTION "public"."urlencode"("string" "bytea") TO "authenticated";
GRANT ALL ON FUNCTION "public"."urlencode"("string" "bytea") TO "service_role";



GRANT ALL ON FUNCTION "public"."urlencode"("data" "jsonb") TO "postgres";
GRANT ALL ON FUNCTION "public"."urlencode"("data" "jsonb") TO "anon";
GRANT ALL ON FUNCTION "public"."urlencode"("data" "jsonb") TO "authenticated";
GRANT ALL ON FUNCTION "public"."urlencode"("data" "jsonb") TO "service_role";



GRANT ALL ON FUNCTION "public"."urlencode"("string" character varying) TO "postgres";
GRANT ALL ON FUNCTION "public"."urlencode"("string" character varying) TO "anon";
GRANT ALL ON FUNCTION "public"."urlencode"("string" character varying) TO "authenticated";
GRANT ALL ON FUNCTION "public"."urlencode"("string" character varying) TO "service_role";



GRANT ALL ON FUNCTION "public"."word_similarity"("text", "text") TO "postgres";
GRANT ALL ON FUNCTION "public"."word_similarity"("text", "text") TO "anon";
GRANT ALL ON FUNCTION "public"."word_similarity"("text", "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."word_similarity"("text", "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."word_similarity_commutator_op"("text", "text") TO "postgres";
GRANT ALL ON FUNCTION "public"."word_similarity_commutator_op"("text", "text") TO "anon";
GRANT ALL ON FUNCTION "public"."word_similarity_commutator_op"("text", "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."word_similarity_commutator_op"("text", "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."word_similarity_dist_commutator_op"("text", "text") TO "postgres";
GRANT ALL ON FUNCTION "public"."word_similarity_dist_commutator_op"("text", "text") TO "anon";
GRANT ALL ON FUNCTION "public"."word_similarity_dist_commutator_op"("text", "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."word_similarity_dist_commutator_op"("text", "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."word_similarity_dist_op"("text", "text") TO "postgres";
GRANT ALL ON FUNCTION "public"."word_similarity_dist_op"("text", "text") TO "anon";
GRANT ALL ON FUNCTION "public"."word_similarity_dist_op"("text", "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."word_similarity_dist_op"("text", "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."word_similarity_op"("text", "text") TO "postgres";
GRANT ALL ON FUNCTION "public"."word_similarity_op"("text", "text") TO "anon";
GRANT ALL ON FUNCTION "public"."word_similarity_op"("text", "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."word_similarity_op"("text", "text") TO "service_role";
























GRANT ALL ON TABLE "public"."account_link_requests" TO "anon";
GRANT ALL ON TABLE "public"."account_link_requests" TO "authenticated";
GRANT ALL ON TABLE "public"."account_link_requests" TO "service_role";



GRANT ALL ON TABLE "public"."admin_invites" TO "anon";
GRANT ALL ON TABLE "public"."admin_invites" TO "authenticated";
GRANT ALL ON TABLE "public"."admin_invites" TO "service_role";



GRANT ALL ON TABLE "public"."audit_log" TO "anon";
GRANT ALL ON TABLE "public"."audit_log" TO "authenticated";
GRANT ALL ON TABLE "public"."audit_log" TO "service_role";



GRANT ALL ON TABLE "public"."card_actions" TO "anon";
GRANT ALL ON TABLE "public"."card_actions" TO "authenticated";
GRANT ALL ON TABLE "public"."card_actions" TO "service_role";



GRANT ALL ON TABLE "public"."cards" TO "anon";
GRANT ALL ON TABLE "public"."cards" TO "authenticated";
GRANT ALL ON TABLE "public"."cards" TO "service_role";



GRANT ALL ON TABLE "public"."crm_events" TO "anon";
GRANT ALL ON TABLE "public"."crm_events" TO "authenticated";
GRANT ALL ON TABLE "public"."crm_events" TO "service_role";



GRANT ALL ON TABLE "public"."event_codes" TO "anon";
GRANT ALL ON TABLE "public"."event_codes" TO "authenticated";
GRANT ALL ON TABLE "public"."event_codes" TO "service_role";



GRANT ALL ON TABLE "public"."event_purchases" TO "anon";
GRANT ALL ON TABLE "public"."event_purchases" TO "authenticated";
GRANT ALL ON TABLE "public"."event_purchases" TO "service_role";



GRANT ALL ON TABLE "public"."events" TO "anon";
GRANT ALL ON TABLE "public"."events" TO "authenticated";
GRANT ALL ON TABLE "public"."events" TO "service_role";



GRANT ALL ON TABLE "public"."extracted_data" TO "anon";
GRANT ALL ON TABLE "public"."extracted_data" TO "authenticated";
GRANT ALL ON TABLE "public"."extracted_data" TO "service_role";



GRANT ALL ON TABLE "public"."form_sessions" TO "anon";
GRANT ALL ON TABLE "public"."form_sessions" TO "authenticated";
GRANT ALL ON TABLE "public"."form_sessions" TO "service_role";



GRANT ALL ON TABLE "public"."high_schools_directory" TO "anon";
GRANT ALL ON TABLE "public"."high_schools_directory" TO "authenticated";
GRANT ALL ON TABLE "public"."high_schools_directory" TO "service_role";



GRANT ALL ON TABLE "public"."magic_links" TO "anon";
GRANT ALL ON TABLE "public"."magic_links" TO "authenticated";
GRANT ALL ON TABLE "public"."magic_links" TO "service_role";



GRANT ALL ON SEQUENCE "public"."magic_links_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."magic_links_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."magic_links_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."majors_cip" TO "anon";
GRANT ALL ON TABLE "public"."majors_cip" TO "authenticated";
GRANT ALL ON TABLE "public"."majors_cip" TO "service_role";



GRANT ALL ON TABLE "public"."mfa_events" TO "anon";
GRANT ALL ON TABLE "public"."mfa_events" TO "authenticated";
GRANT ALL ON TABLE "public"."mfa_events" TO "service_role";



GRANT ALL ON TABLE "public"."mfa_rate_limits" TO "anon";
GRANT ALL ON TABLE "public"."mfa_rate_limits" TO "authenticated";
GRANT ALL ON TABLE "public"."mfa_rate_limits" TO "service_role";



GRANT ALL ON TABLE "public"."processing_jobs" TO "anon";
GRANT ALL ON TABLE "public"."processing_jobs" TO "authenticated";
GRANT ALL ON TABLE "public"."processing_jobs" TO "service_role";



GRANT ALL ON TABLE "public"."profiles" TO "anon";
GRANT ALL ON TABLE "public"."profiles" TO "authenticated";
GRANT ALL ON TABLE "public"."profiles" TO "service_role";



GRANT ALL ON TABLE "public"."registration_attempts" TO "anon";
GRANT ALL ON TABLE "public"."registration_attempts" TO "authenticated";
GRANT ALL ON TABLE "public"."registration_attempts" TO "service_role";



GRANT ALL ON TABLE "public"."registration_metrics" TO "anon";
GRANT ALL ON TABLE "public"."registration_metrics" TO "authenticated";
GRANT ALL ON TABLE "public"."registration_metrics" TO "service_role";



GRANT ALL ON TABLE "public"."reviewed_data" TO "anon";
GRANT ALL ON TABLE "public"."reviewed_data" TO "authenticated";
GRANT ALL ON TABLE "public"."reviewed_data" TO "service_role";



GRANT ALL ON TABLE "public"."schools" TO "anon";
GRANT ALL ON TABLE "public"."schools" TO "authenticated";
GRANT ALL ON TABLE "public"."schools" TO "service_role";



GRANT ALL ON TABLE "public"."sftp_configs" TO "anon";
GRANT ALL ON TABLE "public"."sftp_configs" TO "authenticated";
GRANT ALL ON TABLE "public"."sftp_configs" TO "service_role";



GRANT ALL ON TABLE "public"."student_identifiers" TO "anon";
GRANT ALL ON TABLE "public"."student_identifiers" TO "authenticated";
GRANT ALL ON TABLE "public"."student_identifiers" TO "service_role";



GRANT ALL ON TABLE "public"."student_school_interactions" TO "anon";
GRANT ALL ON TABLE "public"."student_school_interactions" TO "authenticated";
GRANT ALL ON TABLE "public"."student_school_interactions" TO "service_role";



GRANT ALL ON TABLE "public"."students" TO "anon";
GRANT ALL ON TABLE "public"."students" TO "authenticated";
GRANT ALL ON TABLE "public"."students" TO "service_role";



GRANT ALL ON TABLE "public"."trusted_devices" TO "anon";
GRANT ALL ON TABLE "public"."trusted_devices" TO "authenticated";
GRANT ALL ON TABLE "public"."trusted_devices" TO "service_role";



GRANT ALL ON TABLE "public"."universal_events" TO "anon";
GRANT ALL ON TABLE "public"."universal_events" TO "authenticated";
GRANT ALL ON TABLE "public"."universal_events" TO "service_role";



GRANT ALL ON TABLE "public"."user_actions" TO "anon";
GRANT ALL ON TABLE "public"."user_actions" TO "authenticated";
GRANT ALL ON TABLE "public"."user_actions" TO "service_role";



GRANT ALL ON TABLE "public"."user_mfa_backup_codes" TO "anon";
GRANT ALL ON TABLE "public"."user_mfa_backup_codes" TO "authenticated";
GRANT ALL ON TABLE "public"."user_mfa_backup_codes" TO "service_role";



GRANT ALL ON TABLE "public"."user_mfa_settings" TO "anon";
GRANT ALL ON TABLE "public"."user_mfa_settings" TO "authenticated";
GRANT ALL ON TABLE "public"."user_mfa_settings" TO "service_role";



GRANT INSERT,REFERENCES,DELETE,TRIGGER,TRUNCATE,UPDATE ON TABLE "public"."user_profiles_with_login" TO "anon";
GRANT INSERT,REFERENCES,DELETE,TRIGGER,TRUNCATE,UPDATE ON TABLE "public"."user_profiles_with_login" TO "authenticated";
GRANT ALL ON TABLE "public"."user_profiles_with_login" TO "service_role";



ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES  TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES  TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES  TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES  TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS  TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS  TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS  TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS  TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES  TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES  TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES  TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES  TO "service_role";






























