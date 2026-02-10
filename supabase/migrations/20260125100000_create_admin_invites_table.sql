-- Migration: Create admin_invites table for tracking recruiter-to-admin invites
-- This table tracks when a recruiter creates a new school and invites an admin
-- When the admin accepts the invite, the original recruiter is auto-demoted

CREATE TABLE IF NOT EXISTS public.admin_invites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id UUID NOT NULL REFERENCES public.schools(id) ON DELETE CASCADE,
    inviter_user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    invited_admin_email TEXT NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'expired')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    UNIQUE(school_id, invited_admin_email)
);

-- Index for fast lookups when admin accepts invite
CREATE INDEX IF NOT EXISTS idx_admin_invites_email_status
    ON public.admin_invites(invited_admin_email, status);

-- Index for lookups by school
CREATE INDEX IF NOT EXISTS idx_admin_invites_school_id
    ON public.admin_invites(school_id);

-- Enable RLS
ALTER TABLE public.admin_invites ENABLE ROW LEVEL SECURITY;

-- Policy: Service role can do everything (for backend operations)
CREATE POLICY "Service role has full access to admin_invites"
    ON public.admin_invites
    FOR ALL
    USING (auth.role() = 'service_role');

-- Policy: Users can view their own invites (as inviter)
CREATE POLICY "Users can view invites they created"
    ON public.admin_invites
    FOR SELECT
    USING (auth.uid() = inviter_user_id);

COMMENT ON TABLE public.admin_invites IS 'Tracks admin invites from recruiters who create new schools';
COMMENT ON COLUMN public.admin_invites.inviter_user_id IS 'The recruiter who created the school and will be demoted when admin accepts';
COMMENT ON COLUMN public.admin_invites.invited_admin_email IS 'Email of the admin being invited';
COMMENT ON COLUMN public.admin_invites.status IS 'pending=waiting for admin, completed=admin accepted, expired=invite expired';
