-- ============================================================================
-- Recruiter Self-Service Foundation Migration
-- Phase 1: Database schema changes for recruiter self-signup system
-- ============================================================================

-- ============================================================================
-- 1. CREATE UNIVERSAL_EVENTS TABLE
-- Master list of college fair events that recruiters can claim
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.universal_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    event_date DATE NOT NULL,
    start_time TIME,
    end_time TIME,
    location TEXT,                    -- Venue name (e.g., "Argyle High School Cafeteria")
    address TEXT,                     -- Street address
    city TEXT,
    state TEXT DEFAULT 'TX',
    zip TEXT,
    venue TEXT,                       -- Alternative venue field
    description TEXT,
    student_population TEXT,          -- FR, TR, etc.
    contact_name TEXT,
    contact_email TEXT,
    contact_phone TEXT,
    contact_name_secondary TEXT,
    contact_email_secondary TEXT,
    contact_phone_secondary TEXT,
    registration_url TEXT,
    region TEXT,                      -- e.g., "DALLAS I", "HOUSTON II"
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'past', 'cancelled')),
    metadata JSONB DEFAULT '{}',      -- Flexible field for additional data
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for universal_events
CREATE INDEX IF NOT EXISTS idx_universal_events_date ON public.universal_events(event_date);
CREATE INDEX IF NOT EXISTS idx_universal_events_name ON public.universal_events(name);
CREATE INDEX IF NOT EXISTS idx_universal_events_city ON public.universal_events(city);
CREATE INDEX IF NOT EXISTS idx_universal_events_state ON public.universal_events(state);
CREATE INDEX IF NOT EXISTS idx_universal_events_region ON public.universal_events(region);
CREATE INDEX IF NOT EXISTS idx_universal_events_status ON public.universal_events(status);

-- Full-text search index for event search
CREATE INDEX IF NOT EXISTS idx_universal_events_search ON public.universal_events
    USING gin(to_tsvector('english', coalesce(name, '') || ' ' || coalesce(city, '') || ' ' || coalesce(location, '')));

-- Updated at trigger
DROP TRIGGER IF EXISTS update_universal_events_updated_at ON public.universal_events;
CREATE TRIGGER update_universal_events_updated_at
    BEFORE UPDATE ON public.universal_events
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE public.universal_events IS 'Centralized catalog of college fair events that all schools/recruiters can reference';


-- ============================================================================
-- 2. CREATE EVENT_PURCHASES TABLE
-- Track $25 payments per recruiter per event
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.event_purchases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    universal_event_id UUID NOT NULL REFERENCES public.universal_events(id) ON DELETE RESTRICT,
    amount INTEGER NOT NULL DEFAULT 2500,  -- Amount in cents ($25.00)
    currency TEXT DEFAULT 'usd',
    stripe_payment_intent_id TEXT,
    stripe_checkout_session_id TEXT,
    stripe_customer_id TEXT,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'refunded', 'failed', 'expired')),
    purchased_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    refunded_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Prevent duplicate purchases for same user+event
    UNIQUE(user_id, universal_event_id)
);

-- Indexes for event_purchases
CREATE INDEX IF NOT EXISTS idx_event_purchases_user ON public.event_purchases(user_id);
CREATE INDEX IF NOT EXISTS idx_event_purchases_universal_event ON public.event_purchases(universal_event_id);
CREATE INDEX IF NOT EXISTS idx_event_purchases_status ON public.event_purchases(status);
CREATE INDEX IF NOT EXISTS idx_event_purchases_stripe_session ON public.event_purchases(stripe_checkout_session_id);
CREATE INDEX IF NOT EXISTS idx_event_purchases_stripe_intent ON public.event_purchases(stripe_payment_intent_id);

-- Updated at trigger
DROP TRIGGER IF EXISTS update_event_purchases_updated_at ON public.event_purchases;
CREATE TRIGGER update_event_purchases_updated_at
    BEFORE UPDATE ON public.event_purchases
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE public.event_purchases IS 'Financial tracking for per-event purchases by recruiters';


-- ============================================================================
-- 3. CREATE ACCOUNT_LINK_REQUESTS TABLE
-- Track pending requests to link standalone recruiters to school accounts
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.account_link_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requester_user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    target_school_id UUID NOT NULL REFERENCES public.schools(id) ON DELETE CASCADE,
    universal_event_id UUID NOT NULL REFERENCES public.universal_events(id) ON DELETE CASCADE,
    event_purchase_id UUID REFERENCES public.event_purchases(id) ON DELETE SET NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')),
    requester_message TEXT,           -- Optional message from recruiter
    admin_notes TEXT,                 -- Notes from admin who reviewed
    created_at TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    reviewed_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '30 days'),

    -- One pending request per user+school+event combination
    UNIQUE(requester_user_id, target_school_id, universal_event_id)
);

