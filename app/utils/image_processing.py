"""
Integrated Image Processing with PhotoRoom
Production-ready replacement for image_processing.py
Maintains backwards compatibility while adding PhotoRoom support
"""

import os
import logging
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image, ImageOps
import numpy as np
from scipy import ndimage
from google.cloud import documentai_v1 as documentai

# Import configuration
from app.config import PROJECT_ID, DOCAI_LOCATION, DOCAI_PROCESSOR_ID, TRIMMED_FOLDER
from app.utils.retry_utils import log_debug

# Import PhotoRoom service
try:
    from app.services.photoroom_service import get_photoroom_service
    PHOTOROOM_AVAILABLE = True
except ImportError:
    PHOTOROOM_AVAILABLE = False
    log_debug("[WARNING] PhotoRoom service not available, using fallback methods only", service="image_processing")

# Register HEIF opener if available
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_SUPPORT = True
    log_debug("[INFO] HEIC support enabled", service="image_processing")
except ImportError:
    HEIC_SUPPORT = False
    log_debug("[WARNING] HEIC support not available - pillow_heif not installed", service="image_processing")
except Exception as e:
    HEIC_SUPPORT = False
    log_debug(f"[WARNING] HEIC support failed to initialize: {e}", service="image_processing")

logger = logging.getLogger(__name__)

# Feature flag for PhotoRoom (can be controlled via environment)
USE_PHOTOROOM = os.getenv('USE_PHOTOROOM', 'true').lower() == 'true' and PHOTOROOM_AVAILABLE


def ensure_proper_orientation(image_path: str) -> str:
    """
    Properly handle EXIF orientation and prepare image for processing.
    Handles HEIC conversion if needed.
    """
    try:
        # Check if HEIC and convert if needed
        file_ext = Path(image_path).suffix.lower()
        if file_ext in ['.heic', '.heif'] and HEIC_SUPPORT:
            log_debug(f"[Orientation] Converting HEIC file: {image_path}", service="image_processing")
            img = Image.open(image_path)
            img = ImageOps.exif_transpose(img)
            
            # Convert to RGB
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Save as JPEG
            base_path, _ = os.path.splitext(image_path)
            processed_path = f"{base_path}_processed.jpg"
            img.save(processed_path, format='JPEG', quality=95, optimize=True)
            log_debug(f"[Orientation] HEIC converted to: {processed_path}", service="image_processing")
            return processed_path
        
        # Regular image processing
        img = Image.open(image_path)
        
        # This handles EXIF orientation automatically
        img = ImageOps.exif_transpose(img)
        log_debug(f"EXIF orientation applied successfully", service="image_processing")
        
        # Check aspect ratio for logging
        aspect_ratio = img.width / img.height
        if aspect_ratio > 1.5:
            log_debug(f"Detected horizontal card format (aspect ratio: {aspect_ratio:.2f})", service="image_processing")
        elif aspect_ratio < 0.7:
            log_debug(f"Detected vertical card format (aspect ratio: {aspect_ratio:.2f})", service="image_processing")
        else:
            log_debug(f"Square/ambiguous format (aspect ratio: {aspect_ratio:.2f})", service="image_processing")
        
        # Convert to RGB if needed
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        
        # Save processed image
        base_path, ext = os.path.splitext(image_path)
        processed_path = f"{base_path}_processed{ext}"
        img.save(processed_path, format='JPEG', quality=100, optimize=True)
        log_debug(f"Processed image saved to: {processed_path}", service="image_processing")
        
        return processed_path
        
    except Exception as e:
        log_debug(f"[Orientation] Error: {e}", service="image_processing")
        return image_path


