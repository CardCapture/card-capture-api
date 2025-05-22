# CardCapture Cloud Function

This Cloud Function replaces the worker service for processing card images using Google Doc AI and Gemini.

## Features

- Processes card images using Google Doc AI and Gemini
- Runs OpenCV for image trimming
- Supports both HTTP and Pub/Sub triggers
- Handles retries for failed jobs
- Updates job status in Supabase
- Syncs card field preferences

## Deployment

### Prerequisites

1. Google Cloud CLI installed
2. Authenticated with `gcloud auth login`
3. Project selected with `gcloud config set project YOUR_PROJECT_ID`

### Deploy the Function

1. Make the deployment script executable:
   ```
   chmod +x deploy.sh
   ```

2. Run the deployment script:
   ```
   ./deploy.sh
   ```

This will deploy the Cloud Function with the following configuration:
- Gen 2 runtime
- Python 3.11
- 2GB memory
- 9-minute timeout (can be increased up to 60 minutes for Gen 2)
- HTTP trigger

## Usage

### HTTP Trigger

Send a POST request to the Cloud Function URL with a JSON body containing the job ID:

```json
{
  "job_id": "your-job-id"
}
```

### Pub/Sub Trigger (if enabled)

Publish a message to the Pub/Sub topic with a JSON payload containing the job ID:

```json
{
  "job_id": "your-job-id"
}
```

## Environment Variables

The Cloud Function automatically sets the following environment variables:
- `PROJECT_ID`: Your Google Cloud project ID

Add any additional environment variables needed by your application in the `deploy.sh` script.

## Local Testing

To test the function locally, install the Functions Framework:

```
pip install -r requirements.txt
```

Then run:

```
functions-framework --target=process_card_http
```

Send a test request:

```
curl -X POST http://localhost:8080 -H "Content-Type: application/json" -d '{"job_id":"your-job-id"}'
``` 