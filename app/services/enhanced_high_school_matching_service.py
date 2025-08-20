from typing import Dict, Any, List, Optional, Tuple
from difflib import SequenceMatcher
import re
from app.repositories.high_schools_repository import HighSchoolsRepository
from app.utils.retry_utils import log_debug
from app.utils.location_utils import get_proximity_boost, get_student_location_context

class EnhancedHighSchoolMatchingService:
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
            'sw': 'southwest',
            # Common school-specific abbreviations
            'jj': 'j j',
            'lbj': 'lyndon b johnson',
            'ywla': 'young womens leadership academy',
        }
        
        # Common words to ignore in matching
        self.stop_words = {'the', 'of', 'and', 'at', 'in', 'for', 'school', 'high', 'public', 'private'}
    
    def normalize_school_name(self, name: str) -> str:
        """Normalize school name for better matching"""
        if not name:
            return ""
            
        # Convert to lowercase
        normalized = name.lower().strip()
        
        # Handle common typos and variations
        normalized = normalized.replace('highland', 'highlands')  # Common typo
        normalized = normalized.replace('wylie west jh', 'wylie west junior high')
        normalized = normalized.replace(' jh', ' junior high')
        
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
    
    def create_search_variants(self, name: str) -> list[str]:
        """Create search variants for better matching"""
        variants = [name]
        normalized = self.normalize_school_name(name)
        
        # Add normalized version
        if normalized != name.lower():
            variants.append(normalized)
        
        # Handle city prefix patterns (e.g., "Abilene Wylie High School" -> "Wylie High School")
        words = normalized.split()
        if len(words) >= 3:
            # Try removing first word if it might be a city name
            potential_city = words[0]
            if potential_city not in ['high', 'school', 'junior', 'senior', 'christian', 'catholic']:
                without_city = ' '.join(words[1:])
                variants.append(without_city)
                
                # Also try with "high school" at the end if not present
                if 'high school' not in without_city:
                    variants.append(without_city + ' high school')
        
        # Handle school type suffixes
        if 'high school' in normalized:
            base_name = normalized.replace('high school', '').strip()
            if base_name:
                variants.append(base_name)
                variants.append(base_name + ' hs')
        
        return list(set(variants))  # Remove duplicates
    
    def calculate_similarity_score(
        self, 
        query: str, 
        candidate: str, 
        candidate_data: Dict[str, Any] = None,
        student_location: Dict[str, Any] = None
    ) -> float:
        """
        Calculate similarity score between query and candidate school name
        Enhanced with location-based scoring and search variants
        
        Args:
            query: The search query (from Gemini extraction)
            candidate: The candidate school name from database
            candidate_data: Additional school data (city, state) for context scoring
            student_location: Student location context from get_student_location_context()
            
        Returns:
            Similarity score between 0 and 1
        """
        # Create search variants for better matching
        query_variants = self.create_search_variants(query)
        candidate_normalized = self.normalize_school_name(candidate)
        
        # Calculate similarity against all query variants and take the best
        best_score = 0.0
        best_variant = ""
        
        for variant in query_variants:
            variant_normalized = self.normalize_school_name(variant)
            
            # Base similarity using SequenceMatcher
            base_similarity = SequenceMatcher(None, variant_normalized, candidate_normalized).ratio()
            
            # Check for exact match (after normalization)
            if variant_normalized == candidate_normalized:
                base_similarity = 1.0
            
            # Check if one contains the other (partial match)
            elif variant_normalized in candidate_normalized or candidate_normalized in variant_normalized:
                base_similarity = max(base_similarity, 0.85)
            
            # Special boost for "High School" → "Senior High School" patterns
            elif 'high school' in variant_normalized and 'senior high school' in candidate_normalized:
                # Extract the base name (e.g., "midland" from "midland high school")
                query_base = variant_normalized.replace('high school', '').strip()
                candidate_base = candidate_normalized.replace('senior high school', '').strip()
                if query_base == candidate_base:
                    base_similarity = max(base_similarity, 0.90)  # Strong match for this pattern
            
            # Token-based matching for better handling of word order differences
            variant_tokens = set(variant_normalized.split()) - self.stop_words
            candidate_tokens = set(candidate_normalized.split()) - self.stop_words
            
            if variant_tokens and candidate_tokens:
                # Jaccard similarity
                intersection = variant_tokens.intersection(candidate_tokens)
                union = variant_tokens.union(candidate_tokens)
                token_similarity = len(intersection) / len(union) if union else 0
                
                # Weight token similarity higher if most important words match
                if len(intersection) >= min(3, len(variant_tokens)):
                    token_similarity = min(token_similarity * 1.2, 1.0)
                
                # Special boost for school name core matches (e.g., "Wylie" matching "Wylie High School")
                if variant_tokens.issubset(candidate_tokens) or candidate_tokens.issubset(variant_tokens):
                    token_similarity = min(token_similarity * 1.1, 1.0)
                
                # Combine base and token similarity
                combined_score = (base_similarity * 0.6) + (token_similarity * 0.4)
            else:
                combined_score = base_similarity
            
            # Apply penalties for mismatched patterns
            # If query says "High School" but candidate is something very different, penalize
            if 'high school' in variant_normalized:
                # Prefer schools that actually have "high school" in their name
                if ('high school' in candidate_normalized or 
                    'senior high school' in candidate_normalized or
                    'freshman high school' in candidate_normalized or
                    'junior high school' in candidate_normalized):
                    # No penalty for actual high schools
                    pass
                else:
                    # Penalty for schools that don't match the "high school" pattern
                    combined_score = combined_score * 0.8
            
            if combined_score > best_score:
                best_score = combined_score
                best_variant = variant
        
        # Location-based proximity boost
        location_boost = 0.0
        if student_location and candidate_data:
            location_boost = get_proximity_boost(
                student_location.get('city'),
                student_location.get('state'),
                candidate_data.get('city', ''),
                candidate_data.get('state', ''),
                student_location.get('coordinates'),
                None  # We don't have school coordinates yet
            )
        
        # Apply location boost
        base_with_location = min(best_score + location_boost, 1.0)
        
        # Add secondary scoring for name pattern preference
        pattern_bonus = self._calculate_pattern_bonus(query, candidate_data.get('name', '')) if candidate_data else 0.0
        final_score = min(base_with_location + pattern_bonus, 1.0)
        
        if location_boost > 0:
            log_debug(
                f"Location boost applied: +{location_boost:.2f}",
                {
                    "base_score": best_score,
                    "final_score": final_score,
                    "student_city": student_location.get('city') if student_location else None,
                    "school_city": candidate_data.get('city') if candidate_data else None,
                    "best_variant": best_variant
                },
                service="enhanced_high_school_matching"
            )
        
        return final_score
    
    def _calculate_pattern_bonus(self, query: str, candidate_name: str) -> float:
        """Calculate small bonus for name pattern preferences"""
        if not query or not candidate_name:
            return 0.0
        
        query_lower = query.lower()
        candidate_lower = candidate_name.lower()
        
        # Small bonus for exact abbreviation expansion matches
        if 'ywla' in query_lower and 'young womens leadership academy' in candidate_lower:
            return 0.02
        
        return 0.0
    
    def find_best_match_with_location(
        self, 
        school_name: str, 
        fields: Dict[str, Any],
        confidence_threshold: float = 0.8
    ) -> Tuple[Optional[Dict[str, Any]], float, List[Dict[str, Any]]]:
        """
        Find the best matching school using location context from student fields
        
        Args:
            school_name: The school name to match (from Gemini extraction)
            fields: Complete student field data containing location info
            confidence_threshold: Minimum confidence for automatic matching
            
        Returns:
            Tuple of (best_match, confidence_score, alternative_suggestions)
        """
        log_debug("=== ENHANCED HIGH SCHOOL MATCHING START ===", service="enhanced_high_school_matching")
        
        # Extract student location context
        student_location = get_student_location_context(fields)
        
        log_debug(
            f"Searching for: {school_name}",
            {
                "student_location": student_location,
                "confidence_threshold": confidence_threshold
            },
            service="enhanced_high_school_matching"
        )
        
        if not school_name or len(school_name.strip()) < 3:
            log_debug("School name too short or empty", service="enhanced_high_school_matching")
            return None, 0.0, []
        
        try:
            # Search for schools with location context prioritization
            search_state = student_location.get('state') if student_location else None
            search_city = student_location.get('city') if student_location else None
            candidates = self.repo.search_schools(
                query=school_name,
                limit=100,  # Increase limit for location-based filtering
                state=search_state,
                city=search_city  # Pass city for location-first search
            )
            
            if not candidates:
                log_debug("No candidates found", service="enhanced_high_school_matching")
                return None, 0.0, []
            
            # Filter out colleges, universities, and community colleges
            filtered_candidates = []
            college_keywords = ['college', 'university', 'community college', 'junior college']
            
            for candidate in candidates:
                candidate_name = candidate.get('name', '').lower()
                is_college = any(keyword in candidate_name for keyword in college_keywords)
                
                # Special case: "Early College High School" should be allowed
                if is_college and 'early college high school' in candidate_name:
                    is_college = False
                
                if not is_college:
                    filtered_candidates.append(candidate)
                else:
                    log_debug(f"Filtered out college: {candidate.get('name')}", service="enhanced_high_school_matching")
            
            log_debug(f"Filtered candidates: {len(candidates)} -> {len(filtered_candidates)}", service="enhanced_high_school_matching")
            
            if not filtered_candidates:
                log_debug("No candidates after college filtering", service="enhanced_high_school_matching")
                return None, 0.0, []
            
            # Calculate similarity scores for all candidates with location context
            scored_candidates = []
            for candidate in filtered_candidates:
                score = self.calculate_similarity_score(
                    school_name,
                    candidate.get('name', ''),
                    candidate,
                    student_location
                )
                scored_candidates.append({
                    **candidate,
                    'match_score': score,
                    'distance_info': self._get_distance_info(student_location, candidate)
                })
            
            # Sort by score (location boost is already included)
            scored_candidates.sort(key=lambda x: x['match_score'], reverse=True)
            
            # Get best match
            best_match = scored_candidates[0] if scored_candidates else None
            best_score = best_match['match_score'] if best_match else 0.0
            
            # Get alternative suggestions (top 5, excluding best match if it's above threshold)
            if best_score >= confidence_threshold:
                alternatives = scored_candidates[1:6]
                log_debug(
                    f"Found confident match: {best_match['name']}",
                    {
                        "score": best_score,
                        "ceeb_code": best_match.get('ceeb_code'),
                        "location": f"{best_match.get('city')}, {best_match.get('state')}"
                    },
                    service="enhanced_high_school_matching"
                )
            else:
                alternatives = scored_candidates[:5]
                log_debug(
                    f"No confident match, best candidate: {best_match['name'] if best_match else 'None'}",
                    {"score": best_score},
                    service="enhanced_high_school_matching"
                )
            
            # Only return best match if it meets threshold
            if best_score >= confidence_threshold:
                return best_match, best_score, alternatives
            else:
                return None, best_score, alternatives
                
        except Exception as e:
            log_debug(f"Error in enhanced high school matching: {str(e)}", service="enhanced_high_school_matching")
            return None, 0.0, []
    
    def _get_distance_info(self, student_location: Dict[str, Any], school: Dict[str, Any]) -> str:
        """Generate human-readable distance information"""
        if not student_location or not student_location.get('city'):
            return ""
        
        student_city = student_location.get('city', '')
        school_city = school.get('city', '')
        school_state = school.get('state', '')
        
        if student_city.lower() == school_city.lower():
            return f"Local to {school_city}"
        else:
            return f"Located in {school_city}, {school_state}"
    
    def validate_and_enhance_high_school_with_location(
        self,
        fields: Dict[str, Any],
        confidence_threshold: float = 0.85
    ) -> Dict[str, Any]:
        """
        Enhanced validation using location context
        
        Args:
            fields: Field data containing high_school field and location data
            confidence_threshold: Minimum confidence for automatic enhancement
            
        Returns:
            Enhanced fields with high_school validation, ceeb_code, and validation_status
        """
        log_debug("=== ENHANCED HIGH SCHOOL VALIDATION START ===", service="enhanced_high_school_matching")
        
        # Get current high school value
        high_school_field = fields.get('high_school', {})
        high_school_name = high_school_field.get('value', '')
        
        if not high_school_name:
            log_debug("No high school name to validate", service="enhanced_high_school_matching")
            return fields
        
        # Find best match with location context
        best_match, confidence, alternatives = self.find_best_match_with_location(
            high_school_name,
            fields,
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
        
        # Add validation_status field for UI
        validation_status = {
            'status': 'unvalidated',  # 'verified', 'needs_validation', 'no_matches', 'unvalidated'
            'match_type': '',  # 'auto', 'suggestions', 'manual'
            'suggestions': [],
            'confidence': confidence
        }
        
        if best_match and confidence >= confidence_threshold:
            # Auto-fill with high confidence match
            log_debug(
                f"Auto-filling high school: {best_match['name']}",
                {"confidence": confidence, "ceeb_code": best_match.get('ceeb_code')},
                service="enhanced_high_school_matching"
            )
            
            # Update high school field with validated name
            fields['high_school'] = {
                **high_school_field,
                'value': best_match['name'],
                'confidence': confidence,
                'source': 'high_school_directory_verified',
                'requires_human_review': False,
                'review_notes': f"Auto-verified using location context (confidence: {confidence:.2f})",
                'metadata': {
                    'school_id': best_match.get('id'),
                    'original_value': high_school_name,
                    'match_confidence': confidence,
                    'location_used': True
                }
            }
            
            # Add CEEB code if available
            if best_match.get('ceeb_code'):
                fields['ceeb_code'] = {
                    'value': best_match['ceeb_code'],
                    'confidence': confidence,
                    'source': 'high_school_directory_verified',
                    'requires_human_review': False,
                    'review_notes': 'Auto-filled from school directory with location context',
                    'required': False,
                    'enabled': True
                }
            
            validation_status['status'] = 'verified'
            validation_status['match_type'] = 'auto'
            
        elif alternatives and len(alternatives) > 0:
            # Has suggestions but needs validation
            log_debug(
                f"High school needs validation with suggestions: {high_school_name}",
                {"best_confidence": confidence, "alternatives_count": len(alternatives)},
                service="enhanced_high_school_matching"
            )
            
            # Format suggestions for UI
            formatted_suggestions = []
            for alt in alternatives:
                formatted_suggestions.append({
                    'id': alt.get('id'),
                    'name': alt.get('name'),
                    'ceeb_code': alt.get('ceeb_code'),
                    'location': f"{alt.get('city')}, {alt.get('state')}",
                    'display_name': f"{alt.get('name')} (CEEB: {alt.get('ceeb_code', 'N/A')}) - {alt.get('city')}, {alt.get('state')}",
                    'match_score': alt.get('match_score'),
                    'distance_info': alt.get('distance_info', '')
                })
            
            fields['high_school'] = {
                **high_school_field,
                'requires_human_review': True,
                'review_notes': f"Please validate school selection. Best match confidence: {confidence:.2f}",
                'source': 'high_school_directory_suggestions_available',
                'metadata': {
                    'original_value': high_school_name,
                    'suggestions': formatted_suggestions
                }
            }
            
            validation_status['status'] = 'needs_validation'
            validation_status['match_type'] = 'suggestions'
            validation_status['suggestions'] = formatted_suggestions
            
            # Mark CEEB code as needing review too
            fields['ceeb_code']['requires_human_review'] = True
            fields['ceeb_code']['review_notes'] = 'Pending high school validation'
            
        else:
            # No matches found
            log_debug(
                f"No matches found for: {high_school_name}",
                service="enhanced_high_school_matching"
            )
            
            fields['high_school'] = {
                **high_school_field,
                'requires_human_review': True,
                'review_notes': 'No matching schools found in directory. Please verify manually.',
                'source': 'high_school_directory_no_matches',
                'metadata': {
                    'original_value': high_school_name,
                    'suggestions': []
                }
            }
            
            validation_status['status'] = 'no_matches'
            validation_status['match_type'] = 'manual'
            
            # Mark CEEB code as needing manual entry
            fields['ceeb_code']['requires_human_review'] = True
            fields['ceeb_code']['review_notes'] = 'No school matches found - manual entry required'
        
        # Add validation status to fields for UI consumption
        fields['high_school_validation'] = validation_status
        
        log_debug("=== ENHANCED HIGH SCHOOL VALIDATION COMPLETE ===", service="enhanced_high_school_matching")
        return fields
    
    def validate_and_enhance_high_school(
        self,
        fields: Dict[str, Any],
        confidence_threshold: float = 0.85
    ) -> Dict[str, Any]:
        """
        Backward compatibility wrapper for validate_and_enhance_high_school_with_location
        """
        return self.validate_and_enhance_high_school_with_location(fields, confidence_threshold)