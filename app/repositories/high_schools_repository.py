from typing import List, Dict, Any, Optional
from app.core.clients import get_supabase_client
from app.utils.retry_utils import log_debug

class HighSchoolsRepository:
    def __init__(self):
        self.client = get_supabase_client()
        self.table = "high_schools_directory"
    
    def normalize_text(self, text: str) -> str:
        """Normalize text for better matching by removing apostrophes and other special characters"""
        # Remove apostrophes and replace with empty string
        normalized = text.replace("'", "").replace("'", "").replace("`", "")
        # Replace multiple spaces with single space
        normalized = " ".join(normalized.split())
        return normalized
    
    def search_schools(self, query: str, limit: int = 10, state: Optional[str] = None, city: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search high schools with multi-tier strategy:
        1. Same-state matches (prioritized)
        2. Exact name matches from other states
        3. High-confidence cross-state matches
        """
        try:
            results = []
            # Normalize the query to handle apostrophes
            normalized_query = self.normalize_text(query)

            def build_state_query(target_state: Optional[str] = None):
                """Build query with optional state filter"""
                qb = self.client.table(self.table).select(
                    "id, name, city, state, phone, website, district_name, school_type, level, ceeb_code, source"
                ).limit(limit * 3)

                if target_state:
                    qb = qb.eq("state", target_state.upper())

                return qb

            def build_base_query():
                """Build base query without state filter for cross-state search"""
                return self.client.table(self.table).select(
                    "id, name, city, state, phone, website, district_name, school_type, level, ceeb_code, source"
                ).limit(limit * 5)  # Get more results for cross-state matching
            
            def build_city_query(target_state: Optional[str] = None):
                """Build query with city filter for location-first search"""
                qb = self.client.table(self.table).select(
                    "id, name, city, state, phone, website, district_name, school_type, level, ceeb_code, source"
                ).limit(limit)

                if target_state:
                    qb = qb.eq("state", target_state.upper())
                if city:
                    qb = qb.ilike("city", f"%{city}%")

                return qb

            def calculate_similarity(school_name: str, query: str) -> float:
                """Calculate similarity between school name and query"""
                from difflib import SequenceMatcher
                return SequenceMatcher(None, school_name.lower(), query.lower()).ratio()

            def add_unique_results(new_results: List[Dict], priority_tier: int = 1):
                """Add results if not already present, with tier information"""
                for result in new_results:
                    if not any(existing['id'] == result['id'] for existing in results):
                        result['_search_tier'] = priority_tier  # Add tier info for sorting
                        results.append(result)

            # TIER 1: Same-state matches (highest priority)
            if state:
                # 1A: Local city matches first (if city provided)
                if city:
                    try:
                        city_query = build_city_query(state)
                        local_results = city_query.ilike("name", f"%{normalized_query}%").execute()
                        if local_results.data:
                            add_unique_results(local_results.data, priority_tier=1)
                            log_debug(f"Tier 1A: Found {len(local_results.data)} local matches in {city}, {state}", service="high_schools")
                    except Exception as e:
                        log_debug(f"Tier 1A city search failed: {e}", service="high_schools")

                # 1B: State-wide matches
                try:
                    state_query = build_state_query(state)
                    state_results = state_query.ilike("name", f"%{normalized_query}%").execute()
                    if state_results.data:
                        add_unique_results(state_results.data, priority_tier=1)
                        log_debug(f"Tier 1B: Found {len(state_results.data)} state matches in {state}", service="high_schools")

                    # Try original query if different
                    if query != normalized_query:
                        state_query_orig = build_state_query(state)
                        state_results_orig = state_query_orig.ilike("name", f"%{query}%").execute()
                        if state_results_orig.data:
                            add_unique_results(state_results_orig.data, priority_tier=1)
                except Exception as e:
                    log_debug(f"Tier 1B state search failed: {e}", service="high_schools")

            # TIER 2: Exact name matches from other states (if we need more results)
            if len([r for r in results if r.get('_search_tier', 1) == 1]) < limit:
                try:
                    # Search nationwide for exact matches
                    exact_query = build_base_query()
                    exact_results = exact_query.ilike("name", f"%{normalized_query}%").execute()

                    if exact_results.data:
                        # Filter for high-similarity matches from other states
                        for result in exact_results.data:
                            if result['state'] != (state or '').upper():  # Different state
                                similarity = calculate_similarity(result['name'], normalized_query)
                                if similarity >= 0.85:  # High similarity threshold
                                    if not any(existing['id'] == result['id'] for existing in results):
                                        result['_search_tier'] = 2  # Cross-state match
                                        result['_similarity'] = similarity
                                        results.append(result)

                        log_debug(f"Tier 2: Found cross-state exact matches", service="high_schools")
                except Exception as e:
                    log_debug(f"Tier 2 exact match search failed: {e}", service="high_schools")

            # TIER 3: Word-based matches for broader coverage
            if len(results) < limit and len(normalized_query.split()) > 1:
                words = [word.strip() for word in normalized_query.split() if len(word.strip()) > 2]
                # Focus on most significant words (often school-specific terms come last)
                for word in reversed(words[:2]):
                    if len(results) >= limit * 2:
                        break
                    try:
                        # First try same-state word matches
                        if state:
                            word_query = build_state_query(state)
                            word_results = word_query.ilike("name", f"%{word}%").limit(3).execute()
                            if word_results.data:
                                add_unique_results(word_results.data, priority_tier=3)

                        # Then try cross-state word matches (lower priority)
                        cross_word_query = build_base_query()
                        cross_word_results = cross_word_query.ilike("name", f"%{word}%").limit(2).execute()
                        if cross_word_results.data:
                            for result in cross_word_results.data:
                                if result['state'] != (state or '').upper():
                                    similarity = calculate_similarity(result['name'], normalized_query)
                                    if similarity >= 0.7:  # Lower threshold for word matches
                                        if not any(existing['id'] == result['id'] for existing in results):
                                            result['_search_tier'] = 4  # Cross-state word match
                                            result['_similarity'] = similarity
                                            results.append(result)
                    except Exception as e:
                        continue

            # Sort results by tier (1=same state, 2=cross-state exact, 3=same state word, 4=cross-state word)
            # Within each tier, maintain original order (which favors exact matches)
            def sort_key(result):
                tier = result.get('_search_tier', 1)
                similarity = result.get('_similarity', 1.0)
                return (tier, -similarity)  # Lower tier first, higher similarity first within tier

            results.sort(key=sort_key)

            # Clean up temporary fields and remove duplicates
            unique_results = []
            seen_ids = set()
            for result in results:
                if result['id'] not in seen_ids:
                    # Remove internal fields
                    result.pop('_search_tier', None)
                    result.pop('_similarity', None)
                    unique_results.append(result)
                    seen_ids.add(result['id'])

            log_debug(f"Final results: {len(unique_results)} schools found for '{query}'", service="high_schools")
            return unique_results[:limit]

        except Exception as e:
            log_debug(f"Error searching high schools: {str(e)}", service="high_schools")
            raise
    
    def get_school_by_id(self, school_id: str) -> Optional[Dict[str, Any]]:
        """Get a single school by ID"""
        try:
            response = self.client.table(self.table).select("*").eq("id", school_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            log_debug(f"Error getting school by ID: {str(e)}", service="high_schools")
            raise
    
    def get_schools_by_state(self, state: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get schools by state"""
        try:
            response = self.client.table(self.table).select(
                "id, name, city, state, phone, website, ceeb_code, source"
            ).eq("state", state.upper()).limit(limit).order("name").execute()
            return response.data
        except Exception as e:
            log_debug(f"Error getting schools by state: {str(e)}", service="high_schools")
            raise
    
    def get_school_count(self) -> int:
        """Get total count of schools in the directory"""
        try:
            response = self.client.table(self.table).select("count", count="exact").execute()
            return response.count
        except Exception as e:
            log_debug(f"Error getting school count: {str(e)}", service="high_schools")
            return 0