def detect_card_boundaries(image_path: str, padding: int = 20, white_threshold: int = 245, use_color_detection: bool = True) -> tuple:
    """
    Detect the actual card boundaries (existing fallback method)
    """
    try:
        img = Image.open(image_path)
        img = ImageOps.exif_transpose(img)
        
        if use_color_detection:
            img_array = np.array(img)
            
            if len(img_array.shape) == 3:
                color_std = np.std(img_array, axis=2)
                brightness = np.mean(img_array, axis=2)
                not_background = brightness > (white_threshold - 40)
                allow_variation = color_std < 50
                potential_card = not_background | (brightness > 240)
                
                structure = np.ones((3, 3))
                potential_card = ndimage.binary_opening(potential_card, structure=structure)
                
                labeled_array, num_features = ndimage.label(potential_card)
                
                if num_features > 0:
                    component_sizes = [(labeled_array == i).sum() for i in range(1, num_features + 1)]
                    min_card_size = img.width * img.height * 0.1
                    valid_components = []
                    
                    for i, size in enumerate(component_sizes):
                        if size > min_card_size:
                            valid_components.append((i + 1, size))
                    
                    if valid_components:
                        largest_component = max(valid_components, key=lambda x: x[1])[0]
                        card_mask = labeled_array == largest_component
                    else:
                        log_debug("[CardBoundary] No large enough components found", service="image_processing")
                        card_mask = potential_card
                else:
                    card_mask = potential_card
            else:
                img_array = np.array(img.convert('L'))
                card_mask = img_array > white_threshold
        else:
            img_array = np.array(img.convert('L'))
            card_mask = img_array < white_threshold
        
        rows = np.any(card_mask, axis=1)
        cols = np.any(card_mask, axis=0)

        if not np.any(rows) or not np.any(cols):
            log_debug("[CardBoundary] No card detected - trying fallback", service="image_processing")
            img_gray = np.array(img.convert('L'))
            non_white = img_gray < (white_threshold - 50)
            rows = np.any(non_white, axis=1)
            cols = np.any(non_white, axis=0)

            if not np.any(rows) or not np.any(cols):
                log_debug("[CardBoundary] Fallback also failed", service="image_processing")
                return None
        
        top, bottom = np.where(rows)[0][[0, -1]]
        left, right = np.where(cols)[0][[0, -1]]
        
        safe_padding = max(padding, 40)
        left = max(0, left - safe_padding)
        top = max(0, top - safe_padding)
        right = min(img.width, right + safe_padding)
        bottom = min(img.height, bottom + safe_padding)

        log_debug(f"[CardBoundary] Detected: ({left}, {top}) to ({right}, {bottom})", service="image_processing")

        return (left, top, right, bottom)
        
    except Exception as e:
        log_debug(f"[CardBoundary] Error: {e}", service="image_processing")
        return None


def trim_image_with_docai(input_path: str, output_path: str = None, percent_expand: float = 0.5) -> str:
    """
    Uses Google Document AI to find the bounding box (existing method)
    """
    try:
        if not output_path:
            filename = os.path.basename(input_path)
            name, ext = os.path.splitext(filename)
            output_path = os.path.join(TRIMMED_FOLDER, f"{name}_trimmed{ext}")
        
        client = documentai.DocumentProcessorServiceClient()
        name = f"projects/{PROJECT_ID}/locations/{DOCAI_LOCATION}/processors/{DOCAI_PROCESSOR_ID}"
        
        with open(input_path, "rb") as image_file:
            image_content = image_file.read()
        
        raw_document = documentai.RawDocument(content=image_content, mime_type="image/jpeg")
        request = documentai.ProcessRequest(name=name, raw_document=raw_document)
        result = client.process_document(request=request)
        document = result.document
        
        all_vertices = []
        for entity in getattr(document, "entities", []):
            if entity.page_anchor and entity.page_anchor.page_refs:
                for page_ref in entity.page_anchor.page_refs:
                    page_index = page_ref.page
                    page = document.pages[page_index]
                    width = page.dimension.width
                    height = page.dimension.height
                    if page_ref.bounding_poly.normalized_vertices:
                        for v in page_ref.bounding_poly.normalized_vertices:
                            pixel_x = v.x * width
                            pixel_y = v.y * height
                            all_vertices.append((pixel_x, pixel_y))
                    elif page_ref.bounding_poly.vertices:
                        for v in page_ref.bounding_poly.vertices:
                            all_vertices.append((v.x, v.y))
        
        if not all_vertices:
            log_debug("[DocAI] No bounding box vertices found", service="image_processing")
            return input_path
        
        xs, ys = zip(*all_vertices)
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        
        img = Image.open(input_path)
        box_width = max_x - min_x
        box_height = max_y - min_y
        expand_x = box_width * (percent_expand / 2)
        expand_y = box_height * (percent_expand / 2)
        left = max(int(min_x - expand_x), 0)
        top = max(int(min_y - expand_y), 0)
        right = min(int(max_x + expand_x), img.width)
        bottom = min(int(max_y + expand_y), img.height)
        
        cropped_img = img.crop((left, top, right, bottom))
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cropped_img.save(output_path)
        log_debug(f"[DocAI] Cropped image saved to {output_path}", service="image_processing")
        return output_path

    except Exception as e:
        log_debug(f"[DocAI] Error: {e}", service="image_processing")
        return input_path


