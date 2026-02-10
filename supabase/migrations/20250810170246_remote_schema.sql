

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


COMMENT ON SCHEMA "public" IS 'standard public schema';



CREATE EXTENSION IF NOT EXISTS "pg_net" WITH SCHEMA "public";






CREATE EXTENSION IF NOT EXISTS "pgsodium";






CREATE EXTENSION IF NOT EXISTS "http" WITH SCHEMA "public";






CREATE EXTENSION IF NOT EXISTS "pg_graphql" WITH SCHEMA "graphql";






CREATE EXTENSION IF NOT EXISTS "pg_stat_statements" WITH SCHEMA "extensions";






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


CREATE OR REPLACE FUNCTION "public"."cleanup_expired_magic_links"() RETURNS integer
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$
DECLARE
  deleted_count INTEGER;
BEGIN
  DELETE FROM magic_links 
  WHERE (expires_at < NOW() - INTERVAL '7 days')
     OR (used = TRUE AND used_at < NOW() - INTERVAL '1 day');
  
  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RETURN deleted_count;
END;
$$;


ALTER FUNCTION "public"."cleanup_expired_magic_links"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."create_user"("p_email" "text", "p_password" "text", "p_user_meta" "jsonb" DEFAULT '{}'::"jsonb") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$
declare
  new_id uuid := gen_random_uuid();
  now_ts timestamptz := now();
begin
  -- 2) Insert into auth.users
  insert into auth.users (
    instance_id,
    id,
    aud,
    role,
    email,
    encrypted_password,
    email_confirmed_at,
    raw_user_meta_data,
    raw_app_meta_data,
    created_at,
    updated_at
  ) values (
    '00000000-0000-0000-0000-000000000000',  -- default instance_id
    new_id,
    'authenticated',
    'authenticated',
    p_email,
    crypt(p_password, gen_salt('bf')),
    now_ts,
    p_user_meta,
    p_user_meta,
    now_ts,
    now_ts
  );

  -- 3) Insert into auth.identities so the Auth system can log the user in
  insert into auth.identities (
    id,
    user_id,
    identity_data,
    provider,
    provider_id,
    last_sign_in_at,
    created_at,
    updated_at
  ) values (
    gen_random_uuid(),
    new_id,
    jsonb_build_object('sub', new_id::text, 'email', p_email),
    'email',
    p_email,
    now_ts,
    now_ts,
    now_ts
  );
end;
$$;


ALTER FUNCTION "public"."create_user"("p_email" "text", "p_password" "text", "p_user_meta" "jsonb") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."current_user_school_id"() RETURNS "uuid"
    LANGUAGE "sql" SECURITY DEFINER
    AS $$
  SELECT school_id FROM public.profiles WHERE id = auth.uid();
$$;


ALTER FUNCTION "public"."current_user_school_id"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_user_activity"("target_user_id" "uuid", "time_period" interval DEFAULT '30 days'::interval) RETURNS TABLE("action_type" "text", "action_count" bigint)
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$
begin
    -- Check if the current user is an admin or the target user
    if not (is_admin(auth.uid()) or auth.uid() = target_user_id) then
        raise exception 'Unauthorized to view user activity';
    end if;

    return query
    select 
        ca.action_type,
        count(*) as action_count
    from card_actions ca
    where ca.user_id = target_user_id
    and ca.created_at > now() - time_period
    group by ca.action_type;
end;
$$;


ALTER FUNCTION "public"."get_user_activity"("target_user_id" "uuid", "time_period" interval) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."handle_new_user"() RETURNS "trigger"
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$
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
$$;


