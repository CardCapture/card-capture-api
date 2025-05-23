# Processing Jobs Trigger Setup

This setup creates a database trigger that automatically calls a Cloud Run service whenever a new row is inserted into the `processing_jobs` table.

## Architecture

1. **Database Trigger**: Fires when a new row is inserted into `processing_jobs` table
2. **Edge Function**: Called by the trigger, makes HTTP request to Cloud Run service
3. **Cloud Run Service**: Processes the job with the provided `jobId`

## Files Created

- `functions/process-job-trigger/index.ts` - Edge function that calls Cloud Run service
- `migrations/20250523125506_create_processing_jobs_trigger.sql` - Creates the database trigger (local development)
- `migrations/20250523125507_create_processing_jobs_trigger_production.sql` - Production configuration

## Setup Instructions

### 1. Deploy the Edge Function

```bash
# Deploy the Edge function to Supabase
supabase functions deploy process-job-trigger
```

### 2. Apply Database Migrations

```bash
# Apply the migration to create the trigger
supabase db reset
# or if you prefer to apply specific migrations:
supabase migration up
```

### 3. Production Configuration

Before deploying to production, update the production migration file:

1. Replace `YOUR_SUPABASE_PROJECT_REF` in `migrations/20250523125507_create_processing_jobs_trigger_production.sql` with your actual Supabase project reference
2. Set the environment configuration in your production database:

```sql
-- Set environment to production
ALTER DATABASE postgres SET app.environment = 'production';
```

### 4. Configure Service Role Key

The trigger function needs access to the service role key to call the Edge function. Set this up in your Supabase dashboard:

1. Go to Project Settings > API
2. Copy the `service_role` key
3. Set it as a database setting:

```sql
-- Set the service role key (replace with your actual key)
ALTER DATABASE postgres SET app.settings.service_role_key = 'your-service-role-key-here';
```

## How It Works

1. When a new row is inserted into the `processing_jobs` table, the `processing_jobs_insert_trigger` fires
2. The trigger calls the `handle_processing_jobs_insert()` function
3. This function makes an HTTP POST request to the Edge function at `/functions/v1/process-job-trigger`
4. The Edge function receives the new row data and extracts the `jobId`
5. The Edge function makes an HTTP POST request to your Cloud Run service at:
   ```
   https://card-capture-worker-v2-878585200500.us-central1.run.app
   ```
6. The request body contains:
   ```json
   {
     "jobId": "the-job-id-from-the-new-row",
     "timestamp": "2025-05-23T12:55:06.123Z"
   }
   ```

## Testing

### Local Testing

1. Start Supabase locally:
   ```bash
   supabase start
   ```

2. Insert a test row into the `processing_jobs` table:
   ```sql
   INSERT INTO processing_jobs (id, status, data) 
   VALUES ('test-job-123', 'pending', '{"test": true}');
   ```

3. Check the Edge function logs:
   ```bash
   supabase functions logs process-job-trigger
   ```

### Production Testing

1. Insert a row in your production database
2. Monitor the Cloud Run service logs to verify the request is received
3. Check Supabase Edge function logs in the dashboard

## Troubleshooting

### Common Issues

1. **Permission Errors**: Ensure the `net` extension is enabled and permissions are granted
2. **Service Role Key Not Found**: Make sure the service role key is set as a database setting
3. **Edge Function Not Found**: Verify the function is deployed and the URL is correct
4. **Cloud Run Service Unreachable**: Check that the service is running and accessible

### Enable HTTP Extensions

If you get errors about the `net` schema, you may need to enable the HTTP extension:

```sql
-- Enable the http extension
CREATE EXTENSION IF NOT EXISTS http;

-- Create the net schema if it doesn't exist
CREATE SCHEMA IF NOT EXISTS net;

-- Grant usage
GRANT USAGE ON SCHEMA net TO authenticated, anon, service_role;
```

## Security Considerations

- The service role key is stored as a database setting and should be kept secure
- The Edge function validates incoming requests to ensure they contain valid job data
- Consider adding authentication to your Cloud Run service if it's not already protected
- Monitor logs for any suspicious activity

## Monitoring

- Edge function logs can be viewed in the Supabase dashboard or via CLI
- Cloud Run service logs can be viewed in Google Cloud Console
- Database trigger execution can be monitored through Supabase logs 