from typing import List, Dict, Any, Optional
from app.repositories.crm_events_repository import CRMEventsRepository

class CRMEventsService:
    def __init__(self):
        self.repository = CRMEventsRepository()
    
    async def list_events(self, school_id: str) -> List[Dict[str, Any]]:
        """List all CRM events for a school"""
        return await self.repository.list_events(school_id)
    
    async def create_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new CRM event"""
        return await self.repository.create_event(event_data)
    
    async def update_event(self, event_id: str, school_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing CRM event"""
        # Ensure the event belongs to the school
        existing = await self.repository.get_event(event_id, school_id)
        if not existing:
            raise ValueError("Event not found or doesn't belong to your school")
        
        return await self.repository.update_event(event_id, updates)
    
    async def delete_event(self, event_id: str, school_id: str) -> None:
        """Delete a CRM event"""
        # Ensure the event belongs to the school
        existing = await self.repository.get_event(event_id, school_id)
        if not existing:
            raise ValueError("Event not found or doesn't belong to your school")
        
        await self.repository.delete_event(event_id)
    
    async def bulk_delete_events(self, event_ids: List[str], school_id: str) -> int:
        """Bulk delete CRM events"""
        return await self.repository.bulk_delete_events(event_ids, school_id)
    
    async def get_event_by_crm_id(self, school_id: str, crm_event_id: str) -> Optional[Dict[str, Any]]:
        """Get an event by its CRM ID"""
        return await self.repository.get_event_by_crm_id(school_id, crm_event_id)
    
    async def search_events(self, school_id: str, query: str) -> List[Dict[str, Any]]:
        """Search events by name or CRM ID"""
        return await self.repository.search_events(school_id, query)
    
    async def bulk_upsert_events(self, events_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Bulk create/update events using upsert"""
        return await self.repository.bulk_upsert_events(events_data)