-- ============================================================================
-- Add Inquiry Cards Fields to Universal Events
-- Allows event creators to request paper inquiry cards for their events
-- ============================================================================

-- Add needs_inquiry_cards boolean column
ALTER TABLE public.universal_events
    ADD COLUMN IF NOT EXISTS needs_inquiry_cards BOOLEAN DEFAULT FALSE;

-- Add expected_students integer column
ALTER TABLE public.universal_events
    ADD COLUMN IF NOT EXISTS expected_students INTEGER;

-- Add comment for documentation
COMMENT ON COLUMN public.universal_events.needs_inquiry_cards IS 'Whether the event organizer has requested paper inquiry cards';
COMMENT ON COLUMN public.universal_events.expected_students IS 'Expected number of students attending (used for inquiry card quantity)';

-- Index for filtering events that need inquiry cards
CREATE INDEX IF NOT EXISTS idx_universal_events_needs_inquiry_cards
    ON public.universal_events(needs_inquiry_cards)
    WHERE needs_inquiry_cards = TRUE;
