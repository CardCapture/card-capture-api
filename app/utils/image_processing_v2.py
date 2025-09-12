"""
Enhanced Image Processing with PhotoRoom Integration
Handles HEIC support and background removal
"""

import os
import logging
from pathlib import Path
from typing import Optional
from PIL import Image, ImageOps
import pillow_heif

# Import existing functions we'll keep
from app.utils.image_processing import (
    ensure_proper_orientation,
    detect_card_boundaries,
    trim_image_with_docai
)

# Import PhotoRoom service
from app.services.photoroom_service import get_photoroom_service

# Register HEIF opener
pillow_heif.register_heif_opener()

logger = logging.getLogger(__name__)

def convert_heic_to_jpeg(input_path: str, output_path: Optional[str] = None) -> str:
    """
    Convert HEIC/HEIF image to JPEG format
    
    Args:
        input_path: Path to HEIC file
        output_path: Optional output path (auto-generated if None)
        
    Returns:
        Path to converted JPEG file
    """
    try:
        logger.info(f"Converting HEIC image: {input_path}")
        
        # Generate output path if not provided
        if not output_path:
            base_path = Path(input_path).with_suffix('.jpg')
            output_path = str(base_path)
        
        # Open and convert HEIC
        img = Image.open(input_path)
        
        # Apply EXIF orientation
        img = ImageOps.exif_transpose(img)
        
        # Convert to RGB
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Save as JPEG
        img.save(output_path, 'JPEG', quality=95, optimize=True)
        
        logger.info(f"HEIC converted to: {output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"Error converting HEIC: {e}")
        raise

def process_uploaded_image(
    input_path: str,
    use_photoroom: bool = True,
    fallback_to_boundary: bool = True,
    output_dir: Optional[str] = None
) -> str:
    """
    Main image processing pipeline with PhotoRoom integration
    
    Args:
        input_path: Path to uploaded image
        use_photoroom: Whether to use PhotoRoom for background removal
        fallback_to_boundary: Fall back to boundary detection if PhotoRoom fails
        output_dir: Optional output directory
        
    Returns:
        Path to processed image
    """
    try:
        logger.info(f"Processing uploaded image: {input_path}")
        
        # Check file extension
        file_ext = Path(input_path).suffix.lower()
        
        # Handle HEIC conversion first
        if file_ext in ['.heic', '.heif']:
            logger.info("HEIC file detected, converting to JPEG...")
            converted_path = convert_heic_to_jpeg(input_path)
            working_path = converted_path
        else:
            working_path = input_path
        
        # Apply EXIF orientation for all images
        oriented_path = ensure_proper_orientation(working_path)
        
        # Try PhotoRoom background removal if enabled
        if use_photoroom:
            try:
                logger.info("Using PhotoRoom for background removal...")
                photoroom_service = get_photoroom_service()
                
                result = photoroom_service.remove_background(
                    oriented_path,
                    output_dir=output_dir
                )
                
                if result['success']:
                    # Return white background version (production default)
                    return result['white_bg_path']
                else:
                    logger.warning(f"PhotoRoom failed: {result.get('message')}")
                    
            except Exception as e:
                logger.error(f"PhotoRoom error: {e}")
        
        # Fallback to boundary detection if PhotoRoom fails or is disabled
        if fallback_to_boundary:
            logger.info("Falling back to boundary detection...")
            
            # Try conservative threshold for white cards
            boundaries = detect_card_boundaries(
                oriented_path,
                white_threshold=250,
                use_color_detection=True
            )
            
            if boundaries:
                # Crop to detected boundaries
                img = Image.open(oriented_path)
                left, top, right, bottom = boundaries
                cropped = img.crop((left, top, right, bottom))
                
                # Save cropped image
                if output_dir:
                    output_path = Path(output_dir) / f"{Path(input_path).stem}_processed.jpg"
                else:
                    output_path = Path(input_path).parent / f"{Path(input_path).stem}_processed.jpg"
                
                output_path.parent.mkdir(parents=True, exist_ok=True)
                cropped.save(output_path, 'JPEG', quality=95, optimize=True)
                
                logger.info(f"Boundary detection successful: {output_path}")
                return str(output_path)
        
        # If all processing fails, return oriented image
        logger.warning("All processing methods failed, returning oriented image")
        return oriented_path
        
    except Exception as e:
        logger.error(f"Error in process_uploaded_image: {e}")
        # Return original on any error
        return input_path

def validate_image_format(file_path: str) -> bool:
    """
    Validate if the uploaded file is a supported image format
    
    Args:
        file_path: Path to file
        
    Returns:
        True if supported format, False otherwise
    """
    supported_formats = {
        '.jpg', '.jpeg', '.png', '.gif', '.bmp',
        '.tiff', '.tif', '.webp', '.heic', '.heif',
        '.pdf'  # PDFs are converted to images
    }
    
    file_ext = Path(file_path).suffix.lower()
    return file_ext in supported_formats

def get_image_dimensions(image_path: str) -> tuple:
    """
    Get image dimensions, handling HEIC files
    
    Args:
        image_path: Path to image
        
    Returns:
        Tuple of (width, height)
    """
    try:
        img = Image.open(image_path)
        return img.size
    except Exception as e:
        logger.error(f"Error getting image dimensions: {e}")
        return (0, 0)

def optimize_image_for_storage(
    image_path: str,
    max_size: int = 2048,
    quality: int = 85
) -> str:
    """
    Optimize image for storage by resizing and compressing
    
    Args:
        image_path: Path to image
        max_size: Maximum dimension (width or height)
        quality: JPEG quality (1-100)
        
    Returns:
        Path to optimized image
    """
    try:
        img = Image.open(image_path)
        
        # Apply EXIF orientation
        img = ImageOps.exif_transpose(img)
        
        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Resize if too large
        if max(img.size) > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        
        # Save optimized version
        optimized_path = Path(image_path).with_suffix('.jpg')
        img.save(optimized_path, 'JPEG', quality=quality, optimize=True)
        
        logger.info(f"Image optimized: {optimized_path}")
        return str(optimized_path)
        
    except Exception as e:
        logger.error(f"Error optimizing image: {e}")
        return image_path

# Enhanced version of the main processing function
def ensure_trimmed_image_v2(
    original_image_path: str,
    use_photoroom: bool = True,
    optimize_for_storage: bool = False
) -> str:
    """
    Enhanced image processing pipeline with PhotoRoom integration
    
    Args:
        original_image_path: Path to original image
        use_photoroom: Whether to use PhotoRoom API
        optimize_for_storage: Whether to optimize image size
        
    Returns:
        Path to processed image
    """
    logger.info(f"Processing image (v2): {original_image_path}")
    
    try:
        # Process with PhotoRoom and fallbacks
        processed_path = process_uploaded_image(
            original_image_path,
            use_photoroom=use_photoroom,
            fallback_to_boundary=True
        )
        
        # Optionally optimize for storage
        if optimize_for_storage:
            processed_path = optimize_image_for_storage(processed_path)
        
        return processed_path
        
    except Exception as e:
        logger.error(f"Error in ensure_trimmed_image_v2: {e}")
        return original_image_path