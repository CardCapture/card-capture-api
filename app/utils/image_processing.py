import os
import numpy as np
from PIL import Image, ExifTags, ImageOps
from google.cloud import documentai_v1 as documentai
from app.config import PROJECT_ID, DOCAI_LOCATION, DOCAI_PROCESSOR_ID, TRIMMED_FOLDER

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

def detect_card_boundaries(image_path: str, padding: int = 20) -> tuple:
    """
    Detect the actual card boundaries by finding non-white content areas.
    This works universally for any card format as it detects content vs background.
    
    Args:
        image_path: Path to the image file
        padding: Additional padding to add around detected content (default: 20 pixels)
        
    Returns:
        Tuple of (left, top, right, bottom) coordinates or None if detection fails
    """
    try:
        # Convert image to grayscale for content detection
        img = Image.open(image_path).convert('L')
        img_array = np.array(img)
        
        # Find non-white areas (content areas vs background)
        # Use threshold to identify areas that aren't pure white/near-white
        non_white = img_array < 240  # Adjust threshold as needed
        
        # Find the bounding box of all non-white content
        rows = np.any(non_white, axis=1)
        cols = np.any(non_white, axis=0)
        
        if not np.any(rows) or not np.any(cols):
            print("[CardBoundary] No content detected - image might be blank or all white")
            return None
            
        # Get the first and last rows/columns with content
        top, bottom = np.where(rows)[0][[0, -1]]
        left, right = np.where(cols)[0][[0, -1]]
        
        # Add padding to ensure we don't clip content at edges
        left = max(0, left - padding)
        top = max(0, top - padding)
        right = min(img.width, right + padding)
        bottom = min(img.height, bottom + padding)
        
        print(f"[CardBoundary] Detected card boundaries: ({left}, {top}) to ({right}, {bottom})")
        print(f"[CardBoundary] Card size: {right - left} x {bottom - top}")
        
        return (left, top, right, bottom)
        
    except Exception as e:
        print(f"[CardBoundary] Error in boundary detection: {e}")
        return None

def trim_image_with_boundary_detection(input_path: str, output_path: str = None) -> str:
    """
    Trim image using card boundary detection - finds actual content boundaries.
    This is more accurate than field-based detection as it captures the entire card.
    
    Args:
        input_path: Path to input image
        output_path: Path for output image (auto-generated if None)
        
    Returns:
        Path to trimmed image, or input_path if trimming fails
    """
    try:
        # Set up output path
        if not output_path:
            filename = os.path.basename(input_path)
            name, ext = os.path.splitext(filename)
            output_path = os.path.join(TRIMMED_FOLDER, f"{name}_trimmed{ext}")
        
        # Detect card boundaries
        boundaries = detect_card_boundaries(input_path)
        if not boundaries:
            print("[CardBoundary] Boundary detection failed - returning original image")
            return input_path
        
        # Crop image to detected boundaries
        img = Image.open(input_path)
        left, top, right, bottom = boundaries
        cropped_img = img.crop((left, top, right, bottom))
        
        # Ensure output directory exists and save
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cropped_img.save(output_path)
        
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
        print(f"🎯 Attempting card boundary detection...")
        trimmed_path = trim_image_with_boundary_detection(processed_path)
        
        # If boundary detection returns the original path, it failed - try DocAI fallback
        if trimmed_path == processed_path:
            print(f"⚠️ Card boundary detection failed, falling back to DocAI field detection...")
            trimmed_path = trim_image_with_docai(processed_path, percent_expand=0.80)  # Higher expansion for better coverage
            
            # If DocAI also fails, return original
            if trimmed_path == processed_path:
                print(f"⚠️ Both trimming methods failed, returning original image")
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