ALTER FUNCTION "public"."handle_new_user"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."handle_processing_jobs_insert"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$BEGIN
  PERFORM net.http_post(
    url     := 'https://pkpcqmlswrwsefxqhfuf.supabase.co/functions/v1/process-job-trigger',
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


CREATE OR REPLACE FUNCTION "public"."has_role"("user_id" "uuid", "role_name" "text") RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$
begin
    return exists (
        select 1 from profiles
        where id = user_id
        and role_name::user_role = ANY(role)
    );
end;
$$;


ALTER FUNCTION "public"."has_role"("user_id" "uuid", "role_name" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."invite_school_admin"("invitee_email" "text", "invitee_first_name" "text" DEFAULT ''::"text", "invitee_last_name" "text" DEFAULT ''::"text", "target_school_id" "uuid" DEFAULT NULL::"uuid") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$
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
  INSERT INTO public.audit_log (user_id, action_type, extra_info)
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


CREATE OR REPLACE FUNCTION "public"."invite_user"("invitee_email" "text", "invited_user_type" "public"."user_type" DEFAULT 'user'::"public"."user_type") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$
begin
    -- Check if the current user is an admin
    if not is_admin(auth.uid()) then
        raise exception 'Only admins can invite users';
    end if;
    
    -- The actual invitation will be handled by Supabase Auth UI
    -- This function is mainly for validation and future extensibility
    return;
end;
$$;


ALTER FUNCTION "public"."invite_user"("invitee_email" "text", "invited_user_type" "public"."user_type") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."is_admin"("user_id" "uuid") RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$
begin
    return exists (
        select 1 from profiles
        where id = user_id
        and 'admin' = ANY(role)
    );
end;
$$;


ALTER FUNCTION "public"."is_admin"("user_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."is_superadmin"("user_id" "uuid") RETURNS boolean
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$
BEGIN
  RETURN (SELECT school_id FROM public.profiles WHERE id = user_id) IS NULL;
END;
$$;


ALTER FUNCTION "public"."is_superadmin"("user_id" "uuid") OWNER TO "postgres";


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
    AS $$
begin
    -- Check if the current user is an admin
    if not is_admin(auth.uid()) then
        raise exception 'Only admins can promote users to admin';
    end if;

    -- Add admin role if not already present
    update profiles
    set role = array_append(role, 'admin'::user_role)
    where id = target_user_id
    and not ('admin' = ANY(role));
end;
$$;


ALTER FUNCTION "public"."make_user_admin"("target_user_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."remove_admin_status"("target_user_id" "uuid") RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$
begin
    -- Check if the current user is an admin
    if not is_admin(auth.uid()) then
        raise exception 'Only admins can demote other admins';
    end if;

    -- Prevent removing the last admin
    if (select count(*) from profiles where 'admin' = ANY(role)) <= 1 then
        raise exception 'Cannot remove the last admin';
    end if;

    -- Remove admin role
    update profiles
    set role = array_remove(role, 'admin'::user_role)
    where id = target_user_id;
end;
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


CREATE TABLE IF NOT EXISTS "public"."bulk_uploads" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "school_id" "uuid",
    "user_id" "uuid",
    "upload_timestamp" timestamp with time zone DEFAULT "now"() NOT NULL,
    "original_filename" "text",
    "page_count" integer NOT NULL,
    "success_count" integer DEFAULT 0 NOT NULL,
    "failure_count" integer DEFAULT 0 NOT NULL,
    "status" "text" NOT NULL,
    "error_message" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "bulk_uploads_status_check" CHECK (("status" = ANY (ARRAY['pending'::"text", 'processing'::"text", 'complete'::"text", 'failed'::"text"])))
);


ALTER TABLE "public"."bulk_uploads" OWNER TO "postgres";


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
    CONSTRAINT "events_status_check" CHECK (("status" = ANY (ARRAY['active'::"text", 'archived'::"text"])))
);


ALTER TABLE "public"."events" OWNER TO "postgres";


COMMENT ON COLUMN "public"."events"."slate_event_id" IS 'Optional Slate Event ID for integration purposes';



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


CREATE TABLE IF NOT EXISTS "public"."integration_credentials" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "school_id" "uuid",
    "host" "text" NOT NULL,
    "port" integer NOT NULL,
    "username" "text" NOT NULL,
    "encrypted_secret" "bytea" NOT NULL,
    "secret_nonce" "bytea" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."integration_credentials" OWNER TO "postgres";


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
    CONSTRAINT "magic_links_type_check" CHECK ((("type")::"text" = ANY ((ARRAY['password_reset'::character varying, 'invite'::character varying])::"text"[])))
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
    "role" "public"."user_role"[] DEFAULT ARRAY[]::"public"."user_role"[]
);


ALTER TABLE "public"."profiles" OWNER TO "postgres";


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
    "card_orientation" "public"."card_orientation" DEFAULT 'auto'::"public"."card_orientation" NOT NULL
);


