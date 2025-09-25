import os
import json
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional
from google.cloud import documentai_v1 as documentai
from PIL import Image
import tempfile
import io
from app.config import PROJECT_ID, DOCAI_LOCATION, TRIMMED_FOLDER, GOOGLE_OCR_PROCESSOR
from app.utils.retry_utils import retry_with_exponential_backoff, log_debug
from app.core.clients import get_supabase_client

def process_image_with_docai(image_path: str, processor_id: str, original_storage_path: str = None) -> Tuple[Dict[str, Any], str]:
    """
    Two-step DocAI processing with rotation correction:
    1. Enterprise OCR for rotation correction (if GOOGLE_OCR_PROCESSOR is set)
    2. Custom processor for field extraction
    3. Save corrected image to Supabase (if original_storage_path provided)
    4. Crop image and return extracted fields

    Args:
        image_path: Path to the input image
        processor_id: Custom processor ID for field extraction
        original_storage_path: Supabase storage path for saving corrected image

    Returns:
        Tuple of (field_data_dict, cropped_image_path)
    """
    try:
        # Log processing start
        log_debug(f"Starting processing: {image_path}", service="docai")
        log_debug(f"Image exists: {os.path.exists(image_path)}", service="docai")
        log_debug(f"Image size: {os.path.getsize(image_path)} bytes", service="docai")

        # Check if we have Enterprise OCR processor for rotation correction
        use_rotation_correction = GOOGLE_OCR_PROCESSOR and original_storage_path
        if use_rotation_correction:
            log_debug(f"Using two-step processing with Enterprise OCR: {GOOGLE_OCR_PROCESSOR}", service="docai")
        else:
            log_debug("Using single-step processing (no rotation correction)", service="docai")

        # Initialize DocAI client
        client = documentai.DocumentProcessorServiceClient()

        # Read the file into memory
        with open(image_path, "rb") as image:
            original_content = image.read()
            log_debug(f"Read {len(original_content)} bytes from image", service="docai")

        # Determine MIME type based on file extension
        file_extension = os.path.splitext(image_path)[1].lower()
        mime_type = {
            '.pdf': 'application/pdf',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.tiff': 'image/tiff',
            '.tif': 'image/tiff',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp'
        }.get(file_extension, 'image/png')

        log_debug(f"Detected MIME type: {mime_type}", service="docai")

        # Content that will be used for custom processor (may be corrected by OCR)
        processing_content = original_content

        # =====================================
        # STEP 1: ENTERPRISE OCR (ROTATION FIX)
        # Only if we have OCR processor and storage path
        # =====================================

        if use_rotation_correction:
            ocr_processor_name = f"projects/{PROJECT_ID}/locations/{DOCAI_LOCATION}/processors/{GOOGLE_OCR_PROCESSOR}"

            ocr_request = documentai.ProcessRequest(
                name=ocr_processor_name,
                raw_document=documentai.RawDocument(
                    content=original_content,
                    mime_type=mime_type
                ),
                process_options=documentai.ProcessOptions(
                    ocr_config=documentai.OcrConfig(
                        enable_image_quality_scores=True,
                        enable_symbol=True
                    )
                )
            )

            log_debug("Step 1: Calling Enterprise OCR for rotation correction...", service="docai")

            try:
                ocr_result = retry_with_exponential_backoff(
                    func=lambda: client.process_document(request=ocr_request),
                    max_retries=3,
                    operation_name="Enterprise OCR rotation correction",
                    service="docai"
                )
                log_debug("✅ Enterprise OCR processing successful", service="docai")

                # Extract the rotation-corrected image
                if ocr_result.document.pages and len(ocr_result.document.pages) > 0:
                    page = ocr_result.document.pages[0]
                    if hasattr(page, 'image') and page.image and page.image.content:
                        processing_content = page.image.content
                        log_debug("✅ Retrieved rotation-corrected image from Enterprise OCR", service="docai")

                        # Log if rotation actually occurred
                        original_img = Image.open(io.BytesIO(original_content))
                        corrected_img = Image.open(io.BytesIO(processing_content))
                        if original_img.size != corrected_img.size:
                            log_debug(f"🔄 Image was rotated: {original_img.size} → {corrected_img.size}", service="docai")
                        else:
                            log_debug(f"📏 Image dimensions unchanged: {original_img.size}", service="docai")
                    else:
                        log_debug("⚠️ No corrected image in OCR response, using original", service="docai")

            except Exception as e:
                log_debug(f"⚠️ Enterprise OCR error: {str(e)}, continuing with original image", service="docai")
                # Continue with original image if OCR fails

            # =====================================
            # SAVE CORRECTED IMAGE TO SUPABASE
            # =====================================

            if processing_content != original_content:
                log_debug(f"Saving corrected image to Supabase: {original_storage_path}", service="docai")

                # Clean the storage path
                if original_storage_path.startswith('cards-uploads/'):
                    clean_path = original_storage_path.replace('cards-uploads/', '')
                else:
                    clean_path = original_storage_path

                try:
                    supabase = get_supabase_client()
                    if not supabase:
                        raise Exception("Could not get Supabase client")

                    # Remove old file (ignore errors)
                    try:
                        supabase.storage.from_('cards-uploads').remove([clean_path])
                    except:
                        pass

                    # Compress corrected image before upload (Enterprise OCR returns PNG)
                    corrected_img = Image.open(io.BytesIO(processing_content))

                    # Compress to JPEG with high quality
                    compressed_buffer = io.BytesIO()
                    corrected_img.save(compressed_buffer, format='JPEG', quality=90, optimize=True)
                    compressed_content = compressed_buffer.getvalue()

                    log_debug(f"Compressed image: {len(processing_content):,} → {len(compressed_content):,} bytes", service="docai")

                    # Upload compressed image
                    upload_response = supabase.storage.from_('cards-uploads').upload(
                        path=clean_path,
                        file=compressed_content,
                        file_options={"content-type": "image/jpeg"}
                    )

                    if hasattr(upload_response, 'error') and upload_response.error:
                        raise Exception(f"Supabase upload error: {upload_response.error}")

                    log_debug("✅ Corrected image saved to Supabase", service="docai")

                except Exception as e:
                    log_debug(f"⚠️ Failed to save corrected image to Supabase: {str(e)}", service="docai")
                    # Continue processing even if Supabase save fails

        # =====================================
        # STEP 2: CUSTOM PROCESSOR (FIELD EXTRACTION)
        # =====================================

        custom_processor_name = f"projects/{PROJECT_ID}/locations/{DOCAI_LOCATION}/processors/{processor_id}"

        custom_request = documentai.ProcessRequest(
            name=custom_processor_name,
            raw_document=documentai.RawDocument(
                content=processing_content,  # Use the rotation-corrected image if available
                mime_type=mime_type
            )
        )

        step_name = "Step 2: Calling custom processor" if use_rotation_correction else "Calling custom processor"
        log_debug(f"{step_name} for field extraction...", service="docai")

        try:
            custom_result = retry_with_exponential_backoff(
                func=lambda: client.process_document(request=custom_request),
                max_retries=3,
                operation_name="Custom processor field extraction",
                service="docai"
            )
            log_debug("✅ Custom processor extraction successful", service="docai")
        except Exception as e:
            log_debug(f"❌ Custom processor error: {str(e)}", service="docai")
            raise Exception(f"Custom processor failed: {str(e)}")

        document = custom_result.document

        log_debug("Custom processor response received", {
            "text_length": len(document.text),
            "num_pages": len(document.pages),
            "num_entities": len(document.entities)
        }, service="docai")

        # =====================================
        # EXTRACT FIELD DATA (SAME AS BEFORE)
        # =====================================

        field_data = {}
        all_vertices = []

        log_debug("=== EXTRACTING ENTITIES ===", service="docai")
        for entity in document.entities:
            field_name = entity.type_.lower().replace(" ", "_")
            field_value = entity.mention_text.strip() if entity.mention_text else ""
            confidence = float(entity.confidence) if entity.confidence else 0.0

            log_debug(f"Entity: {field_name}", {
                "value": field_value,
                "confidence": confidence
            }, service="docai")

            # Extract bounding box coordinates (same as before)
            bounding_box = []
            if entity.page_anchor and entity.page_anchor.page_refs:
                for page_ref in entity.page_anchor.page_refs:
                    page_index = page_ref.page
                    if page_index < len(document.pages):
                        page = document.pages[page_index]
                        width = page.dimension.width
                        height = page.dimension.height

                        if page_ref.bounding_poly.normalized_vertices:
                            for vertex in page_ref.bounding_poly.normalized_vertices:
                                pixel_x = vertex.x * width
                                pixel_y = vertex.y * height
                                bounding_box.append([pixel_x, pixel_y])
                                all_vertices.append((pixel_x, pixel_y))
                        elif page_ref.bounding_poly.vertices:
                            for vertex in page_ref.bounding_poly.vertices:
                                bounding_box.append([vertex.x, vertex.y])
                                all_vertices.append((vertex.x, vertex.y))

            # Create field data structure
            field_data[field_name] = {
                "value": field_value,
                "confidence": confidence,
                "bounding_box": bounding_box,
                "source": "docai",
                "enabled": True,
                "required": False,
                "requires_human_review": confidence < 0.8,
                "review_notes": "",
                "review_confidence": 0.0
            }

        log_debug("Extracted fields", list(field_data.keys()), service="docai")

        # =====================================
        # CROP IMAGE (USING CORRECTED IMAGE IF AVAILABLE)
        # =====================================

        # If we have corrected content, save it to temp file for cropping
        if processing_content != original_content:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
                tmp.write(processing_content)
                temp_corrected_path = tmp.name

            # Crop the corrected image
            cropped_image_path = _crop_image_from_entities(temp_corrected_path, all_vertices)

            # Clean up temp file
            os.unlink(temp_corrected_path)
        else:
            # Use original image for cropping
            cropped_image_path = _crop_image_from_entities(image_path, all_vertices)

        completion_msg = "TWO-STEP PROCESSING COMPLETE" if use_rotation_correction else "DOCAI PROCESSING COMPLETE"
        log_debug(f"=== {completion_msg} ===", service="docai")
        log_debug(f"Cropped image saved to: {cropped_image_path}", service="docai")

        return field_data, cropped_image_path

    except Exception as e:
        log_debug(f"ERROR in DocAI processing: {str(e)}", service="docai")
        raise Exception(f"DocAI processing failed: {str(e)}")

