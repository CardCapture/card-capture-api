-- Add stripe_customer_id column to public.schools if it doesn't exist
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='schools' AND column_name='stripe_customer_id'
  ) THEN
    ALTER TABLE public.schools ADD COLUMN stripe_customer_id TEXT;
  END IF;
END $$; 