-- Fix mfa_rate_limits table: add missing columns that the trigger expects
-- The original migration used CREATE TABLE IF NOT EXISTS which was a no-op
-- since the baseline already created the table without these columns.
-- The trigger update_mfa_rate_limits_updated_at references updated_at but
-- the column never existed, causing error 42703 on every UPDATE.

ALTER TABLE public.mfa_rate_limits
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW(),
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