ALTER TABLE "public"."schools" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."settings" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "school_id" "uuid",
    "user_id" "uuid",
    "preferences" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."settings" OWNER TO "postgres";


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



ALTER TABLE ONLY "public"."audit_log"
    ADD CONSTRAINT "audit_log_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."bulk_uploads"
    ADD CONSTRAINT "bulk_uploads_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."card_actions"
    ADD CONSTRAINT "card_actions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."cards"
    ADD CONSTRAINT "cards_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."events"
    ADD CONSTRAINT "events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."extracted_data"
    ADD CONSTRAINT "extracted_data_document_id_key" UNIQUE ("document_id");



ALTER TABLE ONLY "public"."extracted_data"
    ADD CONSTRAINT "extracted_data_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."integration_credentials"
    ADD CONSTRAINT "integration_credentials_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."magic_links"
    ADD CONSTRAINT "magic_links_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."magic_links"
    ADD CONSTRAINT "magic_links_token_key" UNIQUE ("token");



ALTER TABLE ONLY "public"."processing_jobs"
    ADD CONSTRAINT "processing_jobs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."profiles"
    ADD CONSTRAINT "profiles_email_key" UNIQUE ("email");



ALTER TABLE ONLY "public"."profiles"
    ADD CONSTRAINT "profiles_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."reviewed_data"
    ADD CONSTRAINT "reviewed_data_document_id_key" UNIQUE ("document_id");



ALTER TABLE ONLY "public"."reviewed_data"
    ADD CONSTRAINT "reviewed_data_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."schools"
    ADD CONSTRAINT "schools_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."settings"
    ADD CONSTRAINT "settings_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."sftp_configs"
    ADD CONSTRAINT "sftp_configs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."sftp_configs"
    ADD CONSTRAINT "sftp_configs_school_id_unique" UNIQUE ("school_id");



ALTER TABLE ONLY "public"."settings"
    ADD CONSTRAINT "unique_school_user" UNIQUE ("school_id", "user_id");



ALTER TABLE ONLY "public"."user_actions"
    ADD CONSTRAINT "user_actions_pkey" PRIMARY KEY ("id");



CREATE INDEX "idx_extracted_data_event_id" ON "public"."extracted_data" USING "btree" ("event_id");



CREATE INDEX "idx_magic_links_email" ON "public"."magic_links" USING "btree" ("email");



CREATE INDEX "idx_magic_links_expires_used" ON "public"."magic_links" USING "btree" ("expires_at", "used");



CREATE INDEX "idx_magic_links_token" ON "public"."magic_links" USING "btree" ("token");



CREATE INDEX "idx_magic_links_type" ON "public"."magic_links" USING "btree" ("type");



CREATE INDEX "idx_processing_jobs_status" ON "public"."processing_jobs" USING "btree" ("status");



CREATE INDEX "idx_profiles_school_id_null" ON "public"."profiles" USING "btree" ("id") WHERE ("school_id" IS NULL);



CREATE INDEX "idx_reviewed_data_event_id" ON "public"."reviewed_data" USING "btree" ("event_id");



CREATE INDEX "idx_reviewed_data_upload_type" ON "public"."reviewed_data" USING "btree" ("upload_type");



CREATE OR REPLACE TRIGGER "Process_jobs" AFTER INSERT ON "public"."processing_jobs" FOR EACH ROW EXECUTE FUNCTION "public"."handle_processing_jobs_insert"();



CREATE OR REPLACE TRIGGER "set_updated_at" BEFORE UPDATE ON "public"."schools" FOR EACH ROW EXECUTE FUNCTION "public"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "trg_log_cards_changes" AFTER INSERT OR DELETE OR UPDATE ON "public"."cards" FOR EACH ROW EXECUTE FUNCTION "public"."log_table_changes"();



CREATE OR REPLACE TRIGGER "trg_log_extracted_data_changes" AFTER INSERT OR DELETE OR UPDATE ON "public"."extracted_data" FOR EACH ROW EXECUTE FUNCTION "public"."log_table_changes"();



CREATE OR REPLACE TRIGGER "trg_log_processing_jobs_changes" AFTER INSERT OR DELETE OR UPDATE ON "public"."processing_jobs" FOR EACH ROW EXECUTE FUNCTION "public"."log_table_changes"();