-- Indexes for account_link_requests
CREATE INDEX IF NOT EXISTS idx_link_requests_target_school ON public.account_link_requests(target_school_id);
CREATE INDEX IF NOT EXISTS idx_link_requests_requester ON public.account_link_requests(requester_user_id);
CREATE INDEX IF NOT EXISTS idx_link_requests_status ON public.account_link_requests(status);
CREATE INDEX IF NOT EXISTS idx_link_requests_pending ON public.account_link_requests(target_school_id, status)
    WHERE status = 'pending';

COMMENT ON TABLE public.account_link_requests IS 'Admin approval workflow for linking standalone recruiter accounts to schools';


-- ============================================================================
-- 4. UPDATE PROFILES TABLE
-- Add account linking status columns
-- ============================================================================

-- Account status: standalone (default for self-signup), linked (approved by admin), pending_link
ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS account_status TEXT DEFAULT 'linked'
        CHECK (account_status IN ('standalone', 'linked', 'pending_link'));

-- Parent school ID: tracks which school the recruiter selected during signup (before linking)
ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS parent_school_id UUID REFERENCES public.schools(id) ON DELETE SET NULL;

-- Flag for self-registered users (vs invited)
ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS is_self_registered BOOLEAN DEFAULT FALSE;

-- Index for querying by account status
CREATE INDEX IF NOT EXISTS idx_profiles_account_status ON public.profiles(account_status);
CREATE INDEX IF NOT EXISTS idx_profiles_parent_school ON public.profiles(parent_school_id)
    WHERE parent_school_id IS NOT NULL;

COMMENT ON COLUMN public.profiles.account_status IS 'standalone: self-signup not linked, linked: approved by school admin, pending_link: awaiting approval';
COMMENT ON COLUMN public.profiles.parent_school_id IS 'School selected during self-signup, before linking is approved';
COMMENT ON COLUMN public.profiles.is_self_registered IS 'True if user signed up themselves, false if invited by admin';


-- ============================================================================
-- 5. UPDATE SCHOOLS TABLE
-- Add virtual school flag and credits balance
-- ============================================================================

-- Virtual school: auto-created schools for standalone recruiters who select "My school isn't listed"
ALTER TABLE public.schools
    ADD COLUMN IF NOT EXISTS is_virtual_school BOOLEAN DEFAULT FALSE;

-- Credits balance for future bulk credit purchases
ALTER TABLE public.schools
    ADD COLUMN IF NOT EXISTS credits_balance INTEGER DEFAULT 0;

-- Legacy unlimited plan flag (for existing subscription customers)
ALTER TABLE public.schools
    ADD COLUMN IF NOT EXISTS is_legacy_unlimited BOOLEAN DEFAULT FALSE;

-- Index for virtual schools
CREATE INDEX IF NOT EXISTS idx_schools_virtual ON public.schools(is_virtual_school)
    WHERE is_virtual_school = TRUE;

COMMENT ON COLUMN public.schools.is_virtual_school IS 'True for auto-created schools for standalone recruiters';
COMMENT ON COLUMN public.schools.credits_balance IS 'Number of event credits remaining for bulk purchase plans';
COMMENT ON COLUMN public.schools.is_legacy_unlimited IS 'True for existing subscription customers with unlimited events';


-- ============================================================================
-- 6. UPDATE EVENTS TABLE
-- Link to universal events catalog
-- ============================================================================

-- Reference to the universal event catalog
ALTER TABLE public.events
    ADD COLUMN IF NOT EXISTS universal_event_id UUID REFERENCES public.universal_events(id) ON DELETE SET NULL;

-- Track the event purchase that created this event (for self-service flow)
ALTER TABLE public.events
    ADD COLUMN IF NOT EXISTS event_purchase_id UUID REFERENCES public.event_purchases(id) ON DELETE SET NULL;

-- Index for looking up events by universal event
CREATE INDEX IF NOT EXISTS idx_events_universal_event ON public.events(universal_event_id)
    WHERE universal_event_id IS NOT NULL;

COMMENT ON COLUMN public.events.universal_event_id IS 'Reference to universal event catalog entry';
COMMENT ON COLUMN public.events.event_purchase_id IS 'Reference to the purchase that created this event (self-service flow)';


-- ============================================================================
-- 7. RLS POLICIES FOR NEW TABLES
-- ============================================================================

-- Enable RLS on all new tables
ALTER TABLE public.universal_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.event_purchases ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.account_link_requests ENABLE ROW LEVEL SECURITY;


