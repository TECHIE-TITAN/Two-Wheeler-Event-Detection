#!/usr/bin/env python3
"""
Simple script to rotate an image upside down (180 degrees)
Usage: python3 rotate_image.py <input_image> <output_image>
"""

import sys
from PIL import Image

def rotate_image_upside_down(input_path, output_path):
    """
    Rotate an image 180 degrees (upside down)
    
    Args:
        input_path: Path to input image
        output_path: Path to save rotated image
    """
    try:
        # Open the image
        img = Image.open(input_path)
        
        # Rotate 180 degrees
        rotated_img = img.rotate(180)
        
        # Save the rotated image
        rotated_img.save(output_path)
        
        print(f"✓ Image rotated successfully!")
        print(f"  Input: {input_path}")
        print(f"  Output: {output_path}")
        print(f"  Size: {img.size}")
        
    except FileNotFoundError:
        print(f"✗ Error: File not found: {input_path}")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 rotate_image.py <input_image> <output_image>")
        print("\nExample:")
        print("  python3 rotate_image.py input.jpg output.jpg")
        sys.exit(1)
    
    input_image = sys.argv[1]
    output_image = sys.argv[2]
    
    rotate_image_upside_down(input_image, output_image)