CREATE OR REPLACE TRIGGER "trg_log_profiles_changes" AFTER INSERT OR DELETE OR UPDATE ON "public"."profiles" FOR EACH ROW EXECUTE FUNCTION "public"."log_table_changes"();



CREATE OR REPLACE TRIGGER "trg_log_reviewed_data_changes" AFTER INSERT OR DELETE OR UPDATE ON "public"."reviewed_data" FOR EACH ROW EXECUTE FUNCTION "public"."log_table_changes"();



CREATE OR REPLACE TRIGGER "trg_log_schools_changes" AFTER INSERT OR DELETE OR UPDATE ON "public"."schools" FOR EACH ROW EXECUTE FUNCTION "public"."log_table_changes"();



CREATE OR REPLACE TRIGGER "trg_update_bulk_uploads_updated_at" BEFORE UPDATE ON "public"."bulk_uploads" FOR EACH ROW EXECUTE FUNCTION "public"."update_bulk_uploads_updated_at"();



CREATE OR REPLACE TRIGGER "trg_update_integration_credentials_updated_at" BEFORE UPDATE ON "public"."integration_credentials" FOR EACH ROW EXECUTE FUNCTION "public"."update_integration_credentials_updated_at"();



CREATE OR REPLACE TRIGGER "trg_update_settings_updated_at" BEFORE UPDATE ON "public"."settings" FOR EACH ROW EXECUTE FUNCTION "public"."update_settings_updated_at"();



CREATE OR REPLACE TRIGGER "update_events_updated_at" BEFORE UPDATE ON "public"."events" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_extracted_data_updated_at" BEFORE UPDATE ON "public"."extracted_data" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_reviewed_data_updated_at" BEFORE UPDATE ON "public"."reviewed_data" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



ALTER TABLE ONLY "public"."audit_log"
    ADD CONSTRAINT "audit_log_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."profiles"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."bulk_uploads"
    ADD CONSTRAINT "bulk_uploads_school_id_fkey" FOREIGN KEY ("school_id") REFERENCES "public"."schools"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."bulk_uploads"
    ADD CONSTRAINT "bulk_uploads_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."profiles"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."card_actions"
    ADD CONSTRAINT "card_actions_card_id_fkey" FOREIGN KEY ("card_id") REFERENCES "public"."cards"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."card_actions"
    ADD CONSTRAINT "card_actions_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."cards"
    ADD CONSTRAINT "cards_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "auth"."users"("id") ON DELETE SET NULL;



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



ALTER TABLE ONLY "public"."integration_credentials"
    ADD CONSTRAINT "integration_credentials_school_id_fkey" FOREIGN KEY ("school_id") REFERENCES "public"."schools"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."processing_jobs"
    ADD CONSTRAINT "processing_jobs_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id");



