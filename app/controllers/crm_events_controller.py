from typing import List, Dict, Any
from fastapi import HTTPException, UploadFile
from app.services.crm_events_service import CRMEventsService
import csv
import io
from datetime import datetime, date

service = CRMEventsService()

async def list_crm_events_controller(user: dict) -> dict:
    """List all CRM events for the user's school"""
    try:
        school_id = user.get("school_id")
        if not school_id:
            raise HTTPException(status_code=403, detail="User must belong to a school")
        
        events = await service.list_events(school_id)
        return {"success": True, "events": events}
    except Exception as e:
        print(f"Error listing CRM events: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def create_crm_event_controller(user: dict, payload: dict) -> dict:
    """Create a single CRM event"""
    try:
        school_id = user.get("school_id")
        if not school_id:
            raise HTTPException(status_code=403, detail="User must belong to a school")
        
        # Check for admin role
        if 'admin' not in user.get('role', []):
            raise HTTPException(status_code=403, detail="Only admins can create events")
        
        # Validate required fields
        required_fields = ["name", "event_date", "crm_event_id"]
        for field in required_fields:
            if field not in payload:
                raise HTTPException(status_code=400, detail=f"Missing required field: {field}")
        
        event_data = {
            "school_id": school_id,
            "name": payload["name"],
            "event_date": payload["event_date"],
            "crm_event_id": payload["crm_event_id"],
            "source": payload.get("source", "manual"),
            "metadata": payload.get("metadata", {})
        }
        
        event = await service.create_event(event_data)
        return {"success": True, "event": event}
    except Exception as e:
        print(f"Error creating CRM event: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def update_crm_event_controller(user: dict, event_id: str, payload: dict) -> dict:
    """Update a CRM event"""
    try:
        school_id = user.get("school_id")
        if not school_id:
            raise HTTPException(status_code=403, detail="User must belong to a school")
        
        # Check for admin role
        if 'admin' not in user.get('role', []):
            raise HTTPException(status_code=403, detail="Only admins can update events")
        
        event = await service.update_event(event_id, school_id, payload)
        return {"success": True, "event": event}
    except Exception as e:
        print(f"Error updating CRM event: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def delete_crm_event_controller(user: dict, event_id: str) -> dict:
    """Delete a single CRM event"""
    try:
        school_id = user.get("school_id")
        if not school_id:
            raise HTTPException(status_code=403, detail="User must belong to a school")
        
        # Check for admin role
        if 'admin' not in user.get('role', []):
            raise HTTPException(status_code=403, detail="Only admins can delete events")
        
        await service.delete_event(event_id, school_id)
        return {"success": True, "message": "Event deleted successfully"}
    except Exception as e:
        print(f"Error deleting CRM event: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def bulk_delete_crm_events_controller(user: dict, event_ids: List[str]) -> dict:
    """Bulk delete CRM events"""
    try:
        school_id = user.get("school_id")
        if not school_id:
            raise HTTPException(status_code=403, detail="User must belong to a school")
        
        # Check for admin role
        if 'admin' not in user.get('role', []):
            raise HTTPException(status_code=403, detail="Only admins can delete events")
        
        deleted_count = await service.bulk_delete_events(event_ids, school_id)
        return {"success": True, "deleted_count": deleted_count}
    except Exception as e:
        print(f"Error bulk deleting CRM events: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def upload_csv_controller(user: dict, file: UploadFile, mapping: dict) -> dict:
    """Process CSV upload with column mapping"""
    try:
        print(f"📤 Starting CSV upload for user {user.get('email', 'unknown')}")
        
        school_id = user.get("school_id")
        if not school_id:
            raise HTTPException(status_code=403, detail="User must belong to a school")
        
        # Check for admin role
        if 'admin' not in user.get('role', []):
            raise HTTPException(status_code=403, detail="Only admins can upload events")
        
        # Read and parse CSV
        contents = await file.read()
        csv_text = contents.decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(csv_text))
        # Normalize header names to avoid BOM/whitespace/quotes mismatches with FE mapping
        if csv_reader.fieldnames:
            csv_reader.fieldnames = [
                (fn or "").strip().replace("\ufeff", "").strip('"').strip("'") for fn in csv_reader.fieldnames
            ]
        
        # Convert to list to get total count, then filter out blank rows
        raw_rows = list(csv_reader)
        raw_total = len(raw_rows)
        # Remove rows that are entirely empty/whitespace
        csv_rows = [
            row for row in raw_rows
            if row and any(str(value or "").strip() for value in row.values())
        ]
        total_rows = len(csv_rows)
        print(f"📊 Processing {total_rows} CSV rows (received {raw_total}, skipped {raw_total - total_rows} blank rows)")
        
        # Process each row
        results = {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": []
        }
        
        # Parse and validate all rows first
        print("🔍 Parsing and validating CSV data...")
        print(f"📋 Received mapping: {mapping}")
        print(f"📋 CSV headers (first row): {list(csv_rows[0].keys()) if csv_rows else 'No rows'}")
        events_to_create = []
        
        # Pre-normalize mapping keys for consistent lookup
        norm_map = {
            key: (mapping.get(key, "") or "").strip()
            for key in ("name", "date", "crm_id")
        }
        norm_map = {k: v.replace("\ufeff", "") for k, v in norm_map.items()}
        print(f"📋 Normalized mapping: {norm_map}")

        for row_num, row in enumerate(csv_rows, start=2):
            try:
                # Normalize row keys (trim and strip BOM and quotes)
                norm_row = { (k or "").strip().replace("\ufeff", "").strip('"').strip("'"): (v or "") for k, v in row.items() }
                
                # Debug output for first row
                if row_num == 2:
                    print(f"🔍 First data row (normalized): {norm_row}")
                    print(f"🔍 Looking for name in column: '{norm_map.get('name', 'NOT SET')}'")
                    print(f"🔍 Looking for date in column: '{norm_map.get('date', 'NOT SET')}'")
                    print(f"🔍 Looking for crm_id in column: '{norm_map.get('crm_id', 'NOT SET')}'")
                
                # Map columns based on user's mapping
                # Only try to get values if the mapping column name is not empty
                event_data = {
                    "school_id": school_id,
                    "name": norm_row.get(norm_map["name"], "").strip() if norm_map.get("name") else "",
                    "event_date": norm_row.get(norm_map["date"], "").strip() if norm_map.get("date") else "",
                    "crm_event_id": norm_row.get(norm_map["crm_id"], "").strip() if norm_map.get("crm_id") else "",
                    "source": "csv"
                }
                
                # Validate required fields
                if not event_data["name"] or not event_data["event_date"]:
                    results["errors"].append({
                        "row": row_num,
                        "error": "Missing required fields (name and date)"
                    })
                    continue
                
                # Handle blank CRM Event ID
                if not event_data["crm_event_id"]:
                    safe_name = ''.join(c for c in event_data['name'] if c.isalnum() or c in (' ', '-')).strip()
                    safe_name = safe_name.replace(' ', '-').lower()[:20]
                    event_data["crm_event_id"] = f"no-id-{row_num}-{safe_name}"
                    event_data["metadata"] = {"note": "No CRM ID provided - auto-generated placeholder"}
                
                # Parse and validate date (handle both date-only and date+time formats)
                parsed_date = None
                date_string = event_data["event_date"]
                
                # If it contains time, split to get just the date part
                if ' ' in date_string:
                    date_string = date_string.split(' ')[0]
                
                # Try various date formats - use date() to avoid timezone issues
                for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%Y/%m/%d', '%m/%d/%y', '%d/%m/%y']:
                    try:
                        parsed_datetime = datetime.strptime(date_string, fmt)
                        # Convert to date object to avoid any timezone interpretation issues
                        parsed_date = parsed_datetime.date()
                        event_data["event_date"] = parsed_date.strftime('%Y-%m-%d')
                        break
                    except ValueError:
                        continue
                
                if not parsed_date:
                    results["errors"].append({
                        "row": row_num,
                        "error": f"Invalid date format: {event_data['event_date']} (tried: {date_string})"
                    })
                    continue
                    
                events_to_create.append(event_data)
                
            except Exception as row_error:
                results["errors"].append({
                    "row": row_num,
                    "error": str(row_error)
                })
        
        print(f"✅ Parsed {len(events_to_create)} valid events, {len(results['errors'])} errors")
        
        # Bulk create events using upsert (insert or update)
        if events_to_create:
            print("🚀 Bulk creating events...")
            try:
                created_events = await service.bulk_upsert_events(events_to_create)
                results["created"] = len(created_events)
                print(f"✅ Successfully created {results['created']} events")
            except Exception as e:
                print(f"❌ Bulk create error: {str(e)}")
                # Fallback to individual creation if bulk fails
                print("🔄 Falling back to individual creation...")
                for event_data in events_to_create:
                    try:
                        await service.create_event(event_data)
                        results["created"] += 1
                    except Exception as individual_error:
                        results["errors"].append({
                            "row": "unknown",
                            "error": f"Failed to create {event_data.get('name', 'unknown')}: {str(individual_error)}"
                        })
        
        # Log summary
        processed_total = results["created"] + results["updated"] + results["skipped"] + len(results["errors"])
        print(f"CSV Import Summary - Total rows: {processed_total}, Created: {results['created']}, Updated: {results['updated']}, Skipped: {results['skipped']}, Errors: {len(results['errors'])}")
        
        response_data = {
            "success": True,
            "message": f"Import completed: {results['created']} created, {results['updated']} updated, {results['skipped']} unchanged, {len(results['errors'])} errors",
            **results
        }
        print(f"Returning response: {response_data}")
        return response_data
        
    except Exception as e:
        print(f"Error processing CSV upload: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def search_crm_events_controller(user: dict, query: str) -> dict:
    """Search CRM events for type-ahead"""
    try:
        school_id = user.get("school_id")
        if not school_id:
            raise HTTPException(status_code=403, detail="User must belong to a school")
        
        events = await service.search_events(school_id, query)
        return {"success": True, "results": events}
    except Exception as e:
        print(f"Error searching CRM events: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))