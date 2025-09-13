#!/bin/bash

echo "=========================================="
echo "TESTING PHOTOROOM IN PRODUCTION/STAGING"
echo "=========================================="

echo ""
echo "1. CHECKING PRODUCTION WORKER ENVIRONMENT:"
echo "   Looking for PhotoRoom environment variables..."
gcloud run services describe card-capture-worker-v2 --region us-central1 --format="yaml" | grep -A 5 -B 5 "PHOTO_ROOM\|USE_PHOTOROOM" || echo "   No PhotoRoom env vars found"

echo ""
echo "2. CHECKING STAGING WORKER ENVIRONMENT:"
echo "   Looking for PhotoRoom environment variables..."
gcloud run services describe card-capture-worker-v2-staging --region us-central1 --format="yaml" | grep -A 5 -B 5 "PHOTO_ROOM\|USE_PHOTOROOM" || echo "   No PhotoRoom env vars found"

echo ""
echo "3. TO TEST IN PRODUCTION:"
echo "   a) Upload a card photo through the frontend"
echo "   b) Monitor logs with this command:"
echo "      gcloud logging read 'resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"card-capture-worker-v2\" AND (textPayload:\"PhotoRoom\" OR textPayload:\"Attempting PhotoRoom\" OR textPayload:\"PhotoRoom processing successful\" OR textPayload:\"Processing image through full trimming pipeline\")' --limit=10 --format=\"value(textPayload)\" --project=gen-lang-client-0493571343"

echo ""
echo "4. TO TEST IN STAGING:"
echo "   a) Upload a card photo through staging frontend"
echo "   b) Monitor logs with this command:"
echo "      gcloud logging read 'resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"card-capture-worker-v2-staging\" AND (textPayload:\"PhotoRoom\" OR textPayload:\"Attempting PhotoRoom\" OR textPayload:\"PhotoRoom processing successful\" OR textPayload:\"Processing image through full trimming pipeline\")' --limit=10 --format=\"value(textPayload)\" --project=gen-lang-client-0493571343"

echo ""
echo "5. SIGNS PHOTOROOM IS WORKING:"
echo "   ✅ '🎨 Attempting PhotoRoom background removal...' in logs"
echo "   ✅ '✅ PhotoRoom processing successful' in logs"
echo "   ✅ '[PhotoRoom] Success! Processed image:' in logs"
echo "   ✅ 'Processing image through full trimming pipeline' in logs"

echo ""
echo "6. SIGNS PHOTOROOM IS NOT WORKING:"
echo "   ❌ 'Using cropped image from DocAI' in logs (old behavior)"
echo "   ❌ '⚠️ PhotoRoom failed or unavailable' in logs"
echo "   ❌ No PhotoRoom messages at all in logs"

echo ""
echo "=========================================="
echo "READY FOR TESTING!"
echo "=========================================="