ALTER TABLE ONLY "public"."profiles"
    ADD CONSTRAINT "profiles_id_fkey" FOREIGN KEY ("id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."profiles"
    ADD CONSTRAINT "profiles_school_id_fkey" FOREIGN KEY ("school_id") REFERENCES "public"."schools"("id") ON UPDATE CASCADE ON DELETE CASCADE;



ALTER TABLE ONLY "public"."reviewed_data"
    ADD CONSTRAINT "reviewed_data_event_id_fkey" FOREIGN KEY ("event_id") REFERENCES "public"."events"("id");



ALTER TABLE ONLY "public"."settings"
    ADD CONSTRAINT "settings_school_id_fkey" FOREIGN KEY ("school_id") REFERENCES "public"."schools"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."settings"
    ADD CONSTRAINT "settings_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."profiles"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."sftp_configs"
    ADD CONSTRAINT "sftp_configs_school_id_fkey" FOREIGN KEY ("school_id") REFERENCES "public"."schools"("id");



ALTER TABLE ONLY "public"."user_actions"
    ADD CONSTRAINT "user_actions_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "public"."profiles"("id") ON DELETE SET NULL;



CREATE POLICY "Admins can update all cards" ON "public"."cards" FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role"))))));



CREATE POLICY "Admins can view all actions" ON "public"."card_actions" FOR SELECT USING ((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role"))))));



CREATE POLICY "Admins can view all cards" ON "public"."cards" FOR SELECT USING ((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role"))))));



CREATE POLICY "Allow authenticated users to insert schools" ON "public"."schools" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "Allow authenticated users to update schools" ON "public"."schools" FOR UPDATE TO "authenticated" USING (true) WITH CHECK (true);



CREATE POLICY "Allow authenticated users to view schools" ON "public"."schools" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Allow trigger inserts" ON "public"."audit_log" FOR INSERT WITH CHECK (true);



CREATE POLICY "Allow trigger inserts" ON "public"."profiles" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "Authenticated users can read schools" ON "public"."schools" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Enable insert for authenticated users" ON "public"."events" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "Enable insert for authenticated users" ON "public"."extracted_data" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "Enable insert for authenticated users" ON "public"."reviewed_data" FOR INSERT TO "authenticated" WITH CHECK (true);



CREATE POLICY "Enable read access for authenticated users" ON "public"."extracted_data" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Enable update for authenticated users" ON "public"."events" FOR UPDATE TO "authenticated" USING (true) WITH CHECK (true);



CREATE POLICY "Enable update for authenticated users" ON "public"."extracted_data" FOR UPDATE TO "authenticated" USING (true) WITH CHECK (true);



CREATE POLICY "Enable update for authenticated users" ON "public"."reviewed_data" FOR UPDATE TO "authenticated" USING (true) WITH CHECK (true);



CREATE POLICY "Only admins can view audit logs" ON "public"."audit_log" FOR SELECT TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role"))))));



CREATE POLICY "Service role can manage all profiles" ON "public"."profiles" TO "service_role" USING (true) WITH CHECK (true);



CREATE POLICY "Service role only" ON "public"."magic_links" USING (("auth"."role"() = 'service_role'::"text"));



CREATE POLICY "SuperAdmins can create schools" ON "public"."schools" FOR INSERT TO "authenticated" WITH CHECK ((NOT (EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ("profiles"."school_id" IS NOT NULL))))));



CREATE POLICY "SuperAdmins can update schools" ON "public"."schools" FOR UPDATE TO "authenticated" USING ((NOT (EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ("profiles"."school_id" IS NOT NULL)))))) WITH CHECK ((NOT (EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ("profiles"."school_id" IS NOT NULL))))));



CREATE POLICY "Users can insert their own actions" ON "public"."card_actions" FOR INSERT WITH CHECK (("auth"."uid"() = "user_id"));



CREATE POLICY "Users can insert their own cards" ON "public"."cards" FOR INSERT WITH CHECK (("auth"."uid"() = "created_by"));



CREATE POLICY "Users can update their own cards" ON "public"."cards" FOR UPDATE USING (("auth"."uid"() = "created_by"));



CREATE POLICY "Users can update their own profile" ON "public"."profiles" FOR UPDATE TO "authenticated" USING (("auth"."uid"() = "id")) WITH CHECK (("auth"."uid"() = "id"));



CREATE POLICY "Users can view cards they created" ON "public"."cards" FOR SELECT USING (("auth"."uid"() = "created_by"));



CREATE POLICY "Users can view their own actions" ON "public"."card_actions" FOR SELECT USING (("auth"."uid"() = "user_id"));



