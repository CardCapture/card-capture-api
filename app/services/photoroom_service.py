"""
PhotoRoom API Service for Background Removal
Production-ready implementation with HEIC support
"""

import os
import http.client
import mimetypes
import uuid
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from PIL import Image
import io
from pdf2image import convert_from_path
from dotenv import load_dotenv
import logging
import tempfile

# Register HEIF opener with Pillow if available
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_AVAILABLE = True
except ImportError:
    HEIC_AVAILABLE = False

logger = logging.getLogger(__name__)

class PhotoRoomService:
    """
    Production service for removing backgrounds from card images using PhotoRoom API.
    Supports JPG, PNG, HEIC/HEIF, and PDF formats.
    """
    
    def __init__(self):
        """Initialize PhotoRoom service with API key from environment"""
        load_dotenv()
        self.api_key = os.getenv('PHOTO_ROOM_API_KEY')
        if not self.api_key:
            raise ValueError("PHOTO_ROOM_API_KEY not found in environment variables")
        
        self.api_host = "sdk.photoroom.com"
        self.api_endpoint = "/v1/segment"
        
    def convert_heic_to_jpeg(self, heic_path: str) -> Tuple[bytes, str]:
        """
        Convert HEIC/HEIF image to JPEG format
        
        Args:
            heic_path: Path to HEIC file
            
        Returns:
            Tuple of (image_bytes, mime_type)
        """
        try:
            if not HEIC_AVAILABLE:
                raise ValueError("HEIC support not available - pillow_heif not installed")
                
            logger.info(f"Converting HEIC image: {heic_path}")
            
            # Open HEIC image using pillow_heif
            img = Image.open(heic_path)
            
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Save to bytes as JPEG
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='JPEG', quality=95)
            img_byte_arr = img_byte_arr.getvalue()
            
            logger.info("HEIC conversion successful")
            return img_byte_arr, 'image/jpeg'
            
        except Exception as e:
            logger.error(f"Error converting HEIC: {e}")
            raise
    
    def convert_pdf_to_image(self, pdf_path: str) -> Tuple[bytes, str]:
        """
        Convert PDF to PNG image (first page only)
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Tuple of (image_bytes, mime_type)
        """
        try:
            logger.info(f"Converting PDF to image: {pdf_path}")
            
            # Convert PDF to PIL Image (300 DPI for quality)
            images = convert_from_path(pdf_path, dpi=300)
            
            if not images:
                raise ValueError("No pages found in PDF")
            
            # Take the first page
            img = images[0]
            
            # Convert to PNG bytes
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG')
            img_byte_arr = img_byte_arr.getvalue()
            
            logger.info("PDF conversion successful")
            return img_byte_arr, 'image/png'
            
        except Exception as e:
            logger.error(f"Error converting PDF: {e}")
            raise
    
    def prepare_image_data(self, image_path: str) -> Tuple[bytes, str, str]:
        """
        Prepare image data for API submission, handling various formats
        
        Args:
            image_path: Path to image file
            
        Returns:
            Tuple of (image_bytes, mime_type, filename)
        """
        file_ext = Path(image_path).suffix.lower()
        file_name = Path(image_path).name
        
        # Handle HEIC/HEIF files
        if file_ext in ['.heic', '.heif']:
            image_data, content_type = self.convert_heic_to_jpeg(image_path)
            # Change filename extension for API
            file_name = Path(image_path).stem + '.jpg'
            
        # Handle PDF files
        elif file_ext == '.pdf':
            image_data, content_type = self.convert_pdf_to_image(image_path)
            file_name = Path(image_path).stem + '.png'
            
        # Handle standard image formats
        else:
            with open(image_path, 'rb') as f:
                image_data = f.read()
            
            # Detect MIME type
            content_type = mimetypes.guess_type(image_path)[0]
            if not content_type:
                if file_ext in ['.jpg', '.jpeg']:
                    content_type = 'image/jpeg'
                elif file_ext == '.png':
                    content_type = 'image/png'
                else:
                    content_type = 'image/jpeg'  # Default fallback
        
        return image_data, content_type, file_name
    
    def remove_background(self, image_path: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Remove background from image using PhotoRoom API
        
        Args:
            image_path: Path to input image
            output_dir: Optional output directory (uses temp if not specified)
            
        Returns:
            Dictionary with status and output path
        """
        try:
            logger.info(f"Processing image: {image_path}")
            
            # Validate input file exists
            if not os.path.exists(image_path):
                raise FileNotFoundError(f"Image not found: {image_path}")
            
            # Prepare output directory
            if output_dir:
                output_path_base = Path(output_dir)
                output_path_base.mkdir(parents=True, exist_ok=True)
            else:
                output_path_base = Path(tempfile.gettempdir())
            
            # Prepare image data
            image_data, content_type, file_name = self.prepare_image_data(image_path)
            
            # Generate multipart boundary
            boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
            
            # Build multipart request body
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="image_file"; filename="{file_name}"\r\n'
                f"Content-Type: {content_type}\r\n"
                f"\r\n"
            ).encode('utf-8')
            
            body += image_data
            body += f"\r\n--{boundary}--\r\n".encode('utf-8')
            
            # Make API request
            conn = http.client.HTTPSConnection(self.api_host)
            
            try:
                headers = {
                    'x-api-key': self.api_key,
                    'Content-Type': f'multipart/form-data; boundary={boundary}'
                }
                
                logger.info("Calling PhotoRoom API...")
                conn.request("POST", self.api_endpoint, body, headers)
                response = conn.getresponse()
                
                if response.status == 200:
                    result_data = response.read()
                    
                    # Save transparent PNG result
                    transparent_filename = f"{Path(image_path).stem}_no_bg.png"
                    transparent_path = output_path_base / transparent_filename
                    
                    with open(transparent_path, 'wb') as f:
                        f.write(result_data)
                    
                    # Create white background version (production default)
                    white_bg_path = self.create_white_background_version(
                        transparent_path, 
                        output_path_base
                    )
                    
                    logger.info(f"Background removal successful: {white_bg_path}")
                    
                    return {
                        'success': True,
                        'white_bg_path': str(white_bg_path),
                        'transparent_path': str(transparent_path),
                        'message': 'Background removed successfully'
                    }
                    
                else:
                    error_msg = response.read().decode('utf-8')
                    logger.error(f"PhotoRoom API error ({response.status}): {error_msg}")
                    
                    return {
                        'success': False,
                        'error': f"API error {response.status}",
                        'message': error_msg
                    }
                    
            finally:
                conn.close()
                
        except Exception as e:
            logger.error(f"Error in remove_background: {e}")
            return {
                'success': False,
                'error': str(e),
                'message': f"Failed to process image: {str(e)}"
            }
    
    def create_white_background_version(self, transparent_path: Path, output_dir: Path) -> Path:
        """
        Create a white background version from transparent PNG
        
        Args:
            transparent_path: Path to transparent PNG
            output_dir: Directory for output
            
        Returns:
            Path to white background image
        """
        try:
            img = Image.open(transparent_path)
            
            # Create white background only if image has transparency
            if img.mode in ('RGBA', 'LA'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                
                if img.mode == 'RGBA':
                    background.paste(img, mask=img.split()[3])
                else:
                    background.paste(img, mask=img.split()[1])
                
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Save as JPEG with white background
            white_bg_filename = f"{transparent_path.stem.replace('_no_bg', '')}_processed.jpg"
            white_bg_path = output_dir / white_bg_filename
            
            img.save(white_bg_path, 'JPEG', quality=95, optimize=True)
            
            return white_bg_path
            
        except Exception as e:
            logger.error(f"Error creating white background version: {e}")
            # Return transparent version if white bg creation fails
            return transparent_path
    
    def process_batch(self, image_paths: list, output_dir: Optional[str] = None) -> list:
        """
        Process multiple images in batch
        
        Args:
            image_paths: List of image paths to process
            output_dir: Optional output directory
            
        Returns:
            List of results for each image
        """
        results = []
        
        for image_path in image_paths:
            logger.info(f"Processing {len(results) + 1}/{len(image_paths)}: {image_path}")
            result = self.remove_background(image_path, output_dir)
            results.append({
                'input': image_path,
                **result
            })
        
        # Summary
        success_count = sum(1 for r in results if r.get('success'))
        logger.info(f"Batch processing complete: {success_count}/{len(results)} successful")
        
        return results


# Singleton instance for easy import
_service_instance = None

def get_photoroom_service() -> PhotoRoomService:
    """Get singleton instance of PhotoRoom service"""
    global _service_instance
    if _service_instance is None:
        _service_instance = PhotoRoomService()
    return _service_instance