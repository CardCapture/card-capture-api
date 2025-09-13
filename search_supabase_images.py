#!/usr/bin/env python3
"""
Search Supabase storage for original vs trimmed images
"""
import os
import sys
from datetime import datetime, timezone

# Add the app directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up environment for staging
os.environ['SUPABASE_URL'] = 'https://ftlweumoajawitlszpqx.supabase.co'
os.environ['SUPABASE_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ0bHdldW1vYWphd2l0bHN6cHF4Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0MzI2NzE2MiwiZXhwIjoyMDU4ODQzMTYyfQ.SEsM-nY72fr_36jAN4Tjj_YL_8T0qOtCyKmV7kxQey8'
os.environ['SUPABASE_SERVICE_ROLE_KEY'] = os.environ['SUPABASE_KEY']

from app.core.clients import get_supabase_client

def search_recent_images():
    """Search for recent images in the processing_jobs table"""
    print("=" * 70)
    print("SEARCHING RECENT PROCESSING JOBS")
    print("=" * 70)
    
    try:
        supabase = get_supabase_client()
        
        # Search for recent processing jobs for ACU user
        user_id = "dee097cc-5926-4c1b-acec-b50ccb5313c9"
        
        # Get recent jobs
        response = supabase.table("processing_jobs").select(
            "id, user_id, image_path, trimmed_image_path, created_at, status"
        ).eq("user_id", user_id).order("created_at", desc=True).limit(10).execute()
        
        if response.data:
            print(f"Found {len(response.data)} recent processing jobs:")
            print()
            
            for i, job in enumerate(response.data, 1):
                print(f"📋 JOB {i}:")
                print(f"   ID: {job['id']}")
                print(f"   Created: {job['created_at']}")
                print(f"   Status: {job['status']}")
                print(f"   Original image: {job['image_path']}")
                print(f"   Trimmed image:  {job['trimmed_image_path']}")
                print()
                
                # Check if both images exist in storage
                if job['image_path']:
                    print(f"   🔍 Checking original image in storage...")
                    check_image_in_storage(job['image_path'])
                
                if job['trimmed_image_path']:
                    print(f"   🔍 Checking trimmed image in storage...")
                    check_image_in_storage(job['trimmed_image_path'])
                
                print("-" * 50)
            
            return response.data
        else:
            print("No recent processing jobs found")
            return []
            
    except Exception as e:
        print(f"❌ Error searching processing jobs: {e}")
        import traceback
        traceback.print_exc()
        return []

def check_image_in_storage(image_path):
    """Check if an image exists in Supabase storage"""
    if not image_path:
        print("     ⚠️ No image path provided")
        return False
    
    try:
        supabase = get_supabase_client()
        
        # Try to get the file info from storage
        bucket = "cards-uploads"
        response = supabase.storage.from_(bucket).get_public_url(image_path)
        
        if response:
            print(f"     ✅ Image exists: {response}")
            
            # Try to get file info/metadata
            try:
                file_info = supabase.storage.from_(bucket).list(
                    path="/".join(image_path.split("/")[:-1]),
                    options={"limit": 100}
                )
                
                # Find the specific file
                filename = image_path.split("/")[-1]
                for file in file_info:
                    if file['name'] == filename:
                        print(f"     📊 Size: {file.get('metadata', {}).get('size', 'unknown')} bytes")
                        print(f"     📅 Modified: {file.get('updated_at', 'unknown')}")
                        break
                        
            except Exception as meta_error:
                print(f"     ⚠️ Could not get file metadata: {meta_error}")
            
            return True
        else:
            print(f"     ❌ Image not found in storage")
            return False
            
    except Exception as e:
        print(f"     ❌ Error checking storage: {e}")
        return False

def search_storage_directly():
    """Search storage directly for recent images"""
    print("\n" + "=" * 70)
    print("SEARCHING STORAGE DIRECTLY")
    print("=" * 70)
    
    try:
        supabase = get_supabase_client()
        bucket = "cards-uploads"
        user_id = "dee097cc-5926-4c1b-acec-b50ccb5313c9"
        
        # Get today's date for path
        today = datetime.now().strftime("%Y-%m-%d")
        path = f"{user_id}/{today}"
        
        print(f"Searching in path: {path}")
        
        # List files in today's folder
        files = supabase.storage.from_(bucket).list(path=path, options={"limit": 50})
        
        if files:
            print(f"\nFound {len(files)} files in today's folder:")
            
            for file in files:
                file_path = f"{path}/{file['name']}"
                file_size = file.get('metadata', {}).get('size', 'unknown')
                file_time = file.get('updated_at', 'unknown')
                
                print(f"\n📸 {file['name']}")
                print(f"   Path: {file_path}")
                print(f"   Size: {file_size} bytes")
                print(f"   Modified: {file_time}")
                
                # Get public URL
                public_url = supabase.storage.from_(bucket).get_public_url(file_path)
                print(f"   URL: {public_url}")
                
            return files
        else:
            print(f"No files found in {path}")
            return []
            
    except Exception as e:
        print(f"❌ Error searching storage: {e}")
        import traceback
        traceback.print_exc()
        return []

def compare_image_urls():
    """Get the URLs that would be shown in UI vs actual processed images"""
    print("\n" + "=" * 70)
    print("CHECKING UI IMAGE DISPLAY LOGIC")
    print("=" * 70)
    
    try:
        supabase = get_supabase_client()
        
        # Get the most recent review record for ACU user
        user_id = "dee097cc-5926-4c1b-acec-b50ccb5313c9"
        
        response = supabase.table("reviews").select(
            "id, image_path, trimmed_image_path, created_at"
        ).eq("user_id", user_id).order("created_at", desc=True).limit(5).execute()
        
        if response.data:
            print(f"Found {len(response.data)} recent review records:")
            
            for i, review in enumerate(response.data, 1):
                print(f"\n📋 REVIEW {i}:")
                print(f"   ID: {review['id']}")
                print(f"   Created: {review['created_at']}")
                print(f"   Original image path: {review['image_path']}")
                print(f"   Trimmed image path:  {review['trimmed_image_path']}")
                
                # Generate the URLs that would be shown
                if review['image_path']:
                    original_url = supabase.storage.from_("cards-uploads").get_public_url(review['image_path'])
                    print(f"   📷 Original URL: {original_url}")
                
                if review['trimmed_image_path']:
                    trimmed_url = supabase.storage.from_("cards-uploads").get_public_url(review['trimmed_image_path'])
                    print(f"   ✂️ Trimmed URL:  {trimmed_url}")
                    
                    # This is what the UI should be showing!
                    print(f"   🎯 UI should show: {trimmed_url}")
                else:
                    print(f"   ⚠️ No trimmed image path - UI will show original")
        else:
            print("No recent review records found")
            
    except Exception as e:
        print(f"❌ Error checking reviews: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Search for images and compare original vs trimmed"""
    print("Searching Supabase storage for original vs trimmed images...")
    print("This will help determine if PhotoRoom is working but UI shows wrong image.\n")
    
    # Search processing jobs
    jobs = search_recent_images()
    
    # Search storage directly
    files = search_storage_directly()
    
    # Check what UI would show
    compare_image_urls()
    
    print("\n" + "=" * 70)
    print("ANALYSIS")
    print("=" * 70)
    
    if jobs:
        latest_job = jobs[0]
        print(f"📋 Most recent job:")
        print(f"   Original: {latest_job['image_path']}")
        print(f"   Trimmed:  {latest_job['trimmed_image_path']}")
        
        if latest_job['trimmed_image_path']:
            print(f"\n✅ Trimmed image exists in database")
            print(f"🎯 UI should display the TRIMMED image, not the original")
            print(f"\nIf you're seeing the green background, check:")
            print(f"1. Is the UI using 'trimmed_image_path' or 'image_path'?")
            print(f"2. Are both images actually different?")
            print(f"3. Is the frontend caching the original image?")
        else:
            print(f"\n❌ No trimmed image path - PhotoRoom processing may have failed")
    
    print(f"\n🔍 To manually check the images:")
    print(f"1. Copy the URLs above")
    print(f"2. Open them in a browser") 
    print(f"3. Compare original vs trimmed")
    print(f"4. The trimmed one should have background removed")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    main()