-- -------------------------
-- UNIVERSAL_EVENTS POLICIES
-- -------------------------

-- Public read access for universal events (needed for signup flow)
DROP POLICY IF EXISTS "Universal events are publicly readable" ON public.universal_events;
CREATE POLICY "Universal events are publicly readable"
    ON public.universal_events
    FOR SELECT
    USING (TRUE);

-- Only service role can modify universal events
DROP POLICY IF EXISTS "Universal events modifiable by service role" ON public.universal_events;
CREATE POLICY "Universal events modifiable by service role"
    ON public.universal_events
    FOR ALL
    USING (auth.role() = 'service_role');


-- -------------------------
-- EVENT_PURCHASES POLICIES
-- -------------------------

-- Users can view their own purchases
DROP POLICY IF EXISTS "Users can view own purchases" ON public.event_purchases;
CREATE POLICY "Users can view own purchases"
    ON public.event_purchases
    FOR SELECT
    USING (auth.uid() = user_id);

-- Admins can view purchases for their school members
DROP POLICY IF EXISTS "Admins can view school member purchases" ON public.event_purchases;
CREATE POLICY "Admins can view school member purchases"
    ON public.event_purchases
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.profiles admin_profile
            JOIN public.profiles user_profile ON user_profile.id = event_purchases.user_id
            WHERE admin_profile.id = auth.uid()
            AND 'admin' = ANY(admin_profile.role)
            AND admin_profile.school_id = user_profile.school_id
        )
    );

-- Service role can do everything
DROP POLICY IF EXISTS "Event purchases modifiable by service role" ON public.event_purchases;
CREATE POLICY "Event purchases modifiable by service role"
    ON public.event_purchases
    FOR ALL
    USING (auth.role() = 'service_role');


-- -------------------------
-- ACCOUNT_LINK_REQUESTS POLICIES
-- -------------------------

-- Requesters can view their own link requests
DROP POLICY IF EXISTS "Users can view own link requests" ON public.account_link_requests;
CREATE POLICY "Users can view own link requests"
    ON public.account_link_requests
    FOR SELECT
    USING (auth.uid() = requester_user_id);

-- School admins can view link requests for their school
DROP POLICY IF EXISTS "Admins can view school link requests" ON public.account_link_requests;
CREATE POLICY "Admins can view school link requests"
    ON public.account_link_requests
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.profiles
            WHERE profiles.id = auth.uid()
            AND 'admin' = ANY(profiles.role)
            AND profiles.school_id = account_link_requests.target_school_id
        )
    );

-- School admins can update link requests for their school (approve/reject)
DROP POLICY IF EXISTS "Admins can update school link requests" ON public.account_link_requests;
CREATE POLICY "Admins can update school link requests"
    ON public.account_link_requests
    FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM public.profiles
            WHERE profiles.id = auth.uid()
            AND 'admin' = ANY(profiles.role)
            AND profiles.school_id = account_link_requests.target_school_id
        )
    );

-- Service role can do everything
DROP POLICY IF EXISTS "Account link requests modifiable by service role" ON public.account_link_requests;
CREATE POLICY "Account link requests modifiable by service role"
    ON public.account_link_requests
    FOR ALL
    USING (auth.role() = 'service_role');


-- ============================================================================
-- 8. HELPER FUNCTIONS
-- ============================================================================

-- Function to check if a user has purchased access to a universal event
CREATE OR REPLACE FUNCTION public.has_event_access(p_user_id UUID, p_universal_event_id UUID)
RETURNS BOOLEAN AS $$
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
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION public.has_event_access IS 'Check if a user has access to a universal event (via purchase, legacy plan, or credits)';


-- Function to get pending link requests count for a school
CREATE OR REPLACE FUNCTION public.get_pending_link_requests_count(p_school_id UUID)
RETURNS INTEGER AS $$
BEGIN
    RETURN (
        SELECT COUNT(*)::INTEGER
        FROM public.account_link_requests
        WHERE target_school_id = p_school_id
        AND status = 'pending'
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION public.get_pending_link_requests_count IS 'Get count of pending link requests for admin dashboard';


-- ============================================================================
-- 9. AUDIT LOG FOR ACCOUNT LINKING
-- ============================================================================

-- Add new action types for audit logging
-- Note: These will be logged via the existing audit_log table with action_type field


-- ============================================================================
-- MIGRATION COMPLETE
-- ============================================================================

-- Add comment for documentation
COMMENT ON SCHEMA public IS 'Updated with recruiter self-service tables (universal_events, event_purchases, account_link_requests) and profile/school extensions for self-signup flow';
