from typing import List, Dict, Any, Optional
from app.core.clients import get_supabase_client

class HighSchoolsRepository:
    def __init__(self):
        self.client = get_supabase_client()
        self.table = "high_schools_directory"
    
    def search_schools(self, query: str, limit: int = 10, state: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search high schools by name with optional state filter using fuzzy matching"""
        try:
            results = []
            
            def build_base_query():
                """Build base query with common filters"""
                qb = self.client.table(self.table).select(
                    "id, name, city, state, phone, website, district_name, school_type, level, ceeb_code, source"
                ).limit(limit * 3)  # Get more results for better fuzzy matching
                
                if state:
                    qb = qb.eq("state", state.upper())
                
                return qb
            
            # Strategy 1: Direct substring match
            try:
                query_builder = build_base_query()
                direct_results = query_builder.ilike("name", f"%{query}%").execute()
                results.extend(direct_results.data or [])
            except Exception as e:
                print(f"Strategy 1 failed: {e}")
                pass
            
            # Strategy 2: Search for individual words if query contains multiple words (but limit results)
            if len(query.split()) > 1 and len(results) < limit:
                words = [word.strip() for word in query.split() if len(word.strip()) > 2]
                # Reverse the order - often the most specific word is later in the query
                for word in reversed(words[:2]):  # Limit to 2 most significant words
                    if len(results) >= limit * 2:  # Don't add too many results
                        break
                    try:
                        query_builder = build_base_query() 
                        word_results = query_builder.ilike("name", f"%{word}%").limit(5).execute()  # Limit each word search
                        if word_results.data:
                            added_count = 0
                            for result in word_results.data:
                                # Avoid duplicates and limit additions
                                if not any(existing['id'] == result['id'] for existing in results) and added_count < 3:
                                    results.append(result)
                                    added_count += 1
                    except Exception as e:
                        continue
            
            # Strategy 3: If we have a city name in the query, try searching by city + school keywords
            # Look for common city-school patterns like "City School", "City High"
            query_lower = query.lower()
            potential_city = None
            
            # Extract potential city name if pattern matches
            if 'high' in query_lower or 'school' in query_lower:
                words = query.split()
                if len(words) >= 2:
                    # Try first word as potential city name
                    potential_city = words[0]
                    
            if potential_city and len(potential_city) > 3:
                try:
                    query_builder = build_base_query()
                    city_results = query_builder.ilike("city", f"%{potential_city}%").execute()
                    if city_results.data:
                        for result in city_results.data:
                            if not any(existing['id'] == result['id'] for existing in results):
                                results.append(result)
                except Exception as e:
                    pass
            
            # Remove duplicates and limit results
            unique_results = []
            seen_ids = set()
            for result in results:
                if result['id'] not in seen_ids:
                    unique_results.append(result)
                    seen_ids.add(result['id'])
                    
            # Don't sort - keep results in order of relevance (direct matches first)
            return unique_results[:limit]
            
        except Exception as e:
            print(f"Error searching high schools: {str(e)}")
            raise
    
    def get_school_by_id(self, school_id: str) -> Optional[Dict[str, Any]]:
        """Get a single school by ID"""
        try:
            response = self.client.table(self.table).select("*").eq("id", school_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error getting school by ID: {str(e)}")
            raise
    
    def get_schools_by_state(self, state: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get schools by state"""
        try:
            response = self.client.table(self.table).select(
                "id, name, city, state, phone, website, ceeb_code, source"
            ).eq("state", state.upper()).limit(limit).order("name").execute()
            return response.data
        except Exception as e:
            print(f"Error getting schools by state: {str(e)}")
            raise
    
    def get_school_count(self) -> int:
        """Get total count of schools in the directory"""
        try:
            response = self.client.table(self.table).select("count", count="exact").execute()
            return response.count
        except Exception as e:
            print(f"Error getting school count: {str(e)}")
            return 0