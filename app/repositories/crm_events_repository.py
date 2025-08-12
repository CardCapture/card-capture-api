from typing import List, Dict, Any, Optional
from app.core.clients import get_supabase_client

class CRMEventsRepository:
    def __init__(self):
        self.client = get_supabase_client()
        self.table = "crm_events"
    
    async def list_events(self, school_id: str) -> List[Dict[str, Any]]:
        """List all CRM events for a school"""
        try:
            response = self.client.table(self.table).select("*").eq("school_id", school_id).order("event_date").execute()
            return response.data
        except Exception as e:
            print(f"Error listing CRM events: {str(e)}")
            raise
    
    async def create_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new CRM event"""
        try:
            response = self.client.table(self.table).insert(event_data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error creating CRM event: {str(e)}")
            # Check if it's a unique constraint violation
            if "unique_crm_event_per_school" in str(e):
                raise ValueError("An event with this CRM ID already exists for your school")
            raise
    
    async def get_event(self, event_id: str, school_id: str) -> Optional[Dict[str, Any]]:
        """Get a single CRM event"""
        try:
            response = self.client.table(self.table).select("*").eq("id", event_id).eq("school_id", school_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error getting CRM event: {str(e)}")
            raise
    
    async def update_event(self, event_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing CRM event"""
        try:
            # Remove fields that shouldn't be updated
            updates.pop("id", None)
            updates.pop("created_at", None)
            updates.pop("school_id", None)  # Don't allow changing school
            
            response = self.client.table(self.table).update(updates).eq("id", event_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error updating CRM event: {str(e)}")
            if "unique_crm_event_per_school" in str(e):
                raise ValueError("An event with this CRM ID already exists for your school")
            raise
    
    async def delete_event(self, event_id: str) -> None:
        """Delete a CRM event"""
        try:
            self.client.table(self.table).delete().eq("id", event_id).execute()
        except Exception as e:
            print(f"Error deleting CRM event: {str(e)}")
            raise
    
    async def bulk_delete_events(self, event_ids: List[str], school_id: str) -> int:
        """Bulk delete CRM events"""
        try:
            response = self.client.table(self.table).delete().in_("id", event_ids).eq("school_id", school_id).execute()
            return len(response.data) if response.data else 0
        except Exception as e:
            print(f"Error bulk deleting CRM events: {str(e)}")
            raise
    
    async def get_event_by_crm_id(self, school_id: str, crm_event_id: str) -> Optional[Dict[str, Any]]:
        """Get an event by its CRM ID"""
        try:
            response = self.client.table(self.table).select("*").eq("school_id", school_id).eq("crm_event_id", crm_event_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error getting CRM event by CRM ID: {str(e)}")
            raise
    
    async def search_events(self, school_id: str, query: str) -> List[Dict[str, Any]]:
        """Search events by name or CRM ID"""
        try:
            # Search in both name and crm_event_id fields
            response = self.client.table(self.table).select("*").eq("school_id", school_id).or_(f"name.ilike.%{query}%,crm_event_id.ilike.%{query}%").limit(10).execute()
            return response.data
        except Exception as e:
            print(f"Error searching CRM events: {str(e)}")
            raise
    
    async def bulk_upsert_events(self, events_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Bulk create/update events using upsert"""
        try:
            print(f"🔄 Upserting {len(events_data)} events...")
            
            # Use Supabase upsert with on_conflict for the unique constraint
            response = self.client.table(self.table).upsert(
                events_data,
                on_conflict="school_id,crm_event_id"  # Match the unique constraint
            ).execute()
            
            print(f"✅ Upserted {len(response.data)} events")
            return response.data
        except Exception as e:
            print(f"❌ Error bulk upserting CRM events: {str(e)}")
            raise