"""
image_generator.py
Generates background images via Leonardo.ai API.
Falls back to downloading free placeholder images if no API key.
"""
import os
import requests
import time
from pathlib import Path


LEONARDO_API = "https://cloud.leonardo.ai/api/rest/v1"

# Preset background prompts for generic anime video essays
# Used when the script doesn't have explicit [VISUAL] markers
DEFAULT_SCENE_PROMPTS = [
    "floating sky island above dramatic clouds at golden hour, anime art style, cinematic wide shot, painterly",
    "dark underground civilization glowing lanterns in cavern, anime aesthetic, moody atmosphere",
    "two anime warriors standing in heavy rain at night, emotional scene",
    "ancient Japanese classroom morning light through windows, nostalgic, anime style",
    "epic battle field with energy beams, anime art, dramatic lighting",
    "peaceful village rebuilding after war, warm light, hopeful anime aesthetic",
    "elderly figure holding newborn baby, soft golden light, anime illustration style",
    "anime warrior with dark aura, power unleashed, dramatic sky",
]


def generate_image_leonardo(prompt: str, api_key: str, output_path: Path) -> bool:
    """Generates one image via Leonardo.ai. Returns True on success."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Step 1: Create generation job
    create_url = f"{LEONARDO_API}/generations"
    payload = {
        "prompt": prompt,
        "modelId": "b24e16ff-06e3-43eb-8d33-4416c2d75876",  # DreamShaper
        "width": 1280,
        "height": 720,
        "num_images": 1,
        "guidance_scale": 7,
        "presetStyle": "CINEMATIC",
    }

    r = requests.post(create_url, json=payload, headers=headers, timeout=30)
    if r.status_code != 200:
        return False

    gen_id = r.json()["sdGenerationJob"]["generationId"]

    # Step 2: Poll until complete (usually 15-30s)
    for _ in range(20):
        time.sleep(3)
        poll = requests.get(f"{LEONARDO_API}/generations/{gen_id}", headers=headers)
        data = poll.json().get("generations_by_pk", {})
        if data.get("status") == "COMPLETE":
            images = data.get("generated_images", [])
            if images:
                img_url = images[0]["url"]
                img_data = requests.get(img_url, timeout=30).content
                output_path.write_bytes(img_data)
                return True
            break

    return False


def generate_all_backgrounds(scene_prompts: list[dict], output_dir: Path) -> list[Path]:
    """
    Generates background images for all scenes.
    Returns list of image paths in order.
    """
    api_key = os.getenv("LEONARDO_API_KEY")
    output_dir.mkdir(parents=True, exist_ok=True)
    image_paths = []

    # Use provided scene prompts or fall back to defaults
    prompts_to_use = scene_prompts if scene_prompts else [
        {"index": i, "image_prompt": p} for i, p in enumerate(DEFAULT_SCENE_PROMPTS)
    ]

    for scene in prompts_to_use:
        idx = scene["index"]
        prompt = scene["image_prompt"]
        output_path = output_dir / f"bg_{idx:03d}.jpg"

        print(f"  Image {idx+1}/{len(prompts_to_use)}: {prompt[:60]}...")

        if api_key:
            success = generate_image_leonardo(prompt, api_key, output_path)
            if success:
                print(f"    ✓ Generated")
                image_paths.append(output_path)
                time.sleep(1)
                continue

        # Fallback: download a placeholder from picsum (for testing without API key)
        try:
            seed = idx * 137 + 42
            placeholder_url = f"https://picsum.photos/seed/{seed}/1280/720"
            r = requests.get(placeholder_url, timeout=10)
            if r.status_code == 200:
                output_path.write_bytes(r.content)
                print(f"    ✓ Placeholder downloaded")
                image_paths.append(output_path)
        except Exception as e:
            print(f"    ✗ Failed: {e}")

    return image_paths