def _crop_image_from_entities(input_path: str, all_vertices: list, percent_expand: float = 0.5) -> str:
    """
    Crop image based on bounding box vertices from detected entities
    
    Args:
        input_path: Path to input image
        all_vertices: List of (x, y) coordinates from all entities
        percent_expand: Percentage to expand the bounding box
        
    Returns:
        Path to cropped image
    """
    try:
        if not all_vertices:
            log_debug("No vertices found, returning original image", service="docai")
            return input_path
        
        # Calculate bounding box
        xs, ys = zip(*all_vertices)
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        
        log_debug("Bounding box coordinates", {
            "min_x": min_x, "max_x": max_x,
            "min_y": min_y, "max_y": max_y
        }, service="docai")
        
        # Open image and calculate crop area with expansion
        img = Image.open(input_path)
        box_width = max_x - min_x
        box_height = max_y - min_y
        expand_x = box_width * (percent_expand / 2)
        expand_y = box_height * (percent_expand / 2)
        
        left = max(int(min_x - expand_x), 0)
        top = max(int(min_y - expand_y), 0)
        right = min(int(max_x + expand_x), img.width)
        bottom = min(int(max_y + expand_y), img.height)
        
        log_debug("Crop coordinates", {
            "left": left, "top": top, "right": right, "bottom": bottom
        }, service="docai")
        
        # Crop and save image
        cropped_img = img.crop((left, top, right, bottom))
        filename = os.path.basename(input_path)
        name, ext = os.path.splitext(filename)
        output_path = os.path.join(TRIMMED_FOLDER, f"{name}_trimmed{ext}")
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cropped_img.save(output_path)
        
        log_debug(f"Image cropped and saved to: {output_path}", service="docai")
        return output_path
        
    except Exception as e:
        log_debug(f"ERROR in image cropping: {str(e)}", service="docai")
        return input_path  # Return original if cropping fails 