"""Download all forum images using the collected image IDs."""
import json
import os
import urllib.request
import time
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "https://investsocial.com/ru/filedata/fetch?id={}"
OUTPUT_DIR = Path("forum_images")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def detect_ext(data):
    if data[:3] == b'\xff\xd8\xff': return '.jpg'
    if data[:4] == b'\x89PNG': return '.png'
    if data[:4] == b'GIF8': return '.gif'
    if data[:4] == b'RIFF': return '.webp'
    if data[:2] == b'BM': return '.bmp'
    return '.jpg'  # default

def download_one(img_id, user_dir):
    filepath_base = user_dir / img_id
    # Check if already downloaded with any extension
    for ext in ['.jpg', '.png', '.gif', '.webp', '.bmp']:
        if (user_dir / f"{img_id}{ext}").exists():
            return "skip"
    
    url = BASE_URL.format(img_id)
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        if len(data) < 500:
            return "tiny"
        ext = detect_ext(data)
        filepath = user_dir / f"{img_id}{ext}"
        with open(filepath, 'wb') as f:
            f.write(data)
        return "ok"
    except Exception as e:
        return f"err:{e}"

users = ['Ferro', 'Hellcat', 'FFM', 'aid']
total_ok = 0
total_skip = 0
total_err = 0

for user in users:
    json_path = OUTPUT_DIR / "_debug" / f"{user}_images.json"
    if not json_path.exists():
        print(f"{user}: no data file")
        continue
    
    with open(json_path) as f:
        data = json.load(f)
    
    img_ids = data['image_ids']
    user_dir = OUTPUT_DIR / user
    user_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n{user}: {len(img_ids)} images to download...")
    ok = skip = err = 0
    
    # Use thread pool for parallel downloads
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(download_one, img_id, user_dir): img_id for img_id in img_ids}
        for i, future in enumerate(as_completed(futures)):
            result = future.result()
            if result == "ok": ok += 1
            elif result == "skip": skip += 1
            else: err += 1
            
            if (i + 1) % 50 == 0 or i + 1 == len(img_ids):
                print(f"  {i+1}/{len(img_ids)}: ok={ok} skip={skip} err={err}")
                sys.stdout.flush()
    
    total_ok += ok
    total_skip += skip
    total_err += err
    print(f"  {user} done: {ok} downloaded, {skip} skipped, {err} errors")

print(f"\n=== TOTAL: {total_ok} downloaded, {total_skip} skipped, {total_err} errors ===")