CREATE POLICY "admin_delete" ON "public"."card_actions" FOR DELETE USING ((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role"))))));



CREATE POLICY "admin_delete" ON "public"."cards" FOR DELETE USING ((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role"))))));



CREATE POLICY "admin_delete" ON "public"."events" FOR DELETE USING ((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role"))))));



CREATE POLICY "admin_delete" ON "public"."processing_jobs" FOR DELETE USING ((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role"))))));



CREATE POLICY "admin_delete" ON "public"."reviewed_data" FOR DELETE USING ((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role"))))));



CREATE POLICY "admin_delete" ON "public"."user_actions" FOR DELETE USING ((EXISTS ( SELECT 1
   FROM "public"."profiles"
  WHERE (("profiles"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles"."role"))))));



ALTER TABLE "public"."audit_log" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."card_actions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."cards" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."events" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."extracted_data" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."magic_links" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."processing_jobs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."profiles" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "profiles_admin_update" ON "public"."profiles" FOR UPDATE TO "authenticated" USING ((EXISTS ( SELECT 1
   FROM "public"."profiles" "profiles_1"
  WHERE (("profiles_1"."id" = "auth"."uid"()) AND ('admin'::"public"."user_role" = ANY ("profiles_1"."role"))))));



CREATE POLICY "profiles_read_own" ON "public"."profiles" FOR SELECT TO "authenticated" USING (("id" = "auth"."uid"()));



ALTER TABLE "public"."reviewed_data" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "school_delete" ON "public"."processing_jobs" FOR DELETE USING (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_insert" ON "public"."card_actions" FOR INSERT WITH CHECK (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_insert" ON "public"."cards" FOR INSERT WITH CHECK (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_insert" ON "public"."events" FOR INSERT WITH CHECK (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_insert" ON "public"."extracted_data" FOR INSERT WITH CHECK (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_insert" ON "public"."processing_jobs" FOR INSERT WITH CHECK (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_insert" ON "public"."reviewed_data" FOR INSERT WITH CHECK (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_insert" ON "public"."user_actions" FOR INSERT WITH CHECK (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_select" ON "public"."card_actions" FOR SELECT USING (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_select" ON "public"."cards" FOR SELECT USING (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_select" ON "public"."events" FOR SELECT USING (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_select" ON "public"."extracted_data" FOR SELECT USING (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_select" ON "public"."processing_jobs" FOR SELECT USING (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_select" ON "public"."reviewed_data" FOR SELECT USING (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_select" ON "public"."user_actions" FOR SELECT USING (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_update" ON "public"."card_actions" FOR UPDATE USING (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"())))) WITH CHECK (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_update" ON "public"."cards" FOR UPDATE USING (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"())))) WITH CHECK (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_update" ON "public"."events" FOR UPDATE USING (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"())))) WITH CHECK (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_update" ON "public"."extracted_data" FOR UPDATE USING (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"())))) WITH CHECK (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_update" ON "public"."processing_jobs" FOR UPDATE USING (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"())))) WITH CHECK (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_update" ON "public"."reviewed_data" FOR UPDATE USING (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"())))) WITH CHECK (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



CREATE POLICY "school_update" ON "public"."user_actions" FOR UPDATE USING (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"())))) WITH CHECK (("school_id" IN ( SELECT "profiles"."school_id"
   FROM "public"."profiles"
  WHERE ("profiles"."id" = "auth"."uid"()))));



ALTER TABLE "public"."schools" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."user_actions" ENABLE ROW LEVEL SECURITY;




ALTER PUBLICATION "supabase_realtime" OWNER TO "postgres";






ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."processing_jobs";






ALTER PUBLICATION "supabase_realtime" ADD TABLE ONLY "public"."reviewed_data";



GRANT USAGE ON SCHEMA "public" TO "postgres";
GRANT USAGE ON SCHEMA "public" TO "anon";
GRANT USAGE ON SCHEMA "public" TO "authenticated";
GRANT USAGE ON SCHEMA "public" TO "service_role";























































































































































































GRANT ALL ON FUNCTION "public"."bytea_to_text"("data" "bytea") TO "postgres";
GRANT ALL ON FUNCTION "public"."bytea_to_text"("data" "bytea") TO "anon";
GRANT ALL ON FUNCTION "public"."bytea_to_text"("data" "bytea") TO "authenticated";
GRANT ALL ON FUNCTION "public"."bytea_to_text"("data" "bytea") TO "service_role";



GRANT ALL ON FUNCTION "public"."cleanup_expired_magic_links"() TO "anon";
GRANT ALL ON FUNCTION "public"."cleanup_expired_magic_links"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."cleanup_expired_magic_links"() TO "service_role";



GRANT ALL ON FUNCTION "public"."create_user"("p_email" "text", "p_password" "text", "p_user_meta" "jsonb") TO "anon";
GRANT ALL ON FUNCTION "public"."create_user"("p_email" "text", "p_password" "text", "p_user_meta" "jsonb") TO "authenticated";
GRANT ALL ON FUNCTION "public"."create_user"("p_email" "text", "p_password" "text", "p_user_meta" "jsonb") TO "service_role";



GRANT ALL ON FUNCTION "public"."current_user_school_id"() TO "anon";
GRANT ALL ON FUNCTION "public"."current_user_school_id"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."current_user_school_id"() TO "service_role";



GRANT ALL ON FUNCTION "public"."get_user_activity"("target_user_id" "uuid", "time_period" interval) TO "anon";
GRANT ALL ON FUNCTION "public"."get_user_activity"("target_user_id" "uuid", "time_period" interval) TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_user_activity"("target_user_id" "uuid", "time_period" interval) TO "service_role";



GRANT ALL ON FUNCTION "public"."handle_new_user"() TO "anon";
GRANT ALL ON FUNCTION "public"."handle_new_user"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."handle_new_user"() TO "service_role";



GRANT ALL ON FUNCTION "public"."handle_processing_jobs_insert"() TO "anon";
GRANT ALL ON FUNCTION "public"."handle_processing_jobs_insert"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."handle_processing_jobs_insert"() TO "service_role";



GRANT ALL ON FUNCTION "public"."handle_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."handle_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."handle_updated_at"() TO "service_role";



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



























GRANT ALL ON TABLE "public"."audit_log" TO "anon";
GRANT ALL ON TABLE "public"."audit_log" TO "authenticated";
GRANT ALL ON TABLE "public"."audit_log" TO "service_role";



GRANT ALL ON TABLE "public"."bulk_uploads" TO "anon";
GRANT ALL ON TABLE "public"."bulk_uploads" TO "authenticated";
GRANT ALL ON TABLE "public"."bulk_uploads" TO "service_role";



GRANT ALL ON TABLE "public"."card_actions" TO "anon";
GRANT ALL ON TABLE "public"."card_actions" TO "authenticated";
GRANT ALL ON TABLE "public"."card_actions" TO "service_role";



GRANT ALL ON TABLE "public"."cards" TO "anon";
GRANT ALL ON TABLE "public"."cards" TO "authenticated";
GRANT ALL ON TABLE "public"."cards" TO "service_role";



GRANT ALL ON TABLE "public"."events" TO "anon";
GRANT ALL ON TABLE "public"."events" TO "authenticated";
GRANT ALL ON TABLE "public"."events" TO "service_role";



GRANT ALL ON TABLE "public"."extracted_data" TO "anon";
GRANT ALL ON TABLE "public"."extracted_data" TO "authenticated";
GRANT ALL ON TABLE "public"."extracted_data" TO "service_role";



GRANT ALL ON TABLE "public"."integration_credentials" TO "anon";
GRANT ALL ON TABLE "public"."integration_credentials" TO "authenticated";
GRANT ALL ON TABLE "public"."integration_credentials" TO "service_role";



GRANT ALL ON TABLE "public"."magic_links" TO "anon";
GRANT ALL ON TABLE "public"."magic_links" TO "authenticated";
GRANT ALL ON TABLE "public"."magic_links" TO "service_role";



GRANT ALL ON SEQUENCE "public"."magic_links_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."magic_links_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."magic_links_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."processing_jobs" TO "anon";
GRANT ALL ON TABLE "public"."processing_jobs" TO "authenticated";
GRANT ALL ON TABLE "public"."processing_jobs" TO "service_role";



GRANT ALL ON TABLE "public"."profiles" TO "anon";
GRANT ALL ON TABLE "public"."profiles" TO "authenticated";
GRANT ALL ON TABLE "public"."profiles" TO "service_role";



GRANT ALL ON TABLE "public"."reviewed_data" TO "anon";
GRANT ALL ON TABLE "public"."reviewed_data" TO "authenticated";
GRANT ALL ON TABLE "public"."reviewed_data" TO "service_role";



GRANT ALL ON TABLE "public"."schools" TO "anon";
GRANT ALL ON TABLE "public"."schools" TO "authenticated";
GRANT ALL ON TABLE "public"."schools" TO "service_role";



GRANT ALL ON TABLE "public"."settings" TO "anon";
GRANT ALL ON TABLE "public"."settings" TO "authenticated";
GRANT ALL ON TABLE "public"."settings" TO "service_role";



GRANT ALL ON TABLE "public"."sftp_configs" TO "anon";
GRANT ALL ON TABLE "public"."sftp_configs" TO "authenticated";
GRANT ALL ON TABLE "public"."sftp_configs" TO "service_role";



GRANT ALL ON TABLE "public"."user_actions" TO "anon";
GRANT ALL ON TABLE "public"."user_actions" TO "authenticated";
GRANT ALL ON TABLE "public"."user_actions" TO "service_role";



GRANT ALL ON TABLE "public"."user_profiles_with_login" TO "anon";
GRANT ALL ON TABLE "public"."user_profiles_with_login" TO "authenticated";
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






























RESET ALL;
