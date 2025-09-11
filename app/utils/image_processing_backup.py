import os
import numpy as np
from PIL import Image, ExifTags, ImageOps
from google.cloud import documentai_v1 as documentai
from app.config import PROJECT_ID, DOCAI_LOCATION, DOCAI_PROCESSOR_ID, TRIMMED_FOLDER
from scipy import ndimage

def trim_image_with_docai(input_path: str, output_path: str = None, percent_expand: float = 0.5) -> str:
    """
    Uses Google Document AI to find the bounding box of form fields, crops the image with a percentage expansion,
    and saves it to output_path. Returns the output path, or input_path if anything fails.
    """
    try:
        # Set up output path
        if not output_path:
            filename = os.path.basename(input_path)
            name, ext = os.path.splitext(filename)
            output_path = os.path.join(TRIMMED_FOLDER, f"{name}_trimmed{ext}")
        # Set up Document AI client
        client = documentai.DocumentProcessorServiceClient()
        name = f"projects/{PROJECT_ID}/locations/{DOCAI_LOCATION}/processors/{DOCAI_PROCESSOR_ID}"
        with open(input_path, "rb") as image_file:
            image_content = image_file.read()
        raw_document = documentai.RawDocument(content=image_content, mime_type="image/jpeg")
        request = documentai.ProcessRequest(name=name, raw_document=raw_document)
        result = client.process_document(request=request)
        document = result.document
        # Gather all bounding box vertices from entities
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
            print("No bounding box vertices found for any entity. Returning original image.")
            return input_path
        xs, ys = zip(*all_vertices)
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        # Crop with percent expansion
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
        print(f"[DocAI] Cropped image saved to {output_path}")
        return output_path
    except Exception as e:
        print(f"[DocAI] Error in trim_image_with_docai: {e}")
        return input_path

