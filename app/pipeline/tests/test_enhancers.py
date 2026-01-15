"""
Unit tests for pipeline enhancers
"""
import pytest
from unittest.mock import Mock, patch

from app.pipeline.models import FieldData, PipelineContext
from app.pipeline.enhancers.field_splitter import FieldSplitterEnhancer
from app.pipeline.enhancers.data_cleaner import DataCleanerEnhancer
from app.pipeline.enhancers.address_validator import AddressValidationEnhancer
from app.pipeline.enhancers.high_school_matcher import HighSchoolMatcherEnhancer


def create_test_context(school_id="test_school"):
    """Helper to create test context"""
    return PipelineContext(
        school_id=school_id,
        user_id="test_user",
        event_id="test_event",
        image_path="test.jpg",
        valid_majors=["Computer Science", "Biology"],
        field_requirements={
            "first_name": {"required": True, "enabled": True},
            "last_name": {"required": True, "enabled": True},
            "city": {"required": False, "enabled": True},
            "state": {"required": False, "enabled": True}
        }
    )


class TestFieldSplitterEnhancer:
    """Test field splitting functionality"""
    
    def setup_method(self):
        self.enhancer = FieldSplitterEnhancer()
        self.context = create_test_context()
    
    def test_split_city_state_zip_with_commas(self):
        """Test splitting city, state, zip with comma format"""
        fields = {
            'city_state_zip': FieldData(value='Austin, TX, 78701', confidence=0.9, source='test')
        }
        
        result = self.enhancer.enhance(fields, self.context)
        
        assert 'city' in result
        assert result['city'].value == 'Austin'
        assert result['city'].source == 'address_split'
        
        assert 'state' in result
        assert result['state'].value == 'TX'
        
        assert 'zip_code' in result
        assert result['zip_code'].value == '78701'
    
    def test_split_city_state_no_zip(self):
        """Test splitting city, state without zip"""
        fields = {
            'city_state': FieldData(value='Dallas, TX', confidence=0.8, source='test')
        }
        
        result = self.enhancer.enhance(fields, self.context)
        
        assert 'city' in result
        assert result['city'].value == 'Dallas'
        
        assert 'state' in result
        assert result['state'].value == 'TX'
        
        assert 'zip_code' not in result
    
    def test_split_name_fields(self):
        """Test splitting full name into first and last"""
        fields = {
            'name': FieldData(value='John Smith', confidence=0.9, source='test')
        }
        
        result = self.enhancer.enhance(fields, self.context)
        
        assert 'first_name' in result
        assert result['first_name'].value == 'John'
        assert result['first_name'].source == 'name_split'
        
        assert 'last_name' in result  
        assert result['last_name'].value == 'Smith'
    
    def test_split_name_multiple_parts(self):
        """Test splitting name with multiple parts"""
        fields = {
            'name': FieldData(value='John Michael Smith Jr.', confidence=0.9, source='test')
        }
        
        result = self.enhancer.enhance(fields, self.context)
        
        assert result['first_name'].value == 'John'
        assert result['last_name'].value == 'Michael Smith Jr.'
    
    def test_dont_overwrite_existing_fields(self):
        """Test that existing fields aren't overwritten"""
        fields = {
            'city_state_zip': FieldData(value='Austin, TX, 78701', confidence=0.9, source='test'),
            'city': FieldData(value='Existing City', confidence=0.8, source='manual')
        }
        
        result = self.enhancer.enhance(fields, self.context)
        
        # Should not overwrite existing city
        assert result['city'].value == 'Existing City'
        assert result['city'].source == 'manual'
        
        # But should create state and zip
        assert result['state'].value == 'TX'
        assert result['zip_code'].value == '78701'


