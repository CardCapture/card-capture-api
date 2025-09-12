#!/usr/bin/env python3

import os
import cv2
import numpy as np
from PIL import Image

def inspect_image_thoroughly(image_path: str, output_dir: str):
    """
    Thoroughly inspect an image to understand what's going on.
    """
    print(f"\n🔍 INSPECTING: {os.path.basename(image_path)}")
    print("-" * 50)
    
    # Load with both OpenCV and PIL to check for issues
    try:
        cv_img = cv2.imread(image_path)
        pil_img = Image.open(image_path)
        
        if cv_img is None:
            print("❌ OpenCV failed to load image")
            return
            
        print(f"📐 PIL dimensions: {pil_img.width} x {pil_img.height}")
        print(f"📐 OpenCV dimensions: {cv_img.shape[1]} x {cv_img.shape[0]}")
        print(f"🎨 PIL mode: {pil_img.mode}")
        print(f"🎨 OpenCV channels: {cv_img.shape[2] if len(cv_img.shape) > 2 else 1}")
        
        # Convert to RGB for consistent processing
        if len(cv_img.shape) == 3:
            rgb_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
        else:
            rgb_img = cv_img
            
        h, w = rgb_img.shape[:2]
        
        # Sample different areas of the image
        sample_size = 50
        areas = {
            'top_left': rgb_img[0:sample_size, 0:sample_size],
            'top_right': rgb_img[0:sample_size, -sample_size:],
            'bottom_left': rgb_img[-sample_size:, 0:sample_size],
            'bottom_right': rgb_img[-sample_size:, -sample_size:],
            'center': rgb_img[h//2-sample_size//2:h//2+sample_size//2, 
                             w//2-sample_size//2:w//2+sample_size//2]
        }
        
        print(f"\n📊 Color analysis (50x50 samples):")
        for area_name, area in areas.items():
            if area.size > 0:
                if len(area.shape) == 3:
                    mean_color = np.mean(area, axis=(0,1))
                    print(f"  {area_name:12}: RGB({mean_color[0]:.1f}, {mean_color[1]:.1f}, {mean_color[2]:.1f})")
                else:
                    mean_color = np.mean(area)
                    print(f"  {area_name:12}: Gray({mean_color:.1f})")
        
        # Create a simple visualization of the image structure
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY) if len(cv_img.shape) == 3 else cv_img
        
        # Resize for easier viewing
        display_width = 800
        display_height = int(h * display_width / w)
        resized = cv2.resize(cv_img, (display_width, display_height))
        resized_gray = cv2.resize(gray, (display_width, display_height))
        
        # Save the resized version for inspection
        name = os.path.splitext(os.path.basename(image_path))[0]
        cv2.imwrite(os.path.join(output_dir, f"{name}_inspect_color.jpg"), resized)
        cv2.imwrite(os.path.join(output_dir, f"{name}_inspect_gray.jpg"), resized_gray)
        
        # Try some basic thresholding to see what happens
        _, thresh1 = cv2.threshold(resized_gray, 127, 255, cv2.THRESH_BINARY)
        _, thresh2 = cv2.threshold(resized_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        cv2.imwrite(os.path.join(output_dir, f"{name}_thresh_127.jpg"), thresh1)
        cv2.imwrite(os.path.join(output_dir, f"{name}_thresh_otsu.jpg"), thresh2)
        
        # Show histogram info
        hist = cv2.calcHist([resized_gray], [0], None, [256], [0, 256])
        peak_value = np.argmax(hist)
        print(f"📈 Brightness: Peak at {peak_value}, Range: {resized_gray.min()}-{resized_gray.max()}")
        
        print(f"💾 Inspection files saved with prefix: {name}_inspect_")
        
    except Exception as e:
        print(f"❌ Error inspecting image: {e}")

def try_manual_crop_suggestions(image_path: str, output_dir: str):
    """
    Create several manual crop suggestions based on common card positions.
    """
    print(f"\n✂️  MANUAL CROP SUGGESTIONS for {os.path.basename(image_path)}")
    print("-" * 50)
    
    try:
        img = Image.open(image_path)
        w, h = img.width, img.height
        
        # Common crop suggestions for cards photographed on tables
        crop_suggestions = [
            ("center_60", (int(w*0.2), int(h*0.2), int(w*0.8), int(h*0.8))),
            ("center_40", (int(w*0.3), int(h*0.3), int(w*0.7), int(h*0.7))),
            ("upper_half", (int(w*0.1), 0, int(w*0.9), int(h*0.6))),
            ("lower_half", (int(w*0.1), int(h*0.4), int(w*0.9), h)),
            ("left_side", (0, int(h*0.1), int(w*0.6), int(h*0.9))),
            ("right_side", (int(w*0.4), int(h*0.1), w, int(h*0.9))),
        ]
        
        name = os.path.splitext(os.path.basename(image_path))[0]
        
        for crop_name, (left, top, right, bottom) in crop_suggestions:
            try:
                cropped = img.crop((left, top, right, bottom))
                output_path = os.path.join(output_dir, f"{name}_manual_{crop_name}.jpg")
                cropped.save(output_path, format='JPEG', quality=95)
                
                crop_w = right - left
                crop_h = bottom - top
                aspect_ratio = crop_w / crop_h
                
                print(f"  📄 {crop_name:12}: {crop_w}x{crop_h} (aspect: {aspect_ratio:.2f}) -> {os.path.basename(output_path)}")
                
            except Exception as e:
                print(f"  ❌ {crop_name}: {e}")
                
    except Exception as e:
        print(f"❌ Error creating manual crops: {e}")

def debug_mc_images():
    """Debug the McMurry card images to understand what's wrong."""
    
    mc_dir = "/Users/kregboyd/Applications/card-capture-api/MC"
    output_dir = "/Users/kregboyd/Applications/card-capture-api/trim_image_test"
    
    os.makedirs(output_dir, exist_ok=True)
    
    print("🔧 McMURRY CARD DEBUG SESSION")
    print("="*60)
    print("Let's figure out what's actually in these images...")
    
    if not os.path.exists(mc_dir):
        print(f"❌ MC directory not found: {mc_dir}")
        return
        
    # Get first few images
    images = [f for f in os.listdir(mc_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png')) and not 'processed' in f.lower()]
    images.sort()
    
    for img_file in images[:3]:  # Debug first 3 images
        img_path = os.path.join(mc_dir, img_file)
        
        print(f"\n{'='*60}")
        inspect_image_thoroughly(img_path, output_dir)
        try_manual_crop_suggestions(img_path, output_dir)
    
    print(f"\n{'='*60}")
    print(f"🔍 DEBUG COMPLETE")
    print(f"{'='*60}")
    print(f"📁 Check all debug files in: {output_dir}")
    print(f"💡 Look for files ending with:")
    print(f"   - *_inspect_color.jpg (resized color image)")
    print(f"   - *_inspect_gray.jpg (grayscale version)")
    print(f"   - *_manual_*.jpg (manual crop suggestions)")
    print(f"   - *_thresh_*.jpg (threshold experiments)")
    print(f"\n🎯 Find which manual crop looks best, then we can automate that approach!")

if __name__ == "__main__":
    debug_mc_images()