#!/usr/bin/env python3
"""
Fix years in practice_classification_results.json and crop math images.
"""

import json
import re
from pathlib import Path
from PIL import Image

def extract_year_from_path(path):
    """Extract year from path like 'practice/paper 1/Q176_TZ1_2012_sequences'"""
    match = re.search(r'_(\d{4})_', path)
    if match:
        return match.group(1)
    return None

def fix_years_in_json():
    """Update year field in JSON based on folder names"""
    json_path = Path('data/practice_classification_results.json')

    with open(json_path, 'r') as f:
        data = json.load(f)

    updated_count = 0
    for qid, qdata in data.items():
        path = qdata.get('path', '')
        year = extract_year_from_path(path)

        if year and qdata.get('year') != year:
            qdata['year'] = year
            updated_count += 1

    with open(json_path, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"✅ Updated {updated_count} question years in JSON")
    return data

def crop_math_images():
    """Crop corner marks from math question images (not answers)"""
    practice_folder = Path('practice')

    if not practice_folder.exists():
        print("❌ practice folder not found")
        return

    # Find all question images (exclude answer images)
    question_images = []
    for paper_folder in practice_folder.glob('paper *'):
        for q_folder in paper_folder.iterdir():
            if q_folder.is_dir():
                for img in q_folder.glob('*.png'):
                    # Skip answer/markscheme images
                    if 'answer' not in img.name.lower() and 'mark' not in img.name.lower():
                        question_images.append(img)

    print(f"Found {len(question_images)} question images to process")

    cropped_count = 0
    crop_bottom = 100  # Crop 100 pixels from bottom only

    for i, img_path in enumerate(question_images):
        try:
            with Image.open(img_path) as img:
                width, height = img.size

                # Check if image is already too small
                if width < 100 or height < 200:
                    continue

                # Crop bottom only: (left, top, right, bottom)
                cropped = img.crop((
                    0,
                    0,
                    width,
                    height - crop_bottom
                ))

                # Save cropped image
                cropped.save(img_path)
                cropped_count += 1

                if (i + 1) % 100 == 0:
                    print(f"  Processed {i + 1}/{len(question_images)} images...")

        except Exception as e:
            print(f"  ⚠️  Error processing {img_path.name}: {e}")

    print(f"✅ Cropped {cropped_count} images")

if __name__ == '__main__':
    print("=" * 60)
    print("FIXING YEARS IN JSON")
    print("=" * 60)
    fix_years_in_json()

    print("\n" + "=" * 60)
    print("CROPPING MATH QUESTION IMAGES")
    print("=" * 60)
    response = input("This will modify all math question images. Continue? (yes/no): ")
    if response.lower() == 'yes':
        crop_math_images()
    else:
        print("❌ Skipped image cropping")
