#!/usr/bin/env python3
"""
Local Worker Server
Runs the worker API locally so you can test pipeline changes without deploying.
"""

import os
import sys
import uvicorn

# Add the app directory to Python path
sys.path.append('/Users/kregboyd/Applications/card-capture-api')

# Set environment variables for local development
os.environ.setdefault('PORT', '8081')  # Different port from main API

def run_local_worker():
    """Run the worker API locally"""
    print("🚀 Starting local worker server...")
    print("📍 Worker will run on http://localhost:8081")
    print("📋 Test endpoint: POST http://localhost:8081/process")
    print("💡 You can test with existing job_ids from your processing_jobs table")
    print()
    
    # Import and run the worker app
    from app.worker.worker_v2 import app
    
    # Run with auto-reload for development
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8081,
        reload=True,  # Auto-reload on code changes
        reload_dirs=["/Users/kregboyd/Applications/card-capture-api/app"]  # Watch for changes
    )

if __name__ == "__main__":
    run_local_worker()