def detect_card_boundaries(image_path: str, padding: int = 20, white_threshold: int = 245, use_color_detection: bool = True) -> tuple:
    """
    Detect the actual card boundaries by finding the card vs background.
    Enhanced algorithm that can distinguish white cards from light backgrounds.
    
    Args:
        image_path: Path to the image file
        padding: Additional padding to add around detected content (default: 20 pixels)
        white_threshold: Threshold for white detection (0-255, default: 245)
                        Lower values = more aggressive white detection
                        Higher values = more conservative (better for white-on-white cards)
        use_color_detection: Use color-based detection for better card vs background distinction
        
    Returns:
        Tuple of (left, top, right, bottom) coordinates or None if detection fails
    """
    try:
        # Open image and apply EXIF orientation first
        img = Image.open(image_path)
        img = ImageOps.exif_transpose(img)
        
        if use_color_detection:
            # Use color information to better distinguish card from background
            img_array = np.array(img)
            
            # Calculate variance in each color channel to find uniform areas (likely card)
            if len(img_array.shape) == 3:  # Color image
                # Calculate standard deviation across color channels for each pixel
                color_std = np.std(img_array, axis=2)
                
                # Also check for very bright areas (potential card areas)
                brightness = np.mean(img_array, axis=2)
                
                # Simple approach: look for areas that are NOT background
                # Background is typically much darker than card areas
                
                # Card areas are generally brighter than background
                not_background = brightness > (white_threshold - 40)
                
                # Allow significant color variation for printed cards
                allow_variation = color_std < 50
                
                # Combine: bright enough to be card content
                potential_card = not_background | (brightness > 240)  # Very bright areas are definitely card
                
                # Simple cleanup - just remove very small isolated pixels
                structure = np.ones((3, 3))
                potential_card = ndimage.binary_opening(potential_card, structure=structure)
                
                # Find the largest connected component (likely the main card)
                labeled_array, num_features = ndimage.label(potential_card)
                
                if num_features > 0:
                    # Find components and their sizes
                    component_sizes = [(labeled_array == i).sum() for i in range(1, num_features + 1)]
                    
                    # Filter out very small components (likely noise)
                    min_card_size = img.width * img.height * 0.1  # At least 10% of image
                    valid_components = []
                    
                    for i, size in enumerate(component_sizes):
                        if size > min_card_size:
                            valid_components.append((i + 1, size))
                    
                    if valid_components:
                        # Use the largest valid component
                        largest_component = max(valid_components, key=lambda x: x[1])[0]
                        card_mask = labeled_array == largest_component
                    else:
                        # No valid large components found, fall back to original method
                        print("[CardBoundary] No large enough components found, using fallback")
                        card_mask = potential_card
                else:
                    card_mask = potential_card
            else:
                # Fallback to grayscale method
                img_array = np.array(img.convert('L'))
                card_mask = img_array > white_threshold
        else:
            # Original grayscale method
            img_array = np.array(img.convert('L'))
            card_mask = img_array < white_threshold
        
        print(f"[CardBoundary] Using white threshold: {white_threshold}, color detection: {use_color_detection}")
        
        # Find the bounding box of the card
        rows = np.any(card_mask, axis=1)
        cols = np.any(card_mask, axis=0)
        
        if not np.any(rows) or not np.any(cols):
            print("[CardBoundary] No card detected - trying fallback method")
            # Fallback to original method with lower threshold
            img_gray = np.array(img.convert('L'))
            non_white = img_gray < (white_threshold - 50)  # More aggressive
            rows = np.any(non_white, axis=1)
            cols = np.any(non_white, axis=0)
            
            if not np.any(rows) or not np.any(cols):
                print("[CardBoundary] Fallback also failed - no content detected")
                return None
            
        # Get the first and last rows/columns with content
        top, bottom = np.where(rows)[0][[0, -1]]
        left, right = np.where(cols)[0][[0, -1]]
        
        # Add conservative padding to ensure we don't clip any content
        # Use larger padding values for safety
        safe_padding = max(padding, 40)  # At least 40 pixels padding
        
        left = max(0, left - safe_padding)
        top = max(0, top - safe_padding)
        right = min(img.width, right + safe_padding)
        bottom = min(img.height, bottom + safe_padding)
        
        print(f"[CardBoundary] Detected card boundaries: ({left}, {top}) to ({right}, {bottom})")
        print(f"[CardBoundary] Card size: {right - left} x {bottom - top}")
        
        return (left, top, right, bottom)
        
    except Exception as e:
        print(f"[CardBoundary] Error in boundary detection: {e}")
        return None

def trim_image_with_boundary_detection(input_path: str, output_path: str = None, white_threshold: int = 245, apply_orientation: bool = True) -> str:
    """
    Trim image using card boundary detection - finds actual content boundaries.
    Now includes proper orientation handling and enhanced detection.
    
    Args:
        input_path: Path to input image
        output_path: Path for output image (auto-generated if None)
        white_threshold: Threshold for white detection (245 = conservative for white cards)
        apply_orientation: Whether to apply EXIF orientation correction first
        
    Returns:
        Path to trimmed image, or input_path if trimming fails
    """
    try:
        # Apply orientation correction first if requested
        working_path = input_path
        if apply_orientation:
            working_path = ensure_proper_orientation(input_path)
        
        # Set up output path
        if not output_path:
            filename = os.path.basename(input_path)
            name, ext = os.path.splitext(filename)
            output_path = os.path.join(TRIMMED_FOLDER, f"{name}_trimmed{ext}")
        
        # Try enhanced color-based detection first
        boundaries = detect_card_boundaries(working_path, white_threshold=white_threshold, use_color_detection=True)
        
        # If that fails, try traditional grayscale method with more aggressive threshold
        if not boundaries:
            print("[CardBoundary] Color detection failed, trying grayscale method...")
            boundaries = detect_card_boundaries(working_path, white_threshold=white_threshold-30, use_color_detection=False)
        
        if not boundaries:
            print("[CardBoundary] All boundary detection methods failed - returning original image")
            return input_path
        
        # Crop image to detected boundaries
        img = Image.open(working_path)
        left, top, right, bottom = boundaries
        cropped_img = img.crop((left, top, right, bottom))
        
        # Ensure output directory exists and save
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cropped_img.save(output_path, format='JPEG', quality=100, optimize=True)
        
        print(f"[CardBoundary] Cropped image saved to {output_path}")
        return output_path
        
    except Exception as e:
        print(f"[CardBoundary] Error in trim_image_with_boundary_detection: {e}")
        return input_path