def trim_image_with_boundary_detection(input_path: str, output_path: str = None, white_threshold: int = 245, apply_orientation: bool = True) -> str:
    """
    Trim image using card boundary detection
    """
    try:
        working_path = input_path
        if apply_orientation:
            working_path = ensure_proper_orientation(input_path)
        
        if not output_path:
            filename = os.path.basename(input_path)
            name, ext = os.path.splitext(filename)
            output_path = os.path.join(TRIMMED_FOLDER, f"{name}_trimmed{ext}")
        
        boundaries = detect_card_boundaries(working_path, white_threshold=white_threshold, use_color_detection=True)

        if not boundaries:
            log_debug("[CardBoundary] Color detection failed, trying grayscale...", service="image_processing")
            boundaries = detect_card_boundaries(working_path, white_threshold=white_threshold-30, use_color_detection=False)

        if not boundaries:
            log_debug("[CardBoundary] All boundary detection failed", service="image_processing")
            return input_path
        
        img = Image.open(working_path)
        left, top, right, bottom = boundaries
        cropped_img = img.crop((left, top, right, bottom))
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cropped_img.save(output_path, format='JPEG', quality=100, optimize=True)

        log_debug(f"[CardBoundary] Cropped image saved to {output_path}", service="image_processing")
        return output_path

    except Exception as e:
        log_debug(f"[CardBoundary] Error: {e}", service="image_processing")
        return input_path


def process_with_photoroom(image_path: str, output_dir: Optional[str] = None) -> Optional[str]:
    """
    Process image with PhotoRoom API for background removal
    Returns path to processed image or None if failed
    """
    if not USE_PHOTOROOM:
        log_debug("[PhotoRoom] Disabled via feature flag", service="image_processing")
        return None

    try:
        log_debug(f"[PhotoRoom] Processing image: {image_path}", service="image_processing")
        photoroom_service = get_photoroom_service()
        
        # Use TRIMMED_FOLDER as output directory if not specified
        if not output_dir:
            output_dir = TRIMMED_FOLDER
        
        os.makedirs(output_dir, exist_ok=True)
        
        result = photoroom_service.remove_background(
            image_path,
            output_dir=output_dir
        )
        
        if result['success']:
            # Return white background version (production default)
            processed_path = result['white_bg_path']
            log_debug(f"[PhotoRoom] Success! Processed image: {processed_path}", service="image_processing")
            return processed_path
        else:
            log_debug(f"[PhotoRoom] Failed: {result.get('message')}", service="image_processing")
            return None

    except Exception as e:
        log_debug(f"[PhotoRoom] Error: {e}", service="image_processing")
        return None


