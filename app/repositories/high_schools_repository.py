from typing import List, Dict, Any, Optional
from app.core.clients import get_supabase_client

class HighSchoolsRepository:
    def __init__(self):
        self.client = get_supabase_client()
        self.table = "high_schools_directory"
    
    async def search_schools(self, query: str, limit: int = 10, state: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search high schools by name with optional state filter"""
        try:
            # Build the query
            query_builder = self.client.table(self.table).select(
                "id, name, city, state, phone, website, district_name, school_type, level, ceeb_code, source"
            ).limit(limit)
            
            # Add name search - using ilike for case-insensitive partial matching
            query_builder = query_builder.ilike("name", f"%{query}%")
            
            # Add state filter if provided
            if state:
                query_builder = query_builder.eq("state", state.upper())
            
            # Order by name for consistent results
            query_builder = query_builder.order("name")
            
            response = query_builder.execute()
            return response.data
            
        except Exception as e:
            print(f"Error searching high schools: {str(e)}")
            raise
    
    async def get_school_by_id(self, school_id: str) -> Optional[Dict[str, Any]]:
        """Get a single school by ID"""
        try:
            response = self.client.table(self.table).select("*").eq("id", school_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error getting school by ID: {str(e)}")
            raise
    
    async def get_schools_by_state(self, state: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get schools by state"""
        try:
            response = self.client.table(self.table).select(
                "id, name, city, state, phone, website, ceeb_code, source"
            ).eq("state", state.upper()).limit(limit).order("name").execute()
            return response.data
        except Exception as e:
            print(f"Error getting schools by state: {str(e)}")
            raise
    
    async def get_school_count(self) -> int:
        """Get total count of schools in the directory"""
        try:
            response = self.client.table(self.table).select("count", count="exact").execute()
            return response.count
        except Exception as e:
            print(f"Error getting school count: {str(e)}")
            return 0