class TestDataCleanerEnhancer:
    """Test data cleaning functionality"""
    
    def setup_method(self):
        self.enhancer = DataCleanerEnhancer()
        self.context = create_test_context()
    
    def test_clean_phone_number_10_digits(self):
        """Test cleaning 10-digit phone number"""
        fields = {
            'cell': FieldData(value='5551234567', confidence=0.9, source='test')
        }
        
        result = self.enhancer.enhance(fields, self.context)
        
        assert result['cell'].value == '(555) 123-4567'
    
    def test_clean_phone_number_with_formatting(self):
        """Test cleaning phone number with existing formatting"""
        fields = {
            'phone': FieldData(value='(555) 123-4567 ext. 123', confidence=0.9, source='test')
        }
        
        result = self.enhancer.enhance(fields, self.context)
        
        assert result['phone'].value == '(555) 123-4567'
    
    def test_clean_phone_number_11_digits(self):
        """Test cleaning 11-digit phone number with country code"""
        fields = {
            'cell_phone': FieldData(value='15551234567', confidence=0.9, source='test')
        }
        
        result = self.enhancer.enhance(fields, self.context)
        
        assert result['cell_phone'].value == '(555) 123-4567'
    
    def test_clean_date_mm_dd_yyyy(self):
        """Test cleaning date in MM/DD/YYYY format"""
        fields = {
            'date_of_birth': FieldData(value='12/25/1990', confidence=0.9, source='test')
        }
        
        result = self.enhancer.enhance(fields, self.context)
        
        assert result['date_of_birth'].value == '12/25/1990'  # Should remain unchanged
    
    def test_clean_date_mm_dd_yy(self):
        """Test cleaning date in MM/DD/YY format"""
        fields = {
            'birthdate': FieldData(value='12/25/90', confidence=0.9, source='test')
        }
        
        result = self.enhancer.enhance(fields, self.context)
        
        assert result['birthdate'].value == '12/25/1990'  # Should convert to 4-digit year
    
    def test_clean_date_iso_format(self):
        """Test cleaning ISO format date"""
        fields = {
            'dob': FieldData(value='1990-12-25', confidence=0.9, source='test')
        }
        
        result = self.enhancer.enhance(fields, self.context)
        
        assert result['dob'].value == '12/25/1990'
    
    def test_clean_email(self):
        """Test cleaning email address"""
        fields = {
            'email': FieldData(value='  JOHN.DOE@EXAMPLE.COM  ', confidence=0.9, source='test')
        }
        
        result = self.enhancer.enhance(fields, self.context)
        
        assert result['email'].value == 'john.doe@example.com'
    
    def test_remove_na_values(self):
        """Test removing N/A values"""
        fields = {
            'cell': FieldData(value='N/A', confidence=0.9, source='test'),
            'email': FieldData(value='n/a', confidence=0.9, source='test'),
            'address': FieldData(value='None', confidence=0.9, source='test')
        }
        
        result = self.enhancer.enhance(fields, self.context)
        
        assert result['cell'].value == ''
        assert result['email'].value == ''
        assert result['address'].value == ''
    
    def test_general_text_cleanup(self):
        """Test general text cleanup"""
        fields = {
            'first_name': FieldData(value='  John   Michael  ', confidence=0.9, source='test'),
            'city': FieldData(value='Austin,,,', confidence=0.9, source='test')
        }
        
        result = self.enhancer.enhance(fields, self.context)
        
        assert result['first_name'].value == 'John Michael'  # Normalized whitespace
        assert result['city'].value == 'Austin'  # Removed trailing punctuation


class TestAddressValidationEnhancer:
    """Test address validation functionality"""
    
    def setup_method(self):
        self.enhancer = AddressValidationEnhancer()
        self.context = create_test_context()
    
    def test_should_run_with_address_fields(self):
        """Test that enhancer runs when address fields present"""
        fields = {
            'address': FieldData(value='123 Main St', confidence=0.9, source='test')
        }
        
        assert self.enhancer.should_run(fields, self.context) == True
    
    def test_should_not_run_without_address_fields(self):
        """Test that enhancer skips when no address fields"""
        fields = {
            'name': FieldData(value='John Smith', confidence=0.9, source='test')
        }
        
        assert self.enhancer.should_run(fields, self.context) == False
    
    @patch('app.pipeline.enhancers.address_validator.validate_address')
    def test_verified_address_updates_fields(self, mock_validate):
        """Test that verified addresses update field metadata"""
        # Mock successful validation
        mock_result = Mock()
        mock_result.state = "verified"
        mock_result.suggestion = {
            'address': '123 Main Street',
            'city': 'Austin', 
            'state': 'TX',
            'zip_code': '78701'
        }
        mock_validate.return_value = mock_result
        
        fields = {
            'address': FieldData(value='123 Main St', confidence=0.7, source='gemini'),
            'city': FieldData(value='Austin', confidence=0.7, source='gemini')
        }
        
        result = self.enhancer.enhance(fields, self.context)
        
        # Should update with Google Maps verified data
        assert result['address'].value == '123 Main Street'
        assert result['address'].source == 'google_maps_verified'
        assert result['address'].confidence == 1.0
        assert result['address'].validation_status == 'verified'
        
        # Should create new fields
        assert 'state' in result
        assert result['state'].value == 'TX'
        assert result['state'].source == 'google_maps_verified'
    
    @patch('app.pipeline.enhancers.address_validator.validate_address')
    def test_can_be_verified_adds_suggestions(self, mock_validate):
        """Test that 'can be verified' adds suggestions"""
        mock_result = Mock()
        mock_result.state = "can_be_verified"
        mock_result.suggestion = {
            'address': '123 Main Street',
            'city': 'Austin',
            'state': 'TX'
        }
        mock_validate.return_value = mock_result
        
        fields = {
            'address': FieldData(value='123 Main St', confidence=0.7, source='gemini', required=True)
        }
        
        result = self.enhancer.enhance(fields, self.context)
        
        assert result['address'].validation_status == 'can_be_verified'
        assert result['address'].suggestions == [mock_result.suggestion]
        assert result['address'].requires_human_review == True


