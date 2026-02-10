-- ============================================================================
-- Add Inquiry Card Mailing Address Fields to Universal Events
-- Allows event creators to specify where to mail inquiry cards
-- ============================================================================

-- Mailing address fields for inquiry cards (can be same as event address or different)
ALTER TABLE public.universal_events
    ADD COLUMN IF NOT EXISTS inquiry_cards_same_as_event_address BOOLEAN DEFAULT TRUE;

ALTER TABLE public.universal_events
    ADD COLUMN IF NOT EXISTS inquiry_cards_address TEXT;

ALTER TABLE public.universal_events
    ADD COLUMN IF NOT EXISTS inquiry_cards_city TEXT;

ALTER TABLE public.universal_events
    ADD COLUMN IF NOT EXISTS inquiry_cards_state TEXT;

ALTER TABLE public.universal_events
    ADD COLUMN IF NOT EXISTS inquiry_cards_zip TEXT;

ALTER TABLE public.universal_events
    ADD COLUMN IF NOT EXISTS inquiry_cards_attention TEXT;

-- Add comments for documentation
COMMENT ON COLUMN public.universal_events.inquiry_cards_same_as_event_address IS 'If true, use event address for mailing inquiry cards';
COMMENT ON COLUMN public.universal_events.inquiry_cards_address IS 'Street address for mailing inquiry cards (if different from event)';
COMMENT ON COLUMN public.universal_events.inquiry_cards_city IS 'City for mailing inquiry cards';
COMMENT ON COLUMN public.universal_events.inquiry_cards_state IS 'State for mailing inquiry cards';
COMMENT ON COLUMN public.universal_events.inquiry_cards_zip IS 'ZIP code for mailing inquiry cards';
COMMENT ON COLUMN public.universal_events.inquiry_cards_attention IS 'Attention/recipient name for mailing inquiry cards';
