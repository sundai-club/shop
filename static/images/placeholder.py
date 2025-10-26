#!/usr/bin/env python3
"""
Create simple placeholder images for the SundAI Merch Shop
"""

from PIL import Image, ImageDraw, ImageFont
import os

def create_placeholder(width, height, text, filename):
    """Create a simple placeholder image"""
    # Create image with light gray background
    img = Image.new('RGB', (width, height), color='#f8f9fa')
    draw = ImageDraw.Draw(img)

    # Add text
    try:
        # Try to use a nice font
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
    except:
        # Fallback to default font
        font = ImageFont.load_default()

    # Get text bounding box
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # Center the text
    x = (width - text_width) // 2
    y = (height - text_height) // 2

    # Draw text
    draw.text((x, y), text, fill='#999', font=font)

    # Save image
    img.save(filename)
    print(f"Created {filename}")

if __name__ == "__main__":
    # Create placeholder images
    create_placeholder(400, 400, "SundAI T-Shirt", "tshirt.jpg")
    create_placeholder(400, 400, "SundAI Hoodie", "hoodie.jpg")
    create_placeholder(400, 400, "SundAI Cap", "cap.jpg")
    create_placeholder(400, 400, "SundAI Tote Bag", "tote.jpg")

    print("Placeholder images created successfully!")