def ensure_trimmed_image(original_image_path: str) -> str:
    """
    Main entry point - maintains backwards compatibility
    Enhanced with PhotoRoom support
    """
    log_debug(f"Processing image: {original_image_path}", service="image_processing")
    
    try:
        # Step 1: Ensure proper orientation (handles HEIC conversion)
        processed_path = ensure_proper_orientation(original_image_path)
        
        # Step 2: Try PhotoRoom first (if enabled)
        if USE_PHOTOROOM:
            log_debug(f"Attempting PhotoRoom background removal...", service="image_processing")
            photoroom_result = process_with_photoroom(processed_path)

            if photoroom_result and os.path.exists(photoroom_result):
                # Validate that PhotoRoom actually changed the image
                log_debug(f"Validating PhotoRoom results...", service="image_processing")

                try:
                    from PIL import Image
                    import numpy as np

                    original_img = Image.open(processed_path)
                    photoroom_img = Image.open(photoroom_result)

                    # Quick validation: check if images are significantly different
                    if original_img.size == photoroom_img.size:
                        # Same size - check pixel differences in background areas
                        orig_array = np.array(original_img.resize((100, 100)))  # Resize for speed
                        photo_array = np.array(photoroom_img.resize((100, 100)))

                        # Calculate average pixel difference
                        pixel_diff = np.mean(np.abs(orig_array.astype(float) - photo_array.astype(float)))

                        log_debug(f"PhotoRoom pixel difference: {pixel_diff:.2f}", service="image_processing")

                        if pixel_diff < 5.0:  # Very similar images
                            log_debug(f"PhotoRoom didn't significantly change the image (diff: {pixel_diff:.2f}), falling back to boundary detection", service="image_processing")
                        else:
                            log_debug(f"PhotoRoom processing successful (diff: {pixel_diff:.2f})", service="image_processing")
                            return photoroom_result
                    else:
                        # Different sizes - PhotoRoom likely worked
                        log_debug(f"PhotoRoom changed dimensions from {original_img.size} to {photoroom_img.size}", service="image_processing")
                        return photoroom_result

                except Exception as validation_error:
                    log_debug(f"PhotoRoom validation failed: {validation_error}, falling back to boundary detection", service="image_processing")
            else:
                log_debug(f"PhotoRoom failed or unavailable, falling back to boundary detection", service="image_processing")
        
        # Step 3: Fall back to boundary detection
        log_debug(f"Attempting card boundary detection...", service="image_processing")
        trimmed_path = trim_image_with_boundary_detection(processed_path, white_threshold=250)
        
        if trimmed_path == processed_path:
            log_debug(f"Initial boundary detection failed, trying conservative threshold...", service="image_processing")
            trimmed_path = trim_image_with_boundary_detection(processed_path, white_threshold=252)

            if trimmed_path == processed_path:
                log_debug(f"Boundary detection failed, falling back to DocAI...", service="image_processing")
                trimmed_path = trim_image_with_docai(processed_path, percent_expand=0.80)

                if trimmed_path == processed_path:
                    log_debug(f"All trimming methods failed, returning processed image", service="image_processing")
                    return processed_path
        
        # Verify the trimmed file exists
        if not os.path.exists(trimmed_path):
            log_debug(f"Trimmed image not found at: {trimmed_path}", service="image_processing")
            return processed_path
        
        # Ensure high quality output
        output_img = Image.open(trimmed_path)
        if output_img.mode != 'RGB':
            output_img = output_img.convert('RGB')
        
        jpeg_path = os.path.splitext(trimmed_path)[0] + '.jpg'
        output_img.save(jpeg_path, format='JPEG', quality=100, optimize=True)
        log_debug(f"Image processed and saved at: {jpeg_path}", service="image_processing")
        return jpeg_path

    except Exception as e:
        log_debug(f"Error processing image: {e}", service="image_processing")
        import traceback
        traceback.print_exc()
        return original_image_path


# Alias for compatibility with v2
ensure_trimmed_image_v2 = ensure_trimmed_image