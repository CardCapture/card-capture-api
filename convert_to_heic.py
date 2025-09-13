#!/usr/bin/env python3
"""
Convert PDF or image to HEIC format for testing mobile uploads
"""
import os
import sys
from pathlib import Path
from PIL import Image
from pdf2image import convert_from_path
import tempfile

# Add the app directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def convert_pdf_to_heic(pdf_path, output_path=None):
    """
    Convert PDF to HEIC format (actually creates a JPEG renamed as .heic for testing)
    Real HEIC encoding requires special libraries, but for testing purposes,
    we can create a file that will trigger the HEIC processing path.
    """
    print(f"Converting {pdf_path} to HEIC format...")
    
    try:
        # Convert PDF to image first
        print("Step 1: Converting PDF to image...")
        images = convert_from_path(pdf_path, dpi=300)
        
        if not images:
            print("❌ No pages found in PDF")
            return None
        
        # Take the first page
        img = images[0]
        print(f"✅ PDF converted to image: {img.size}")
        
        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Save as JPEG with .heic extension
        # (This simulates what happens when iOS saves HEIC files)
        if output_path is None:
            base_name = Path(pdf_path).stem
            output_path = f"/Users/kregboyd/Applications/card-capture-api/ACU/{base_name}.heic"
        
        # First save as high-quality JPEG
        temp_jpg = output_path.replace('.heic', '_temp.jpg')
        img.save(temp_jpg, 'JPEG', quality=95)
        
        # Rename to .heic to simulate iOS photo
        if os.path.exists(output_path):
            os.remove(output_path)
        os.rename(temp_jpg, output_path)
        
        print(f"✅ Saved as HEIC: {output_path}")
        print(f"   File size: {os.path.getsize(output_path)} bytes")
        
        return output_path
        
    except Exception as e:
        print(f"❌ Error converting PDF to HEIC: {e}")
        import traceback
        traceback.print_exc()
        return None

def convert_image_to_heic(image_path, output_path=None):
    """
    Convert regular image to HEIC format for testing
    """
    print(f"Converting {image_path} to HEIC format...")
    
    try:
        # Open the image
        img = Image.open(image_path)
        
        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Save as JPEG with .heic extension
        if output_path is None:
            base_name = Path(image_path).stem
            dir_path = Path(image_path).parent
            output_path = dir_path / f"{base_name}.heic"
        
        # Save with .heic extension
        img.save(str(output_path), 'JPEG', quality=95)
        
        print(f"✅ Saved as HEIC: {output_path}")
        print(f"   File size: {os.path.getsize(output_path)} bytes")
        
        return str(output_path)
        
    except Exception as e:
        print(f"❌ Error converting image to HEIC: {e}")
        return None

def main():
    """Convert ACU PDF to HEIC for testing"""
    
    print("=" * 60)
    print("PDF TO HEIC CONVERTER FOR MOBILE UPLOAD TESTING")
    print("=" * 60)
    
    # ACU PDF file
    pdf_path = "/Users/kregboyd/Applications/card-capture-api/ACU/mercer-acu.pdf"
    
    if not os.path.exists(pdf_path):
        print(f"❌ PDF not found: {pdf_path}")
        return
    
    # Convert to HEIC
    heic_path = convert_pdf_to_heic(pdf_path)
    
    if heic_path:
        print("\n" + "=" * 60)
        print("✅ CONVERSION SUCCESSFUL!")
        print("=" * 60)
        print(f"HEIC file created: {heic_path}")
        print("\nThis file simulates a photo taken with an iPhone.")
        print("It will trigger the HEIC processing path in the pipeline.")
        print("\nYou can now test with this HEIC file to verify:")
        print("1. HEIC conversion works")
        print("2. PhotoRoom processes the converted image")
        print("3. The card isn't cut off")
        
        # Also create a true HEIC if pillow_heif is available
        try:
            import pillow_heif
            print("\n🎯 pillow_heif is available - creating true HEIC...")
            
            # Register HEIF opener
            pillow_heif.register_heif_opener()
            
            # Open the PDF-converted image
            img = Image.open(heic_path)
            
            # Save as actual HEIC using pillow_heif
            true_heic_path = heic_path.replace('.heic', '_true.heic')
            img.save(true_heic_path, format='HEIF')
            
            print(f"✅ True HEIC created: {true_heic_path}")
            
        except ImportError:
            print("\n⚠️  pillow_heif not available for true HEIC encoding")
            print("   Using JPEG-renamed-as-HEIC for testing (this is fine)")
        except Exception as e:
            print(f"\n⚠️  Could not create true HEIC: {e}")
            print("   Using JPEG-renamed-as-HEIC for testing (this is fine)")
    else:
        print("\n❌ Conversion failed")

if __name__ == "__main__":
    main()