#!/bin/bash

# Set default values
REGION="us-central1"
TIMEOUT="540s"  # 9 minutes (max for 1st gen, adjust to 3600s for 2nd gen)
MEMORY="2048MB"
MIN_INSTANCES=0
MAX_INSTANCES=10

# Ensure you're in the functions directory
cd "$(dirname "$0")"

# Deploy HTTP Trigger Function
gcloud functions deploy card-capture-processor \
  --gen2 \
  --runtime=python311 \
  --region=$REGION \
  --source=. \
  --entry-point=process_card_http \
  --trigger-http \
  --allow-unauthenticated \
  --timeout=$TIMEOUT \
  --memory=$MEMORY \
  --min-instances=$MIN_INSTANCES \
  --max-instances=$MAX_INSTANCES \
  --set-env-vars="PROJECT_ID=$(gcloud config get-value project)"

# Deploy Pub/Sub Trigger Function (uncomment if needed)
# TOPIC_NAME="card-capture-jobs"
# 
# # Create Pub/Sub topic if it doesn't exist
# gcloud pubsub topics create $TOPIC_NAME --quiet || true
# 
# gcloud functions deploy card-capture-processor-pubsub \
#   --gen2 \
#   --runtime=python311 \
#   --region=$REGION \
#   --source=. \
#   --entry-point=process_card_pubsub \
#   --trigger-topic=$TOPIC_NAME \
#   --timeout=$TIMEOUT \
#   --memory=$MEMORY \
#   --min-instances=$MIN_INSTANCES \
#   --max-instances=$MAX_INSTANCES \
#   --set-env-vars="PROJECT_ID=$(gcloud config get-value project)"

echo "Deployment complete!" 