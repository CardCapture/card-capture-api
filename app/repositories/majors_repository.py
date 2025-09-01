from typing import List, Dict, Any, Optional
import re
from app.core.clients import get_supabase_client

class MajorsRepository:
    def __init__(self):
        self.client = get_supabase_client()
        self.table = "majors_cip"
        
        # Student-friendly name mappings for common majors
        self.display_name_mappings = {
            # Computer Science related
            "Computer and Information Sciences, General.": "Computer Science",
            "Computer Science.": "Computer Science", 
            "Computer Engineering, General.": "Computer Engineering",
            "Computer Software Engineering.": "Software Engineering", 
            "Information Technology.": "Information Technology",
            "Computer Programming/Programmer, General.": "Computer Programming",
            "Computer Systems Networking and Telecommunications.": "Computer Networking",
            "Computer and Information Systems Security/Auditing/Information Assurance.": "Cybersecurity",
            "Artificial Intelligence.": "Artificial Intelligence",
            "Data Processing and Data Processing Technology/Technician.": "Data Science",
            "Web/Multimedia Management and Webmaster.": "Web Development",
            
            # Business
            "Business Administration and Management, General.": "Business Administration",
            "Accounting.": "Accounting",
            "Marketing/Marketing Management, General.": "Marketing", 
            "Finance, General.": "Finance",
            "Management Sciences and Quantitative Methods, General.": "Management",
            "Economics, General.": "Economics",
            
            # STEM
            "Biology/Biological Sciences, General.": "Biology",
            "Chemistry, General.": "Chemistry", 
            "Physics, General.": "Physics",
            "Mathematics, General.": "Mathematics",
            "Mechanical Engineering.": "Mechanical Engineering",
            "Electrical and Electronics Engineering.": "Electrical Engineering",
            "Civil Engineering, General.": "Civil Engineering",
            "Chemical Engineering.": "Chemical Engineering",
            
            # Liberal Arts
            "English Language and Literature, General.": "English",
            "History, General.": "History",
            "Political Science and Government, General.": "Political Science", 
            "Sociology.": "Sociology",
            "Communication and Media Studies, General.": "Communications",
            "Journalism.": "Journalism",
            "Psychology, General.": "Psychology",
            
            # Health
            "Registered Nursing/Registered Nurse.": "Nursing",
            "Kinesiology and Exercise Science.": "Kinesiology",
            
            # Creative
            "Fine/Studio Arts, General.": "Art",
            "Music, General.": "Music", 
            "Drama and Dramatics/Theatre Arts, General.": "Theatre",
            "Graphic Design.": "Graphic Design",
            
            # Education  
            "Elementary Education and Teaching.": "Elementary Education",
            "Secondary Education and Teaching.": "Secondary Education",
            
            # Other
            "Criminal Justice/Safety Studies.": "Criminal Justice",
            "Social Work.": "Social Work"
        }
        
        # Priority ordering for search results (higher = appears first)
        self.priority_majors = [
            "Computer Science", "Business Administration", "Biology", "Psychology", 
            "Engineering", "Nursing", "Communications", "Marketing", "Accounting",
            "English", "History", "Criminal Justice", "Education", "Art", "Music",
            "Mathematics", "Chemistry", "Physics", "Computer Engineering",
            "Information Technology", "Finance", "Management", "Political Science",
            "Sociology", "Journalism", "Economics", "Kinesiology"
        ]
    
    def _clean_cip_title(self, title: str) -> str:
        """Clean up CIP title formatting issues"""
        if not title:
            return ""
            
        # Remove problematic formatting
        cleaned = re.sub(r'^[="]+|[="]+$', '', title)  # Remove leading/trailing =" 
        cleaned = re.sub(r'[="]+', '', cleaned)  # Remove any remaining =" sequences
        cleaned = cleaned.strip()
        
        return cleaned
    
    def _get_display_name(self, cip_title: str) -> str:
        """Get student-friendly display name for a major"""
        cleaned_title = self._clean_cip_title(cip_title)
        
        # Check if we have a specific mapping
        if cleaned_title in self.display_name_mappings:
            return self.display_name_mappings[cleaned_title]
        
        # For Computer Science related fields, create more friendly names
        if "computer" in cleaned_title.lower():
            if "science" in cleaned_title.lower():
                return "Computer Science"
            elif "engineering" in cleaned_title.lower():
                return "Computer Engineering"
            elif "programming" in cleaned_title.lower():
                return "Computer Programming"
            elif "information" in cleaned_title.lower():
                return "Information Technology"
        
        # Clean up generic formatting issues and make title case
        cleaned = re.sub(r'\.$', '', cleaned_title)  # Remove trailing period
        cleaned = re.sub(r'/.*$', '', cleaned)  # Remove everything after first slash
        cleaned = re.sub(r', General$', '', cleaned)  # Remove ", General" suffix
        cleaned = re.sub(r', Other$', '', cleaned)  # Remove ", Other" suffix
        
        # Handle specific problematic entries
        if "COMPUTER AND INFORMATION SCIENCES AND SUPPORT SERVICES" in cleaned:
            return "Computer Science"
        
        return cleaned.title() if cleaned else cleaned_title
    
    def _get_priority_score(self, display_name: str) -> int:
        """Get priority score for sorting (higher = more important)"""
        try:
            return len(self.priority_majors) - self.priority_majors.index(display_name)
        except ValueError:
            return 0  # Default priority for unmapped majors
    
    async def search_majors(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search majors by title with student-friendly display names"""
        try:
            # Search in both display_name, cip_title, and CIP code for maximum relevance
            response = self.client.table(self.table).select(
                "id, cip_code, cip_title, cip_family, display_name, search_priority"
            ).or_(
                f"display_name.ilike.%{query}%,cip_title.ilike.%{query}%,cip_code.ilike.%{query}%"
            ).order("search_priority", desc=True).order("display_name").limit(limit * 2).execute()
            
            # Process and deduplicate results
            seen_names = set()
            processed_results = []
            
            for item in response.data:
                # Use display_name if available, otherwise fall back to cleaned cip_title
                display_title = item.get('display_name') 
                if not display_title or display_title.strip() == '':
                    display_title = self._get_display_name(item.get('cip_title', ''))
                
                # Skip duplicates - only keep the first occurrence (which should be highest priority)
                if display_title in seen_names:
                    continue
                    
                seen_names.add(display_title)
                processed_results.append({
                    'id': item['id'],
                    'cip_code': item.get('cip_code', ''),
                    'cip_title': display_title,  # Use the friendly name in cip_title field for compatibility
                    'cip_family': item.get('cip_family', ''),
                    'display_name': display_title,  # Also provide in display_name field
                    'search_priority': item.get('search_priority', 0)
                })
            
            # Sort by priority and then alphabetically, limit to requested amount
            processed_results.sort(key=lambda x: (-x['search_priority'], x['display_name']))
            return processed_results[:limit]
            
        except Exception as e:
            print(f"Error searching majors: {str(e)}")
            raise
    
    async def get_major_by_id(self, major_id: str) -> Optional[Dict[str, Any]]:
        """Get a single major by ID"""
        try:
            response = self.client.table(self.table).select("*").eq("id", major_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error getting major by ID: {str(e)}")
            raise
    
    async def get_major_by_cip_code(self, cip_code: str) -> Optional[Dict[str, Any]]:
        """Get a major by CIP code"""
        try:
            response = self.client.table(self.table).select("*").eq("cip_code", cip_code).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error getting major by CIP code: {str(e)}")
            raise
    
    async def get_majors_by_family(self, cip_family: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get majors by CIP family"""
        try:
            response = self.client.table(self.table).select(
                "id, cip_code, cip_title, cip_family"
            ).eq("cip_family", cip_family).limit(limit).order("cip_title").execute()
            return response.data
        except Exception as e:
            print(f"Error getting majors by family: {str(e)}")
            raise
    
    async def get_major_count(self) -> int:
        """Get total count of majors in the directory"""
        try:
            response = self.client.table(self.table).select("count", count="exact").execute()
            return response.count
        except Exception as e:
            print(f"Error getting major count: {str(e)}")
            return 0