def ensure_proper_orientation(image_path: str) -> str:
    """
    Properly handle EXIF orientation and prepare image for processing.
    No longer forces vertical orientation - respects the card's natural layout.
    """
    img = Image.open(image_path)
    
    # This handles EXIF orientation automatically and strips EXIF data
    img = ImageOps.exif_transpose(img)
    print(f"✅ EXIF orientation applied successfully")
    
    # Check if this appears to be a horizontal card format
    aspect_ratio = img.width / img.height
    if aspect_ratio > 1.5:  # Clearly horizontal card
        print(f"📐 Detected horizontal card format (aspect ratio: {aspect_ratio:.2f}) - preserving orientation")
    elif aspect_ratio < 0.7:  # Clearly vertical card
        print(f"📐 Detected vertical card format (aspect ratio: {aspect_ratio:.2f}) - preserving orientation")
    else:
        print(f"📐 Square/ambiguous format (aspect ratio: {aspect_ratio:.2f}) - preserving original orientation")
    
    # Convert to RGB if needed
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGB')
        
    # Save processed image with corrected path construction
    base_path, ext = os.path.splitext(image_path)
    processed_path = f"{base_path}_processed{ext}"
    img.save(processed_path, format='JPEG', quality=100, optimize=True)
    print(f"✅ Processed image saved to: {processed_path}")
    
    return processed_path

def ensure_trimmed_image(original_image_path: str) -> str:
    print(f"🔄 Processing image: {original_image_path}")
    try:
        # Ensure proper orientation (EXIF handling, no forced rotation)
        processed_path = ensure_proper_orientation(original_image_path)
        
        # Try card boundary detection first (universal method for all card formats)
        # Use conservative threshold (245) for white-on-white cards
        print(f"🎯 Attempting card boundary detection with conservative white threshold...")
        trimmed_path = trim_image_with_boundary_detection(processed_path, white_threshold=250)
        
        # If boundary detection returns the original path, it failed - try more conservative threshold
        if trimmed_path == processed_path:
            print(f"⚠️ Initial boundary detection failed, trying ultra-conservative threshold...")
            trimmed_path = trim_image_with_boundary_detection(processed_path, white_threshold=252)
            
            # If still failing, fall back to DocAI field detection
            if trimmed_path == processed_path:
                print(f"⚠️ Boundary detection failed, falling back to DocAI field detection...")
                trimmed_path = trim_image_with_docai(processed_path, percent_expand=0.80)  # Higher expansion for better coverage
                
                # If DocAI also fails, return original
                if trimmed_path == processed_path:
                    print(f"⚠️ All trimming methods failed, returning original image")
                    return original_image_path
        
        # Verify the trimmed file exists
        if not os.path.exists(trimmed_path):
            print(f"⚠️ Trimmed image not found at: {trimmed_path}")
            return original_image_path
            
        # Ensure high quality output and always save as JPEG (RGB)
        output_img = Image.open(trimmed_path)
        if output_img.mode != 'RGB':
            output_img = output_img.convert('RGB')
        # Always save as .jpg
        jpeg_path = os.path.splitext(trimmed_path)[0] + '.jpg'
        output_img.save(jpeg_path, format='JPEG', quality=100, optimize=True)
        print(f"✅ Image processed and saved at: {jpeg_path}")
        return jpeg_path
    except Exception as e:
        print(f"❌ Error processing image: {e}")
        return original_image_path 