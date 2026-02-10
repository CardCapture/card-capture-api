-- Set up pg_cron job to trigger card scan notifications every hour
-- This will call the Supabase edge function which then calls the API

-- Note: This cron job will be created manually in Supabase dashboard or via SQL
-- The edge function URL will be specific to your Supabase project

-- Instructions for setting up the cron job:
-- 1. Deploy the send-card-notifications edge function first
-- 2. Get the edge function URL from Supabase dashboard
-- 3. Run the following SQL in the Supabase SQL editor:

/*
SELECT cron.schedule(
  'send-card-notifications-hourly',  -- Job name
  '0 * * * *',                        -- Cron expression: every hour at minute 0
  $$
    SELECT
      net.http_post(
        url := 'https://[YOUR-PROJECT-REF].supabase.co/functions/v1/send-card-notifications',
        headers := jsonb_build_object(
          'Content-Type', 'application/json',
          'Authorization', 'Bearer [YOUR-ANON-KEY]'
        ),
        body := jsonb_build_object('timestamp', now())
      ) as request_id;
  $$
);
*/

-- To verify the cron job is created:
-- SELECT * FROM cron.job;

-- To see cron job run history:
-- SELECT * FROM cron.job_run_details ORDER BY start_time DESC LIMIT 10;

-- To unschedule the job (if needed):
-- SELECT cron.unschedule('send-card-notifications-hourly');

-- Note: Make sure pg_cron extension is enabled in your Supabase project
-- You can check with: SELECT * FROM pg_extension WHERE extname = 'pg_cron';