class TestHighSchoolMatcherEnhancer:
    """Test high school matching functionality"""
    
    def setup_method(self):
        self.enhancer = HighSchoolMatcherEnhancer()
        self.context = create_test_context()
    
    def test_should_run_with_high_school(self):
        """Test that enhancer runs when high school field present"""
        fields = {
            'high_school': FieldData(value='Austin High School', confidence=0.9, source='test')
        }
        
        assert self.enhancer.should_run(fields, self.context) == True
    
    def test_should_not_run_without_high_school(self):
        """Test that enhancer skips when no high school field"""
        fields = {
            'name': FieldData(value='John Smith', confidence=0.9, source='test')
        }
        
        assert self.enhancer.should_not_run(fields, self.context) == False
    
    @patch('app.pipeline.enhancers.high_school_matcher.EnhancedHighSchoolMatchingService')
    def test_verified_match_adds_ceeb_code(self, mock_service_class):
        """Test that verified matches add CEEB codes"""
        # Mock the service
        mock_service = Mock()
        mock_service.validate_and_enhance_high_school.return_value = {
            'high_school': {
                'value': 'Austin High School',
                'source': 'high_school_directory',
                'confidence': 0.95
            },
            'ceeb_code': {
                'value': '123456',
                'source': 'high_school_directory'
            },
            'high_school_validation': {
                'status': 'verified',
                'confidence': 0.95,
                'match_type': 'exact',
                'suggestions': []
            }
        }
        mock_service_class.return_value = mock_service
        
        fields = {
            'high_school': FieldData(value='Austin HS', confidence=0.8, source='gemini')
        }
        
        result = self.enhancer.enhance(fields, self.context)
        
        # Should update high school
        assert result['high_school'].value == 'Austin High School'
        assert result['high_school'].source == 'high_school_directory'
        assert result['high_school'].confidence == 0.95
        assert result['high_school'].validation_status == 'verified'
        
        # Should add CEEB code
        assert 'ceeb_code' in result
        assert result['ceeb_code'].value == '123456'
        assert result['ceeb_code'].source == 'high_school_directory'


class TestEnhancerExecution:
    """Test enhancer execution wrapper"""
    
    def setup_method(self):
        self.enhancer = FieldSplitterEnhancer()
        self.context = create_test_context()
    
    def test_execute_success_tracking(self):
        """Test that execute() tracks successful operations"""
        fields = {
            'city_state_zip': FieldData(value='Austin, TX, 78701', confidence=0.9, source='test')
        }
        
        result_fields, execution_result = self.enhancer.execute(fields, self.context)
        
        assert execution_result.success == True
        assert execution_result.enhancer_name == 'FieldSplitterEnhancer'
        assert 'city' in execution_result.fields_added
        assert 'state' in execution_result.fields_added
        assert 'zip_code' in execution_result.fields_added
        assert execution_result.duration_ms > 0
    
    def test_execute_handles_exceptions(self):
        """Test that execute() handles exceptions gracefully"""
        # Create a mock enhancer that throws an exception
        class BrokenEnhancer(FieldSplitterEnhancer):
            def enhance(self, fields, context):
                raise ValueError("Test exception")
        
        broken_enhancer = BrokenEnhancer()
        fields = {'test': FieldData(value='test', confidence=0.9, source='test')}
        
        result_fields, execution_result = broken_enhancer.execute(fields, self.context)
        
        # Should return original fields unchanged
        assert result_fields == fields
        assert execution_result.success == False
        assert "Test exception" in execution_result.error
        assert execution_result.enhancer_name == 'BrokenEnhancer'
    
    def test_execute_respects_should_run(self):
        """Test that execute() respects should_run() method"""
        class ConditionalEnhancer(FieldSplitterEnhancer):
            def should_run(self, fields, context):
                return False  # Never run
            
            def enhance(self, fields, context):
                fields['should_not_exist'] = FieldData(value='test', confidence=1.0, source='test')
                return fields
        
        conditional = ConditionalEnhancer()
        fields = {'test': FieldData(value='test', confidence=0.9, source='test')}
        
        result_fields, execution_result = conditional.execute(fields, self.context)
        
        # Should skip execution
        assert 'should_not_exist' not in result_fields
        assert execution_result.success == True
        assert len(execution_result.fields_added) == 0
        assert execution_result.duration_ms == 0