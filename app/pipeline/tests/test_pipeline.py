"""
Integration tests for the main pipeline
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
import tempfile
import os

from app.pipeline.pipeline import CardProcessingPipeline
from app.pipeline.models import FieldData, ProcessingStage


class TestCardProcessingPipeline:
    """Test the main pipeline integration"""
    
    def setup_method(self):
        self.pipeline = CardProcessingPipeline()
        
        # Create a temporary image file for testing
        self.temp_image = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
        self.temp_image.write(b'fake image data')
        self.temp_image.close()
    
    def teardown_method(self):
        # Clean up temporary file
        if os.path.exists(self.temp_image.name):
            os.unlink(self.temp_image.name)
    
    @patch('app.pipeline.pipeline.get_supabase_client')
    @patch('app.pipeline.pipeline.process_image_with_docai')
    @patch('app.pipeline.pipeline.process_card_with_gemini_v2')
    @patch('app.pipeline.pipeline.get_field_requirements')
    @patch('app.pipeline.pipeline.sync_field_requirements')
    @patch('app.pipeline.pipeline.determine_review_status')
    @patch('app.pipeline.pipeline.validate_field_data')
    @patch('app.pipeline.pipeline.filter_combined_fields')
    def test_full_pipeline_success(
        self, mock_filter, mock_validate, mock_review, mock_sync_req,
        mock_get_req, mock_gemini, mock_docai, mock_supabase
    ):
        """Test successful pipeline execution end-to-end"""
        
        # Mock Supabase
        mock_client = Mock()
        mock_client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = Mock(
            data={'majors': ['Computer Science', 'Biology']}
        )
        mock_supabase.return_value = mock_client
        
        # Mock DocAI (returns 4 values: fields, cropped_path, ocr_text, serial_number)
        mock_docai.return_value = (
            {
                'first_name': {'value': 'John', 'confidence': 0.8, 'source': 'docai'},
                'last_name': {'value': 'Doe', 'confidence': 0.8, 'source': 'docai'}
            },
            '/tmp/cropped.jpg',
            'OCR text here',
            None  # serial_number
        )
        
        # Mock Gemini  
        mock_gemini.return_value = {
            'first_name': {'value': 'John', 'confidence': 0.9, 'source': 'gemini'},
            'last_name': {'value': 'Doe', 'confidence': 0.9, 'source': 'gemini'},
            'email': {'value': 'john.doe@email.com', 'confidence': 0.85, 'source': 'gemini'}
        }
        
        # Mock field requirements
        mock_get_req.return_value = {
            'first_name': {'required': True, 'enabled': True},
            'last_name': {'required': True, 'enabled': True}
        }
        mock_sync_req.return_value = {
            'first_name': {'required': True, 'enabled': True},
            'last_name': {'required': True, 'enabled': True},
            'email': {'required': False, 'enabled': True}
        }
        
        # Mock review services
        mock_validate.return_value = {
            'first_name': {'value': 'John', 'confidence': 0.9, 'required': True},
            'last_name': {'value': 'Doe', 'confidence': 0.9, 'required': True},
            'email': {'value': 'john.doe@email.com', 'confidence': 0.85, 'required': False}
        }
        mock_review.return_value = ('reviewed', [])
        mock_filter.return_value = {
            'first_name': {'value': 'John', 'confidence': 0.9, 'required': True},
            'last_name': {'value': 'Doe', 'confidence': 0.9, 'required': True},
            'email': {'value': 'john.doe@email.com', 'confidence': 0.85, 'required': False}
        }
        
        # Run the pipeline
        result = self.pipeline.process(
            image_path=self.temp_image.name,
            school_id='test_school',
            user_id='test_user',
            event_id='test_event'
        )
        
        # Verify results
        assert result.stage == ProcessingStage.REVIEW
        assert 'first_name' in result.fields
        assert 'last_name' in result.fields
        assert 'email' in result.fields
        assert result.metadata['review_status'] == 'reviewed'
        assert result.metadata['fields_needing_review'] == []
        
        # Verify services were called
        mock_docai.assert_called_once()
        mock_gemini.assert_called_once()
        mock_review.assert_called_once()
        mock_validate.assert_called_once()
    
    def test_enhancer_order_matters(self):
        """Test that enhancers are in the correct order"""
        enhancer_names = [e.__class__.__name__ for e in self.pipeline.enhancers]

        expected_order = [
            'CanonicalFieldMapperEnhancer', # Maps name -> first_name/last_name
            'FieldSplitterEnhancer',        # Splits combined fields
            'FieldRequirementsEnhancer',    # Applies school settings
            'DataCleanerEnhancer',          # Cleans data before validation
            'AddressValidationEnhancer',    # Validates addresses
            'HighSchoolMatcherEnhancer'     # Matches high schools
        ]

        assert enhancer_names == expected_order
    
    @patch('app.pipeline.pipeline.get_supabase_client')
    @patch('app.pipeline.pipeline.get_field_requirements')
    def test_build_context(self, mock_get_req, mock_supabase):
        """Test context building"""
        # Mock Supabase response
        mock_client = Mock()
        mock_client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = Mock(
            data={'majors': ['Math', 'Science']}
        )
        mock_supabase.return_value = mock_client
        
        # Mock field requirements
        mock_get_req.return_value = {'test_field': {'required': True}}
        
        context = self.pipeline._build_context('school123', 'user456', 'event789', 'test.jpg')
        
        assert context.school_id == 'school123'
        assert context.user_id == 'user456'
        assert context.event_id == 'event789'
        assert context.image_path == 'test.jpg'
        assert context.valid_majors == ['Math', 'Science']
        assert 'test_field' in context.field_requirements
    
    @patch('app.pipeline.pipeline.get_supabase_client')
    def test_build_context_no_majors(self, mock_supabase):
        """Test context building when school has no majors"""
        # Mock Supabase response with no data
        mock_client = Mock()
        mock_client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = Mock(
            data=None
        )
        mock_supabase.return_value = mock_client
        
        with patch('app.pipeline.pipeline.get_field_requirements', return_value={}):
            context = self.pipeline._build_context('school123', 'user456', None, 'test.jpg')
        
        assert context.valid_majors == []
        assert context.event_id is None
    
    def test_pipeline_handles_enhancer_failures(self):
        """Test that pipeline continues even if enhancers fail"""
        # Create a custom pipeline with a failing enhancer
        class FailingEnhancer:
            def __init__(self):
                self.name = "FailingEnhancer"
            
            def execute(self, fields, context):
                from app.pipeline.models import EnhancerResult
                return fields, EnhancerResult(
                    enhancer_name=self.name,
                    fields_modified=[],
                    fields_added=[],
                    success=False,
                    error="Test failure"
                )
        
        # Replace first enhancer with failing one
        self.pipeline.enhancers[0] = FailingEnhancer()
        
        # Mock all the external dependencies
        with patch('app.pipeline.pipeline.get_supabase_client') as mock_supabase, \
             patch('app.pipeline.pipeline.process_image_with_docai') as mock_docai, \
             patch('app.pipeline.pipeline.process_card_with_gemini_v2') as mock_gemini, \
             patch('app.pipeline.pipeline.get_field_requirements') as mock_get_req, \
             patch('app.pipeline.pipeline.sync_field_requirements') as mock_sync_req, \
             patch('app.pipeline.pipeline.determine_review_status') as mock_review, \
             patch('app.pipeline.pipeline.validate_field_data') as mock_validate, \
             patch('app.pipeline.pipeline.filter_combined_fields') as mock_filter:
            
            # Setup mocks
            mock_client = Mock()
            mock_client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = Mock(
                data={'majors': []}
            )
            mock_supabase.return_value = mock_client
            
            mock_docai.return_value = ({'test': {'value': 'test', 'confidence': 0.8}}, '/tmp/test.jpg', 'OCR text', None)
            mock_gemini.return_value = {'test': {'value': 'test', 'confidence': 0.8}}
            mock_get_req.return_value = {}
            mock_sync_req.return_value = {}
            mock_validate.return_value = {'test': {'value': 'test', 'confidence': 0.8}}
            mock_review.return_value = ('reviewed', [])
            mock_filter.return_value = {'test': {'value': 'test', 'confidence': 0.8}}
            
            # Run pipeline
            result = self.pipeline.process(
                image_path=self.temp_image.name,
                school_id='test_school',
                user_id='test_user'
            )
            
            # Should still complete successfully
            assert result.stage == ProcessingStage.REVIEW
            
            # Should record the enhancer failure
            enhancer_results = result.metadata['enhancer_results']
            failed_enhancer = next((r for r in enhancer_results if r['enhancer_name'] == 'FailingEnhancer'), None)
            assert failed_enhancer is not None
            assert failed_enhancer['success'] is False
            assert 'Test failure' in failed_enhancer['error']