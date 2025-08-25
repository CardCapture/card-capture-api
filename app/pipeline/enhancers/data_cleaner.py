"""
Data cleaner enhancer - cleans and formats field data
"""
import re
from typing import Dict
from app.pipeline.enhancers.base import FieldEnhancer
from app.pipeline.models import FieldData, PipelineContext
from app.utils.retry_utils import log_debug


class DataCleanerEnhancer(FieldEnhancer):
    """
    Cleans and formats field data.
    
    Handles:
    - Phone number formatting
    - Date formatting  
    - Email validation
    - Removing N/A values
    - Text cleanup (trimming, etc.)
    """
    
    def get_description(self) -> str:
        return "Clean and format field data (phones, dates, emails)"
    
    def enhance(self, fields: Dict[str, FieldData], context: PipelineContext) -> Dict[str, FieldData]:
        """Clean and format all applicable fields"""
        
        for field_name, field_data in fields.items():
            if not field_data.value or not isinstance(field_data.value, str):
                continue
                
            original_value = field_data.value
            cleaned_value = original_value
            
            # Clean based on field type
            if self._is_phone_field(field_name):
                cleaned_value = self._clean_phone_number(original_value)
                
            elif self._is_date_field(field_name):
                cleaned_value = self._clean_date(original_value)
                
            elif self._is_email_field(field_name):
                cleaned_value = self._clean_email(original_value)
                
            else:
                # General text cleanup
                cleaned_value = self._clean_text(original_value)
            
            # Update field if value changed
            if cleaned_value != original_value:
                field_data.value = cleaned_value
                if not field_data.original_value:
                    field_data.original_value = original_value
                log_debug(f"Cleaned {field_name}: '{original_value}' -> '{cleaned_value}'", service="pipeline")
        
        return fields
    
    def _is_phone_field(self, field_name: str) -> bool:
        """Check if field is a phone number field"""
        phone_fields = {
            'cell', 'cell_phone', 'phone', 'phone_number', 
            'mobile', 'mobile_phone', 'cellphone'
        }
        return field_name.lower() in phone_fields
    
    def _is_date_field(self, field_name: str) -> bool:
        """Check if field is a date field"""
        date_fields = {
            'date_of_birth', 'birthdate', 'dob', 'birth_date', 'birthday'
        }
        return field_name.lower() in date_fields
    
    def _is_email_field(self, field_name: str) -> bool:
        """Check if field is an email field"""
        email_fields = {
            'email', 'email_address', 'e_mail', 'emailaddress'
        }
        return field_name.lower() in email_fields
    
    def _clean_phone_number(self, phone: str) -> str:
        """
        Clean and format phone number.
        Standardizes to (XXX) XXX-XXXX format.
        """
        if not phone:
            return ""
        
        # Remove common N/A values
        if phone.upper() in ["N/A", "NA", "NONE", "NULL", "UNKNOWN"]:
            return ""
        
        # Extract just the digits
        digits = re.sub(r'[^\d]', '', phone)
        
        # Handle different digit lengths
        if len(digits) == 10:
            # Standard 10-digit US number
            return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        elif len(digits) == 11 and digits[0] == '1':
            # 11-digit with country code
            return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        elif len(digits) == 7:
            # 7-digit local number (add area code placeholder)
            return f"(XXX) {digits[:3]}-{digits[3:]}"
        else:
            # Return original if we can't parse it
            return phone.strip()
    
    def _clean_date(self, date_str: str) -> str:
        """
        Clean and format date string.
        Attempts to standardize to MM/DD/YYYY format.
        """
        if not date_str:
            return ""
        
        # Remove common N/A values
        if date_str.upper() in ["N/A", "NA", "NONE", "NULL", "UNKNOWN"]:
            return ""
        
        date_str = date_str.strip()
        
        # Try to parse various date formats
        
        # MM/DD/YYYY or MM-DD-YYYY
        match = re.match(r'^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$', date_str)
        if match:
            month, day, year = match.groups()
            return f"{month.zfill(2)}/{day.zfill(2)}/{year}"
        
        # MM/DD/YY or MM-DD-YY
        match = re.match(r'^(\d{1,2})[-/](\d{1,2})[-/](\d{2})$', date_str)
        if match:
            month, day, year = match.groups()
            # Convert 2-digit year to 4-digit (assuming 20xx for years < 30, 19xx otherwise)
            year_int = int(year)
            if year_int < 30:
                full_year = f"20{year}"
            else:
                full_year = f"19{year}"
            return f"{month.zfill(2)}/{day.zfill(2)}/{full_year}"
        
        # YYYY-MM-DD (ISO format)
        match = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', date_str)
        if match:
            year, month, day = match.groups()
            return f"{month.zfill(2)}/{day.zfill(2)}/{year}"
        
        # Month DD, YYYY
        match = re.match(r'^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$', date_str)
        if match:
            month_name, day, year = match.groups()
            month_num = self._month_name_to_number(month_name.lower())
            if month_num:
                return f"{month_num.zfill(2)}/{day.zfill(2)}/{year}"
        
        # If we can't parse it, return original
        return date_str
    
    def _month_name_to_number(self, month_name: str) -> str:
        """Convert month name to number"""
        months = {
            'january': '1', 'jan': '1',
            'february': '2', 'feb': '2',
            'march': '3', 'mar': '3',
            'april': '4', 'apr': '4',
            'may': '5',
            'june': '6', 'jun': '6',
            'july': '7', 'jul': '7',
            'august': '8', 'aug': '8',
            'september': '9', 'sep': '9', 'sept': '9',
            'october': '10', 'oct': '10',
            'november': '11', 'nov': '11',
            'december': '12', 'dec': '12'
        }
        return months.get(month_name.lower(), '')
    
    def _clean_email(self, email: str) -> str:
        """
        Clean email address.
        Validates basic format and cleans whitespace.
        """
        if not email:
            return ""
        
        # Remove common N/A values
        if email.upper() in ["N/A", "NA", "NONE", "NULL", "UNKNOWN"]:
            return ""
        
        email = email.strip().lower()
        
        # Basic email validation
        if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            return email
        
        # If it doesn't look like an email, return empty
        # This prevents garbage data from being stored
        if '@' not in email or '.' not in email:
            return ""
        
        return email
    
    def _clean_text(self, text: str) -> str:
        """
        General text cleanup.
        Removes extra whitespace and common placeholder values.
        """
        if not text:
            return ""
        
        # Remove common N/A values
        if text.upper() in ["N/A", "NA", "NONE", "NULL", "UNKNOWN", "NOT APPLICABLE", "NOT AVAILABLE"]:
            return ""
        
        # Clean whitespace
        text = re.sub(r'\s+', ' ', text.strip())
        
        # Remove trailing punctuation that might be OCR artifacts
        text = re.sub(r'[.,;:]+$', '', text)
        
        return text