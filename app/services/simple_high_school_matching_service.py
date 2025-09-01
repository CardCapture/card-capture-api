from typing import Dict, Any, List, Optional, Tuple
from difflib import SequenceMatcher
import re
from app.repositories.high_schools_repository import HighSchoolsRepository
from app.utils.retry_utils import log_debug

class SimpleHighSchoolMatchingService:
    """Simplified, reliable high school matching focused on accuracy over complexity"""
    
    def __init__(self):
        self.repo = HighSchoolsRepository()
        
        # Simple normalization patterns
        self.normalization_patterns = [
            (r'\s+', ' '),  # Multiple spaces to single space
            (r'[^\w\s]', ''),  # Remove special characters
        ]
        
        # College/university exclusion keywords
        self.college_keywords = [
            'college', 'university', 'community college', 'junior college'
        ]
        
        # Stop words for token matching
        self.stop_words = {'the', 'of', 'and', 'at', 'in', 'for'}
        
        # Generic school words (low weight)
        self.generic_school_words = {
            'high', 'school', 'senior', 'junior', 'freshman', 'elementary', 
            'middle', 'academy', 'institute', 'college', 'university',
            'preparatory', 'prep', 'charter', 'magnet', 'early'
        }
        
        # Common location words (medium weight)  
        self.location_words = {
            'north', 'south', 'east', 'west', 'northeast', 'northwest', 
            'southeast', 'southwest', 'central', 'new', 'old', 'upper', 'lower',
            # Common Texas cities that appear as school prefixes
            'abilene', 'dallas', 'houston', 'austin', 'san', 'fort', 'el', 
            'corpus', 'amarillo', 'lubbock', 'garland', 'irving', 'laredo',
            'plano', 'arlington', 'midland', 'odessa', 'beaumont', 'waco',
            'carrollton', 'denton', 'mckinney', 'frisco', 'killeen', 'pasadena',
            'mesquite', 'grand', 'prairie'
        }

    def normalize_school_name(self, name: str) -> str:
        """Simple, reliable normalization"""
        if not name:
            return ""
        
        # Convert to lowercase and strip
        normalized = name.lower().strip()
        
        # Apply normalization patterns
        for pattern, replacement in self.normalization_patterns:
            normalized = re.sub(pattern, replacement, normalized)
        
        # Handle common abbreviations and variations
        normalized = normalized.replace(' hs', ' high school')
        normalized = normalized.replace(' h.s.', ' high school')
        normalized = normalized.replace('highschool', 'high school')
        normalized = normalized.replace('middleschool', 'middle school')
        normalized = normalized.replace('elementaryschool', 'elementary school')
        
        return normalized.strip()

    def _normalize_state_name(self, state: str) -> str:
        """Normalize state name to standard abbreviation"""
        if not state:
            return ""
        
        state_clean = state.strip().lower()
        
        # State name to abbreviation mapping
        state_mapping = {
            'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR', 'california': 'CA',
            'colorado': 'CO', 'connecticut': 'CT', 'delaware': 'DE', 'florida': 'FL', 'georgia': 'GA',
            'hawaii': 'HI', 'idaho': 'ID', 'illinois': 'IL', 'indiana': 'IN', 'iowa': 'IA',
            'kansas': 'KS', 'kentucky': 'KY', 'louisiana': 'LA', 'maine': 'ME', 'maryland': 'MD',
            'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN', 'mississippi': 'MS', 'missouri': 'MO',
            'montana': 'MT', 'nebraska': 'NE', 'nevada': 'NV', 'new hampshire': 'NH', 'new jersey': 'NJ',
            'new mexico': 'NM', 'new york': 'NY', 'north carolina': 'NC', 'north dakota': 'ND', 'ohio': 'OH',
            'oklahoma': 'OK', 'oregon': 'OR', 'pennsylvania': 'PA', 'rhode island': 'RI', 'south carolina': 'SC',
            'south dakota': 'SD', 'tennessee': 'TN', 'texas': 'TX', 'utah': 'UT', 'vermont': 'VT',
            'virginia': 'VA', 'washington': 'WA', 'west virginia': 'WV', 'wisconsin': 'WI', 'wyoming': 'WY'
        }
        
        # If it's already an abbreviation, return uppercase
        if len(state_clean) == 2 and state_clean.isalpha():
            return state_clean.upper()
        
        # Look up full state name
        return state_mapping.get(state_clean, state.strip())

    def calculate_similarity_score(self, query: str, candidate: str) -> float:
        """Calculate semantic similarity between school names"""
        
        query_norm = self.normalize_school_name(query)
        candidate_norm = self.normalize_school_name(candidate)
        
        # 1. Exact match
        if query_norm == candidate_norm:
            return 1.0
        
        # 2. Handle high school variants (City High School -> City Senior High School)
        if self._is_high_school_variant(query_norm, candidate_norm):
            return 0.95
        
        # 3. Check for truncated name patterns (query is partial candidate)
        if self._is_truncated_match(query_norm, candidate_norm):
            return 0.95
        
        # 4. Token-based similarity (primary method)
        return self._calculate_token_similarity(query_norm, candidate_norm)
    
    def _is_high_school_variant(self, query_norm: str, candidate_norm: str) -> bool:
        """Check for common high school naming patterns"""
        
        patterns = [
            ('high school', 'senior high school'),
            ('high school', 'freshman high school'),  
            ('high school', 'junior high school'),
        ]
        
        for query_pattern, candidate_pattern in patterns:
            if query_pattern in query_norm and candidate_pattern in candidate_norm:
                query_base = query_norm.replace(query_pattern, '').strip()
                candidate_base = candidate_norm.replace(candidate_pattern, '').strip()
                if query_base == candidate_base:
                    return True
        
        return False
    
    def _is_truncated_match(self, query_norm: str, candidate_norm: str) -> bool:
        """Check if query appears to be a truncated version of candidate"""
        
        # Query must be shorter than candidate for this to apply
        if len(query_norm) >= len(candidate_norm):
            return False
        
        query_words = query_norm.split()
        candidate_words = candidate_norm.split()
        
        # Must have at least 3 words to avoid false positives
        if len(query_words) < 3:
            return False
        
        # Check for exact prefix match with truncated last word
        # Example: "young womens leadership aca" vs "young womens leadership academy midland"
        if len(query_words) <= len(candidate_words):
            # Check if first N-1 words match exactly
            for i in range(len(query_words) - 1):
                if i >= len(candidate_words) or query_words[i] != candidate_words[i]:
                    return False
            
            # Last query word should be a truncation of corresponding candidate word
            last_query_word = query_words[-1]
            corresponding_candidate_word = candidate_words[len(query_words) - 1]
            
            if (corresponding_candidate_word.startswith(last_query_word) and 
                len(last_query_word) >= 3 and 
                len(corresponding_candidate_word) > len(last_query_word)):
                return True
        
        # Alternative: check if query is a truncated subsequence
        # Handle cases where truncation happens mid-sequence
        query_str = ' '.join(query_words)
        if candidate_norm.startswith(query_str) and len(query_str) >= 10:
            return True
        
        return False
    
    def _calculate_token_similarity(self, query_norm: str, candidate_norm: str) -> float:
        """Token-based similarity calculation with unique word weighting"""
        
        query_tokens = set(query_norm.split()) - self.stop_words
        candidate_tokens = set(candidate_norm.split()) - self.stop_words
        
        if not query_tokens or not candidate_tokens:
            return 0.0
        
        # Calculate weighted similarity instead of simple Jaccard
        intersection = query_tokens.intersection(candidate_tokens)
        union = query_tokens.union(candidate_tokens)
        
        # Calculate weighted scores for matching tokens
        total_weight = 0.0
        matched_weight = 0.0
        
        for token in union:
            # Determine token weight based on type
            if token in self.generic_school_words:
                weight = 0.3  # Low weight for generic school words
            elif token in self.location_words:
                weight = 0.6  # Medium weight for location words
            else:
                weight = 1.0  # High weight for unique/distinctive words
            
            total_weight += weight
            
            # Add to matched weight if token appears in both
            if token in intersection:
                matched_weight += weight
        
        # Weighted token similarity
        token_similarity = matched_weight / total_weight if total_weight > 0 else 0
        
        # Edit distance similarity
        edit_similarity = SequenceMatcher(None, query_norm, candidate_norm).ratio()
        
        # Weighted combination (favor token matching for school names)
        combined_score = (token_similarity * 0.75) + (edit_similarity * 0.25)
        
        # Smart penalty system for missing important words
        query_unique = query_tokens - self.generic_school_words - self.location_words
        query_location = query_tokens.intersection(self.location_words) 
        candidate_unique = candidate_tokens - self.generic_school_words - self.location_words
        candidate_location = candidate_tokens.intersection(self.location_words)
        
        if query_unique:
            # Calculate coverage of unique words (school identifiers)
            unique_matches = query_unique.intersection(candidate_unique)
            unique_coverage = len(unique_matches) / len(query_unique)
            
            # Heavy penalty for missing unique school identifiers
            if unique_coverage < 1.0:
                missing_unique_penalty = (1.0 - unique_coverage) * 0.7  # Up to 70% penalty
                combined_score = max(combined_score - missing_unique_penalty, 0.05)
            
            # Major boost for complete unique word coverage
            if unique_coverage == 1.0 and len(unique_matches) >= 1:
                unique_boost = min(len(unique_matches) * 0.2, 0.4)
                combined_score = min(combined_score + unique_boost, 1.0)
                
                # Additional boost if this candidate has the unique words but others might not
                if len(unique_matches) >= 1:
                    combined_score = min(combined_score * 1.15, 1.0)
        
        # Light penalty for missing location words (less critical)
        if query_location:
            location_matches = query_location.intersection(candidate_location)
            location_coverage = len(location_matches) / len(query_location)
            
            if location_coverage < 1.0:
                missing_location_penalty = (1.0 - location_coverage) * 0.1  # Only 10% penalty
                combined_score = max(combined_score - missing_location_penalty, 0.05)
        
        return combined_score

    def find_best_match(
        self, 
        school_name: str,
        student_city: str = None,
        student_state: str = None,
        confidence_threshold: float = 0.85
    ) -> Tuple[Optional[Dict[str, Any]], float, List[Dict[str, Any]]]:
        """
        Find the best matching school with simple, reliable logic
        
        Args:
            school_name: The school name to match
            student_city: Student's city for context (optional)
            student_state: Student's state for filtering
            confidence_threshold: Minimum confidence for auto-match
            
        Returns:
            Tuple of (best_match, confidence_score, alternatives)
        """
        
        log_debug(f"Simple matching: {school_name}", service="simple_high_school_matching")
        
        if not school_name or len(school_name.strip()) < 2:
            return None, 0.0, []
        
        try:
            # Search for candidates using normalized name (handles apostrophes, special chars, etc.)
            normalized_name = self.normalize_school_name(school_name)
            log_debug(f"DEBUG: Searching with normalized name: '{normalized_name}' (from '{school_name}')", service="simple_high_school_matching")
            
            candidates = self.repo.search_schools(
                query=normalized_name,
                limit=50,
                state=student_state
            )
            
            # DEBUG: Log all candidates returned from database
            log_debug(f"DEBUG: Database returned {len(candidates)} candidates:", service="simple_high_school_matching")
            for i, candidate in enumerate(candidates[:10]):  # Show first 10
                log_debug(f"  {i+1}. {candidate.get('name', 'N/A')} - {candidate.get('city', 'N/A')}, {candidate.get('state', 'N/A')}", service="simple_high_school_matching")
            
            if not candidates:
                return None, 0.0, []
            
            # Filter out colleges/universities
            high_schools = []
            for candidate in candidates:
                name_lower = candidate.get('name', '').lower()
                is_college = any(keyword in name_lower for keyword in self.college_keywords)
                
                # Exception: "Early College High School" is allowed
                if is_college and 'early college high school' in name_lower:
                    is_college = False
                
                if not is_college:
                    high_schools.append(candidate)
            
            if not high_schools:
                log_debug("No high schools found after filtering", service="simple_high_school_matching")
                return None, 0.0, []
            
            # Score all candidates
            scored_candidates = []
            for candidate in high_schools:
                candidate_name = candidate.get('name', '')
                score = self.calculate_similarity_score(school_name, candidate_name)
                
                # DEBUG: Log scoring for candidates that look promising
                if 'leadership' in candidate_name.lower() and 'midland' in candidate_name.lower():
                    log_debug(f"DEBUG: Scoring '{candidate_name}' = {score:.3f}", service="simple_high_school_matching")
                
                # Location-based scoring improvements
                if student_city and student_state:
                    candidate_city = candidate.get('city', '').lower()
                    candidate_state = candidate.get('state', '').lower()
                    candidate_name = candidate.get('name', '')
                    
                    # DEBUG: Log location matching for promising candidates
                    if 'midland' in candidate_name.lower():
                        log_debug(f"DEBUG: Location check for '{candidate_name}': student='{student_city}, {student_state}' vs candidate='{candidate_city}, {candidate_state}'", service="simple_high_school_matching")
                    
                    # Strong boost for exact city/state match
                    if (candidate_city == student_city.lower() and 
                        candidate_state == student_state.lower()):
                        score += 0.15  # Significant boost for same location
                        log_debug(f"DEBUG: Applied same city/state boost (+0.15) to '{candidate_name}' -> {score:.3f}", service="simple_high_school_matching")
                        
                        # Additional boost if school name contains the city name
                        candidate_name_lower = candidate.get('name', '').lower()
                        if student_city.lower() in candidate_name_lower:
                            score += 0.10  # Extra boost for city-named schools
                    
                    # Medium boost for same state
                    elif candidate_state == student_state.lower():
                        score += 0.05
                
                scored_candidates.append({
                    **candidate,
                    'match_score': score
                })
            
            # Sort by score
            scored_candidates.sort(key=lambda x: x['match_score'], reverse=True)
            
            best_match = scored_candidates[0] if scored_candidates else None
            best_score = best_match['match_score'] if best_match else 0.0
            
            # Return match only if meets threshold
            if best_score >= confidence_threshold:
                alternatives = scored_candidates[1:6]  # Top 5 alternatives
                log_debug(f"Found match: {best_match['name']} ({best_score:.3f})", service="simple_high_school_matching")
                return best_match, best_score, alternatives
            else:
                alternatives = scored_candidates[:5]  # Top 5 as suggestions
                log_debug(f"No confident match. Best: {best_match['name'] if best_match else 'None'} ({best_score:.3f})", service="simple_high_school_matching")
                return None, best_score, alternatives
                
        except Exception as e:
            log_debug(f"Error in simple matching: {str(e)}", service="simple_high_school_matching")
            return None, 0.0, []

    def validate_and_enhance_high_school(
        self,
        fields: Dict[str, Any],
        confidence_threshold: float = 0.85
    ) -> Dict[str, Any]:
        """
        Simple validation that enhances fields with reliable matching
        """
        
        # Get high school value
        high_school_field = fields.get('high_school', {})
        high_school_name = high_school_field.get('value', '')
        
        if not high_school_name:
            return fields
        
        # Extract location context
        student_city = fields.get('city', {}).get('value', '')
        student_state = fields.get('state', {}).get('value', '')
        
        # DEBUG: Log what we're getting
        log_debug(f"DEBUG: Original state value: '{student_state}'", service="simple_high_school_matching")
        
        # Normalize state name to abbreviation for database lookup
        student_state = self._normalize_state_name(student_state)
        
        # DEBUG: Log after normalization
        log_debug(f"DEBUG: Normalized state value: '{student_state}'", service="simple_high_school_matching")
        log_debug(f"DEBUG: Searching with city='{student_city}', state='{student_state}'", service="simple_high_school_matching")
        
        # DEBUG: Log normalized search term
        normalized_search = self.normalize_school_name(high_school_name)
        log_debug(f"DEBUG: Normalized search term: '{normalized_search}'", service="simple_high_school_matching")
        
        # Find best match
        best_match, confidence, alternatives = self.find_best_match(
            high_school_name,
            student_city,
            student_state,
            confidence_threshold
        )
        
        # Initialize CEEB field if needed
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
        
        # Add validation status
        validation_status = {
            'status': 'unvalidated',
            'match_type': '',
            'suggestions': [],
            'confidence': confidence
        }
        
        if best_match and confidence >= confidence_threshold:
            # DEBUG: Log what we matched
            log_debug(
                f"DEBUG: Auto-matched '{high_school_name}' to '{best_match['name']}' in {best_match.get('city')}, {best_match.get('state')} with confidence {confidence:.3f}",
                service="simple_high_school_matching"
            )
            
            # High confidence auto-match
            fields['high_school'] = {
                **high_school_field,
                'value': best_match['name'],
                'confidence': confidence,
                'source': 'high_school_directory_verified',
                'requires_human_review': False,
                'review_notes': f"Auto-verified (confidence: {confidence:.2f})",
                'metadata': {
                    'school_id': best_match.get('id'),
                    'school_city': best_match.get('city', ''),
                    'school_state': best_match.get('state', ''),
                    'original_value': high_school_name,
                    'match_confidence': confidence
                }
            }
            
            # Add CEEB code
            if best_match.get('ceeb_code'):
                fields['ceeb_code'] = {
                    'value': best_match['ceeb_code'],
                    'confidence': confidence,
                    'source': 'high_school_directory_verified',
                    'requires_human_review': False,
                    'review_notes': 'Auto-filled from verified school match',
                    'required': False,
                    'enabled': True
                }
            
            validation_status['status'] = 'verified'
            validation_status['match_type'] = 'auto'
            
        elif alternatives:
            # Has suggestions but needs validation
            formatted_suggestions = []
            for alt in alternatives:
                formatted_suggestions.append({
                    'id': alt.get('id'),
                    'name': alt.get('name'),
                    'ceeb_code': alt.get('ceeb_code'),
                    'location': f"{alt.get('city')}, {alt.get('state')}",
                    'match_score': alt.get('match_score'),
                    'distance_info': alt.get('city', '')
                })
            
            fields['high_school'] = {
                **high_school_field,
                'requires_human_review': True,
                'review_notes': f"Please select correct school. Best match: {confidence:.2f}",
                'source': 'high_school_directory_suggestions',
                'metadata': {
                    'original_value': high_school_name,
                    'suggestions': formatted_suggestions
                }
            }
            
            validation_status['status'] = 'needs_validation'
            validation_status['match_type'] = 'suggestions'
            validation_status['suggestions'] = formatted_suggestions
            
            fields['ceeb_code']['requires_human_review'] = True
            fields['ceeb_code']['review_notes'] = 'Pending school selection'
            
        else:
            # No matches
            fields['high_school'] = {
                **high_school_field,
                'requires_human_review': True,
                'review_notes': 'No matching schools found. Please verify manually.',
                'source': 'high_school_directory_no_matches'
            }
            
            validation_status['status'] = 'no_matches'
            validation_status['match_type'] = 'manual'
            
            fields['ceeb_code']['requires_human_review'] = True
            fields['ceeb_code']['review_notes'] = 'No school matches - manual entry required'
        
        fields['high_school_validation'] = validation_status
        
        return fields