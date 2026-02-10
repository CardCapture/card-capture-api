-- Add event_id column to event_purchases to link the created event
-- This allows easy lookup after payment completion

ALTER TABLE public.event_purchases
    ADD COLUMN IF NOT EXISTS event_id UUID REFERENCES public.events(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_event_purchases_event_id ON public.event_purchases(event_id)
    WHERE event_id IS NOT NULL;

COMMENT ON COLUMN public.event_purchases.event_id IS 'Reference to the event created when purchase was completed';
