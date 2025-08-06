#!/bin/bash

# Test Pipeline with Curl Commands
# Usage: ./test_pipeline_curl.sh [job_id]

echo "🧪 CardCapture Pipeline Local Testing"
echo "====================================="

# Check if local worker is running
echo "📡 Checking if local worker is running..."
if curl -s http://localhost:8081/ > /dev/null; then
    echo "✅ Local worker is running on port 8081"
else
    echo "❌ Local worker is not running!"
    echo "💡 Start it with: python run_local_worker.py"
    exit 1
fi

# Get job_id from argument or prompt user
if [ -n "$1" ]; then
    JOB_ID="$1"
else
    echo ""
    echo "📝 Enter a job_id from your processing_jobs table:"
    read -r JOB_ID
fi

if [ -z "$JOB_ID" ]; then
    echo "❌ No job_id provided!"
    exit 1
fi

echo ""
echo "🚀 Testing pipeline with job_id: $JOB_ID"
echo "⏳ Processing..."

# Send request to local worker
RESPONSE=$(curl -s -X POST http://localhost:8081/process \
  -H "Content-Type: application/json" \
  -d "{\"job_id\": \"$JOB_ID\", \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)\"}")

echo ""
echo "📋 Response:"
echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"

echo ""
echo "✅ Test completed!"
echo "💡 Check worker logs at: worker_v2_debug.log"