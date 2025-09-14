#!/usr/bin/env python3
"""
Convert HEIC files to JPEG format for DocAI processor training
"""

import os
import sys
from pathlib import Path
from PIL import Image, ImageOps
import pillow_heif

# Register HEIF opener
pillow_heif.register_heif_opener()

def convert_heic_to_jpeg(input_dir: str, quality: int = 95):
    """
    Convert all HEIC files in the input directory to JPEG format

    Args:
        input_dir: Directory containing HEIC files
        quality: JPEG quality (1-100, default 95 for high quality)
    """
    input_path = Path(input_dir)

    if not input_path.exists():
        print(f"Error: Directory {input_dir} does not exist")
        return

    # Find all HEIC files
    heic_files = list(input_path.glob("*.HEIC")) + list(input_path.glob("*.heic")) + \
                 list(input_path.glob("*.HEIF")) + list(input_path.glob("*.heif"))

    if not heic_files:
        print(f"No HEIC files found in {input_dir}")
        return

    print(f"Found {len(heic_files)} HEIC files to convert")

    converted_count = 0

    for heic_file in heic_files:
        try:
            print(f"Converting: {heic_file.name}")

            # Open the HEIC file
            with Image.open(heic_file) as img:
                # Apply EXIF orientation correction
                img = ImageOps.exif_transpose(img)

                # Convert to RGB if needed
                if img.mode != 'RGB':
                    img = img.convert('RGB')

                # Create output filename (replace .HEIC/.heic with .jpg)
                output_file = heic_file.with_suffix('.jpg')

                # Save as JPEG with high quality
                img.save(output_file, 'JPEG', quality=quality, optimize=True)

                print(f"  ✅ Saved: {output_file.name}")
                converted_count += 1

        except Exception as e:
            print(f"  ❌ Error converting {heic_file.name}: {e}")

    print(f"\n🎉 Conversion complete!")
    print(f"Successfully converted {converted_count} out of {len(heic_files)} files")

if __name__ == "__main__":
    # Default directory
    merrimack_dir = "/Users/kregboyd/Applications/card-capture-api/Merrimack"

    # Allow command line override
    if len(sys.argv) > 1:
        merrimack_dir = sys.argv[1]

    print(f"Converting HEIC files in: {merrimack_dir}")
    convert_heic_to_jpeg(merrimack_dir)