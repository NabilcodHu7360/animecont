"""
gen_characters.py — generate ORIGINAL character-design candidates for a series.

These are original archetype designs (a fire-wielding shinobi, a swordswoman
executioner, etc.) — NOT reproductions of any anime's cast. Each is a common,
generic anime archetype; the random seed gives each run a fresh, original face.
Generate a batch, pick the one you like per role, and that becomes YOUR
character. Those picks feed the IP-Adapter step so the design stays consistent
across every scene.

Usage (in the image venv, .venv):
    python -m src.images.gen_characters jigokuraku --n 4
Writes candidates to data/characters/<series>/<role>_v{n}.png
Then rename your chosen file for each role to <role>.png.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Broad, original archetypes keyed to the roles the script needs. Deliberately
# generic — design freely, diverge from anything recognizable.
ROLES = {
    # User-authored original designs (positive description only). Standalone
    # designs — rendered as written, not steered toward any source cast.
    "jigokuraku": {
        "lead": "a short lean young man, compact athletic build, shoulder-length messy ash-blonde hair tied back loosely, deep crimson heavy-fabric combat tunic, plated steel gauntlets, reinforced leather boots, frontline brawler silhouette",
        "kunoichi": "a slender young woman, sharp asymmetrical purple bob, fully enclosed dark leather tactical suit, multiple utility belts, high-collared neck protection, heavily equipped practical combat gear",
        "executioner": "a young woman, black hair in twin tight braids wrapped around her head, modern asymmetrical grey coat over tight trousers, heavy steel shoulder guards, sword strapped across her back, rugged imposing silhouette",
        "chobei": "a tall broad-shouldered muscular young man, shaved head covered in intricate dark tattoos, tightly fitted high-collared dark military uniform covering him from the neck down, rigid disciplined attire",
        "elder": "a tall mature man, short swept-back silver hair, eyes covered by thick blood-red bandages, heavy fur-lined longcoat over a simple black tunic, winter-ready silhouette",
        "mei": "a small childlike girl, neat dark bowl cut, structured miniature shrine-maiden inspired outfit in navy and slate, rigid formal silhouette",
        "rien": "a striking adult woman, very long dark hair in an intricate tight updo pierced with metallic hairpins, sleek fitted obsidian gown with sharp geometric cutouts, heavy feathered cape, sharp predatory silhouette",
        "youth": "a youthful girl, teal dyed hair in a short choppy style, oversized heavy wool poncho with intricate tribal patterns, thick oversized snow boots, widened silhouette",
        "shugen": "a heavily built young man, shoulder-length tightly coiled dreadlocks, pristine heavily-armored white breastplate over thick chainmail, armored knight silhouette",
        "creature": "a colossal plant-flower monster, a towering petaled Buddha-like body woven from vines and thick roots, a glowing bioluminescent core, alien and inhuman, no human features",
    },
}

BASE = ("original character design, full body, standing, neutral grey background, "
        "anime style, clean lineart, consistent character sheet, highly detailed")
NEG = ("photo, realistic, text, watermark, signature, logo, multiple people, "
       "extra limbs, deformed, lowres, blurry")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m src.images.gen_characters <series> [--n 4]")
        sys.exit(2)
    series = sys.argv[1]
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 4
    roles = ROLES.get(series)
    if not roles:
        print(f"no role set defined for {series!r}; edit ROLES in gen_characters.py")
        sys.exit(2)

    from .image_gen import _load_sd
    out = Path("data/characters") / series
    out.mkdir(parents=True, exist_ok=True)
    pipe = _load_sd()

    for role, desc in roles.items():
        prompt = f"{desc}, {BASE}"
        print(f"\n[{role}] {desc}")
        for i in range(n):
            img = pipe(prompt, negative_prompt=NEG, num_inference_steps=32,
                       guidance_scale=7.0, width=512, height=768).images[0]
            p = out / f"{role}_v{i}.png"
            img.save(p)
            print(f"  wrote {p}")
    print(f"\nDone. Review {out}, pick one per role, rename it to <role>.png "
          "(e.g. lead.png). Those become the IP-Adapter references.")


if __name__ == "__main__":
    main()
