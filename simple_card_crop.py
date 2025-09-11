#!/usr/bin/env python3

import os
import sys
import cv2
import numpy as np
from PIL import Image

def simple_card_detection(image_path: str, debug_dir: str = None) -> tuple:
    """
    DEAD SIMPLE approach: Find the card by looking for the biggest rectangle
    that's different from the corners of the image (background).
    """
    try:
        print(f"\n🎯 SIMPLE CARD DETECTION")
        print("-" * 40)
        
        # Read image
        img = cv2.imread(image_path)
        if img is None:
            print("❌ Failed to read image")
            return None
            
        h, w = img.shape[:2]
        print(f"📐 Image size: {w}x{h}")
        
        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Sample the corners to understand the background color
        corner_size = min(50, w//10, h//10)
        corners = [
            gray[0:corner_size, 0:corner_size],  # top-left
            gray[0:corner_size, -corner_size:],  # top-right
            gray[-corner_size:, 0:corner_size],  # bottom-left
            gray[-corner_size:, -corner_size:]   # bottom-right
        ]
        
        # Get average background color from corners
        bg_values = [np.mean(corner) for corner in corners]
        bg_color = np.mean(bg_values)
        bg_std = np.std(bg_values)
        
        print(f"📊 Background color: {bg_color:.1f} ± {bg_std:.1f}")
        
        # Create a mask of areas that are DIFFERENT from background
        # Use a threshold that adapts to background variation
        threshold = max(20, bg_std * 3)  # At least 20, or 3x the background variation
        
        # Areas significantly different from background
        diff_from_bg = np.abs(gray.astype(float) - bg_color)
        card_mask = diff_from_bg > threshold
        
        # Clean up the mask with morphological operations
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        card_mask = cv2.morphologyEx(card_mask.astype(np.uint8) * 255, cv2.MORPH_CLOSE, kernel)
        card_mask = cv2.morphologyEx(card_mask, cv2.MORPH_OPEN, kernel)
        
        # Find the largest connected component (the card)
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(card_mask, 8, cv2.CV_32S)
        
        if num_labels < 2:  # Only background found
            print("❌ No card-like regions found")
            return None
            
        # Find the largest component (excluding background which is label 0)
        largest_label = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
        largest_area = stats[largest_label, cv2.CC_STAT_AREA]
        
        # Get bounding box of largest component
        x = stats[largest_label, cv2.CC_STAT_LEFT]
        y = stats[largest_label, cv2.CC_STAT_TOP]
        w_card = stats[largest_label, cv2.CC_STAT_WIDTH] 
        h_card = stats[largest_label, cv2.CC_STAT_HEIGHT]
        
        area_ratio = largest_area / (w * h)
        aspect_ratio = w_card / h_card if h_card > 0 else 0
        
        print(f"📦 Largest region: {w_card}x{h_card} at ({x},{y})")
        print(f"📊 Area ratio: {area_ratio:.1%}, Aspect: {aspect_ratio:.2f}")
        
        # Sanity check: is this a reasonable card size?
        if area_ratio < 0.05:  # Too small
            print("⚠️ Detected region too small to be a card")
            return None
        if area_ratio > 0.95:  # Too big (probably whole image)
            print("⚠️ Detected region too large (probably whole image)")
            return None
            
        # Add padding
        padding = 20
        left = max(0, x - padding)
        top = max(0, y - padding)
        right = min(w, x + w_card + padding)
        bottom = min(h, y + h_card + padding)
        
        print(f"✅ Final boundaries: ({left},{top}) to ({right},{bottom})")
        
        # Save debug images
        if debug_dir:
            # Show the difference from background
            diff_viz = (diff_from_bg / diff_from_bg.max() * 255).astype(np.uint8)
            cv2.imwrite(os.path.join(debug_dir, "simple_diff_from_bg.jpg"), diff_viz)
            
            # Show the card mask
            cv2.imwrite(os.path.join(debug_dir, "simple_card_mask.jpg"), card_mask)
            
            # Show the detected region
            debug_img = img.copy()
            cv2.rectangle(debug_img, (x, y), (x + w_card, y + h_card), (0, 255, 0), 3)
            cv2.rectangle(debug_img, (left, top), (right, bottom), (255, 0, 0), 2)
            cv2.imwrite(os.path.join(debug_dir, "simple_detection_debug.jpg"), debug_img)
            print(f"💾 Debug images saved to {debug_dir}")
        
        return (left, top, right, bottom)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def manual_adjustment_detection(image_path: str, debug_dir: str = None) -> tuple:
    """
    Even simpler: Look for any rectangular region that's clearly not background.
    Uses statistical analysis to find the most "card-like" region.
    """
    try:
        print(f"\n🔧 MANUAL ADJUSTMENT DETECTION")
        print("-" * 40)
        
        img = cv2.imread(image_path)
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Divide image into a grid and analyze each region
        grid_size = 20  # 20x20 grid
        step_x = w // grid_size
        step_y = h // grid_size
        
        regions = []
        
        for i in range(grid_size - 5):  # Don't go all the way to edges
            for j in range(grid_size - 5):
                x = i * step_x
                y = j * step_y
                
                # Try different region sizes
                for size_mult in [3, 4, 5, 6]:
                    region_w = step_x * size_mult
                    region_h = step_y * size_mult
                    
                    if x + region_w < w and y + region_h < h:
                        # Extract region
                        region = gray[y:y+region_h, x:x+region_w]
                        
                        # Calculate region statistics
                        mean_val = np.mean(region)
                        std_val = np.std(region)
                        
                        # Sample the border of this region to see if it's different from surroundings
                        border_top = gray[max(0, y-10):y, x:x+region_w] if y > 10 else None
                        border_left = gray[y:y+region_h, max(0, x-10):x] if x > 10 else None
                        border_right = gray[y:y+region_h, x+region_w:min(w, x+region_w+10)] if x+region_w < w-10 else None
                        border_bottom = gray[y+region_h:min(h, y+region_h+10), x:x+region_w] if y+region_h < h-10 else None
                        
                        border_values = []
                        for border in [border_top, border_left, border_right, border_bottom]:
                            if border is not None and border.size > 0:
                                border_values.append(np.mean(border))
                        
                        if border_values:
                            border_mean = np.mean(border_values)
                            contrast = abs(mean_val - border_mean)
                            
                            # Score this region
                            aspect_ratio = region_w / region_h
                            area_ratio = (region_w * region_h) / (w * h)
                            
                            # Good cards have:
                            # - Reasonable aspect ratio (0.5 to 2.0)
                            # - Reasonable size (10% to 80% of image)
                            # - Good contrast with surroundings
                            # - Not too much internal variation (not noisy background)
                            
                            score = 0
                            if 0.5 <= aspect_ratio <= 2.0:
                                score += 50
                            if 0.1 <= area_ratio <= 0.8:
                                score += 50
                            if contrast > 20:  # Good contrast with surroundings
                                score += contrast
                            if std_val < 30:  # Not too noisy internally
                                score += 20
                                
                            regions.append({
                                'x': x, 'y': y, 'w': region_w, 'h': region_h,
                                'mean': mean_val, 'std': std_val, 'contrast': contrast,
                                'aspect': aspect_ratio, 'area_ratio': area_ratio,
                                'score': score
                            })
        
        if not regions:
            print("❌ No regions analyzed")
            return None
            
        # Sort by score and get the best
        regions.sort(key=lambda r: r['score'], reverse=True)
        best = regions[0]
        
        print(f"📊 Analyzed {len(regions)} regions")
        print(f"🏆 Best region: {best['w']}x{best['h']} at ({best['x']},{best['y']})")
        print(f"   Score: {best['score']:.1f}, Contrast: {best['contrast']:.1f}")
        print(f"   Aspect: {best['aspect']:.2f}, Area: {best['area_ratio']:.1%}")
        
        if best['score'] < 50:
            print("⚠️ Best region score too low")
            return None
            
        # Add padding
        padding = 20
        left = max(0, best['x'] - padding)
        top = max(0, best['y'] - padding)
        right = min(w, best['x'] + best['w'] + padding)
        bottom = min(h, best['y'] + best['h'] + padding)
        
        # Debug visualization
        if debug_dir:
            debug_img = img.copy()
            # Show top 5 candidates
            colors = [(0,255,0), (255,0,0), (0,0,255), (255,255,0), (255,0,255)]
            for i, region in enumerate(regions[:5]):
                color = colors[i % len(colors)]
                cv2.rectangle(debug_img, (region['x'], region['y']), 
                            (region['x']+region['w'], region['y']+region['h']), color, 2)
                cv2.putText(debug_img, f"{i+1}:{region['score']:.0f}", 
                          (region['x'], region['y']-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
            
            # Highlight the winner
            cv2.rectangle(debug_img, (left, top), (right, bottom), (0,255,255), 4)
            cv2.imwrite(os.path.join(debug_dir, "manual_adjustment_debug.jpg"), debug_img)
        
        return (left, top, right, bottom)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def test_simple_approaches(image_path: str, output_dir: str):
    """Test both simple approaches."""
    if not os.path.exists(image_path):
        print(f"❌ Image not found: {image_path}")
        return
        
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"📄 Testing: {image_path}")
    with Image.open(image_path) as img:
        print(f"📐 Original: {img.width} x {img.height}")
    
    filename = os.path.basename(image_path)
    name, ext = os.path.splitext(filename)
    
    # Test simple detection
    print("\n" + "="*50)
    boundaries1 = simple_card_detection(image_path, output_dir)
    if boundaries1:
        left, top, right, bottom = boundaries1
        img = Image.open(image_path)
        cropped = img.crop(boundaries1)
        output_path1 = os.path.join(output_dir, f"{name}_simple{ext}")
        cropped.save(output_path1, format='JPEG', quality=100)
        print(f"✅ Simple method: {output_path1}")
        print(f"📐 Result: {right-left} x {bottom-top}")
    
    # Test manual adjustment detection  
    print("\n" + "="*50)
    boundaries2 = manual_adjustment_detection(image_path, output_dir)
    if boundaries2:
        left, top, right, bottom = boundaries2
        img = Image.open(image_path)
        cropped = img.crop(boundaries2)
        output_path2 = os.path.join(output_dir, f"{name}_manual{ext}")
        cropped.save(output_path2, format='JPEG', quality=100)
        print(f"✅ Manual method: {output_path2}")
        print(f"📐 Result: {right-left} x {bottom-top}")

if __name__ == "__main__":
    # Test on all images in test_images
    test_dir = "/Users/kregboyd/Applications/card-capture-api/test_images"
    output_dir = "/Users/kregboyd/Applications/card-capture-api/trim_image_test"
    
    print("🎯 SIMPLE CARD DETECTION TEST")
    print("="*50)
    print("Testing MUCH simpler approaches...")
    
    if os.path.exists(test_dir):
        images = [f for f in os.listdir(test_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
        
        for img_file in images[:2]:  # Test first 2 images
            img_path = os.path.join(test_dir, img_file)
            print(f"\n{'='*60}")
            print(f"Testing: {img_file}")
            print(f"{'='*60}")
            test_simple_approaches(img_path, output_dir)
    else:
        print(f"❌ Test directory not found: {test_dir}")
    
    print(f"\n📁 Check results in: {output_dir}")
    print("\n💡 These methods focus on finding regions that are clearly different")
    print("   from the background corners, which should work for any card type.")