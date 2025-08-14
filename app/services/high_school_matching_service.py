from typing import Dict, Any, List, Optional, Tuple
from difflib import SequenceMatcher
import re
from app.repositories.high_schools_repository import HighSchoolsRepository
from app.utils.retry_utils import log_debug

class HighSchoolMatchingService:
    def __init__(self):
        self.repo = HighSchoolsRepository()
        
        # Common abbreviations and their expansions
        self.abbreviations = {
            'hs': 'high school',
            'h.s.': 'high school',
            'sr': 'senior',
            'jr': 'junior',
            'elem': 'elementary',
            'intl': 'international',
            'acad': 'academy',
            'prep': 'preparatory',
            'cath': 'catholic',
            'tech': 'technical',
            'sci': 'science',
            'arts': 'arts',
            'st': 'saint',
            'mt': 'mount',
            'n': 'north',
            's': 'south',
            'e': 'east',
            'w': 'west',
            'ne': 'northeast',
            'nw': 'northwest',
            'se': 'southeast',
            'sw': 'southwest'
        }
        
        # Common words to ignore in matching
        self.stop_words = {'the', 'of', 'and', 'at', 'in', 'for', 'school', 'high', 'public', 'private'}
    
    def normalize_school_name(self, name: str) -> str:
        """Normalize school name for better matching"""
        if not name:
            return ""
            
        # Convert to lowercase
        normalized = name.lower().strip()
        
        # Remove special characters but keep spaces
        normalized = re.sub(r'[^\w\s-]', '', normalized)
        
        # Expand abbreviations
        words = normalized.split()
        expanded_words = []
        for word in words:
            if word in self.abbreviations:
                expanded_words.append(self.abbreviations[word])
            else:
                expanded_words.append(word)
        
        normalized = ' '.join(expanded_words)
        
        # Remove extra spaces
        normalized = ' '.join(normalized.split())
        
        return normalized
    
    def calculate_similarity_score(self, query: str, candidate: str, candidate_data: Dict[str, Any] = None) -> float:
        """
        Calculate similarity score between query and candidate school name
        
        Args:
            query: The search query (from Gemini extraction)
            candidate: The candidate school name from database
            candidate_data: Additional school data (city, state) for context scoring
            
        Returns:
            Similarity score between 0 and 1
        """
        # Normalize both strings
        query_normalized = self.normalize_school_name(query)
        candidate_normalized = self.normalize_school_name(candidate)
        
        # Base similarity using SequenceMatcher
        base_similarity = SequenceMatcher(None, query_normalized, candidate_normalized).ratio()
        
        # Check for exact match (after normalization)
        if query_normalized == candidate_normalized:
            return 1.0
        
        # Check if one contains the other (partial match)
        if query_normalized in candidate_normalized or candidate_normalized in query_normalized:
            base_similarity = max(base_similarity, 0.85)
        
        # Token-based matching for better handling of word order differences
        query_tokens = set(query_normalized.split()) - self.stop_words
        candidate_tokens = set(candidate_normalized.split()) - self.stop_words
        
        if query_tokens and candidate_tokens:
            # Jaccard similarity
            intersection = query_tokens.intersection(candidate_tokens)
            union = query_tokens.union(candidate_tokens)
            token_similarity = len(intersection) / len(union) if union else 0
            
            # Weight token similarity higher if most important words match
            if len(intersection) >= min(3, len(query_tokens)):
                token_similarity = min(token_similarity * 1.2, 1.0)
            
            # Combine base and token similarity
            combined_score = (base_similarity * 0.6) + (token_similarity * 0.4)
        else:
            combined_score = base_similarity
        
        # Boost score if query contains city name and it matches candidate's city
        if candidate_data:
            candidate_city = candidate_data.get('city', '').lower()
            if candidate_city and len(candidate_city) > 3:
                query_lower = query.lower()
                # Check if query contains the city name
                if candidate_city in query_lower:
                    # Give significant boost for city match
                    combined_score = min(combined_score + 0.15, 1.0)
                    
                # Also check if any token from query matches city
                query_words = query_lower.split()
                for word in query_words:
                    if len(word) > 3 and word in candidate_city:
                        combined_score = min(combined_score + 0.1, 1.0)
                        break
        
        return min(combined_score, 1.0)
    
    def find_best_match(
        self, 
        school_name: str, 
        state: Optional[str] = None,
        confidence_threshold: float = 0.8
    ) -> Tuple[Optional[Dict[str, Any]], float, List[Dict[str, Any]]]:
        """
        Find the best matching school from the database
        
        Args:
            school_name: The school name to match (from Gemini extraction)
            state: Optional state filter to narrow search
            confidence_threshold: Minimum confidence for automatic matching
            
        Returns:
            Tuple of (best_match, confidence_score, alternative_suggestions)
        """
        log_debug("=== HIGH SCHOOL MATCHING START ===", service="high_school_matching")
        log_debug(f"Searching for: {school_name}", {"state": state}, service="high_school_matching")
        
        if not school_name or len(school_name.strip()) < 3:
            log_debug("School name too short or empty", service="high_school_matching")
            return None, 0.0, []
        
        try:
            # Search for schools (limit to reasonable number for performance)
            candidates = self.repo.search_schools(
                query=school_name,
                limit=50,
                state=state
            )
            
            if not candidates:
                log_debug("No candidates found", service="high_school_matching")
                return None, 0.0, []
            
            # Calculate similarity scores for all candidates
            scored_candidates = []
            for candidate in candidates:
                score = self.calculate_similarity_score(
                    school_name,
                    candidate.get('name', ''),
                    candidate
                )
                scored_candidates.append({
                    **candidate,
                    'match_score': score
                })
            
            # Sort by score
            scored_candidates.sort(key=lambda x: x['match_score'], reverse=True)
            
            # Get best match
            best_match = scored_candidates[0] if scored_candidates else None
            best_score = best_match['match_score'] if best_match else 0.0
            
            # Get alternative suggestions (top 5, excluding best match if it's above threshold)
            if best_score >= confidence_threshold:
                alternatives = scored_candidates[1:6]
                log_debug(
                    f"Found exact match: {best_match['name']}",
                    {"score": best_score, "ceeb_code": best_match.get('ceeb_code')},
                    service="high_school_matching"
                )
            else:
                alternatives = scored_candidates[:5]
                log_debug(
                    f"No exact match, best candidate: {best_match['name'] if best_match else 'None'}",
                    {"score": best_score},
                    service="high_school_matching"
                )
            
            # Only return best match if it meets threshold
            if best_score >= confidence_threshold:
                return best_match, best_score, alternatives
            else:
                return None, best_score, alternatives
                
        except Exception as e:
            log_debug(f"Error in high school matching: {str(e)}", service="high_school_matching")
            return None, 0.0, []
    
    def validate_and_enhance_high_school(
        self,
        fields: Dict[str, Any],
        confidence_threshold: float = 0.85
    ) -> Dict[str, Any]:
        """
        Validate and enhance high school field with CEEB code
        
        Args:
            fields: Field data containing high_school field
            confidence_threshold: Minimum confidence for automatic enhancement
            
        Returns:
            Enhanced fields with high_school validation and ceeb_code
        """
        log_debug("=== HIGH SCHOOL VALIDATION START ===", service="high_school_matching")
        
        # Get current high school value
        high_school_field = fields.get('high_school', {})
        high_school_name = high_school_field.get('value', '')
        
        if not high_school_name:
            log_debug("No high school name to validate", service="high_school_matching")
            return fields
        
        # Get state for more accurate matching
        state = fields.get('state', {}).get('value', '')
        
        # Find best match
        best_match, confidence, alternatives = self.find_best_match(
            high_school_name,
            state=state if state else None,
            confidence_threshold=confidence_threshold
        )
        
        # Initialize ceeb_code field if not exists
        if 'ceeb_code' not in fields:
            fields['ceeb_code'] = {
                'value': '',
                'confidence': 0.0,
                'source': '',
                'requires_human_review': False,
                'review_notes': '',
                'required': False,
                'enabled': True
            }
        
        if best_match and confidence >= confidence_threshold:
            # Auto-fill with high confidence match
            log_debug(
                f"Auto-filling high school: {best_match['name']}",
                {"confidence": confidence, "ceeb_code": best_match.get('ceeb_code')},
                service="high_school_matching"
            )
            
            # Update high school field with validated name
            fields['high_school'] = {
                **high_school_field,
                'value': best_match['name'],
                'confidence': confidence,
                'source': 'high_school_directory_verified',
                'requires_human_review': False,
                'review_notes': f"Verified from school directory (confidence: {confidence:.2f})",
                'metadata': {
                    'school_id': best_match.get('id'),
                    'original_value': high_school_name,
                    'match_confidence': confidence
                }
            }
            
            # Add CEEB code if available
            if best_match.get('ceeb_code'):
                fields['ceeb_code'] = {
                    'value': best_match['ceeb_code'],
                    'confidence': confidence,
                    'source': 'high_school_directory_verified',
                    'requires_human_review': False,
                    'review_notes': 'Auto-filled from school directory',
                    'required': False,
                    'enabled': True
                }
        else:
            # Flag for review with suggestions
            log_debug(
                f"High school needs review: {high_school_name}",
                {"best_confidence": confidence, "alternatives_count": len(alternatives)},
                service="high_school_matching"
            )
            
            fields['high_school'] = {
                **high_school_field,
                'requires_human_review': True,
                'review_notes': f"Could not verify school name. Best match confidence: {confidence:.2f}",
                'source': 'high_school_directory_unverified',
                'metadata': {
                    'original_value': high_school_name,
                    'suggestions': [
                        {
                            'id': alt.get('id'),
                            'name': alt.get('name'),
                            'ceeb_code': alt.get('ceeb_code'),
                            'city': alt.get('city'),
                            'state': alt.get('state'),
                            'match_score': alt.get('match_score')
                        }
                        for alt in alternatives
                    ]
                }
            }
            
            # Mark CEEB code as needing review too
            fields['ceeb_code']['requires_human_review'] = True
            fields['ceeb_code']['review_notes'] = 'Pending high school verification'
        
        log_debug("=== HIGH SCHOOL VALIDATION COMPLETE ===", service="high_school_matching")
        return fields