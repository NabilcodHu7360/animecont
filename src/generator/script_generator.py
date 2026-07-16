"""
script_generator.py
Uses Claude API to generate a cinematic video essay / podcast script
for the post-anime manga continuation of any given anime.
"""
import anthropic
import os


SYSTEM_PROMPT = """You are a professional anime video essayist and podcast host.
Your writing style is cinematic, emotionally engaging, and deeply invested in the story.
You write scripts that feel like premium YouTube video essays — the kind that get millions of views
because they make people FEEL something, not just learn something.

When given an anime title and context, you write the full continuation story
(what happened in the manga after the anime ended) as a complete narration script.

Structure every script with:
- A gripping cold open (hook them in 30 seconds)
- Clear acts with emotional escalation
- [MUSIC CUE] and [BEAT] markers for production
- A closing monologue that lands the theme
- [HOST] sections for direct address

Write in present tense for the narration. Be dramatic. Be specific. Make people cry if the story deserves it."""


def generate_script(anime_name: str, context: dict, target_length: str = "full") -> str:
    """
    Generates a full cinematic script for the anime continuation.

    Args:
        anime_name: Name of the anime
        context: Dict from wiki_scraper.get_anime_context()
        target_length: "short" (10 min), "medium" (20 min), "full" (30+ min)

    Returns:
        Full script as a string
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    length_guide = {
        "short": "~1500 words, 10 minutes of audio",
        "medium": "~3000 words, 20 minutes of audio",
        "full": "~5000 words, 30+ minutes of audio",
    }.get(target_length, "~5000 words")

    wiki_section = ""
    if context.get("wikipedia_summary"):
        wiki_section = f"\n\nWikipedia context:\n{context['wikipedia_summary']}"
    if context.get("fandom_detail"):
        wiki_section += f"\n\nFandom wiki detail:\n{context['fandom_detail']}"

    user_prompt = f"""Write a full cinematic video essay / podcast script for:

ANIME: {anime_name}
TARGET LENGTH: {length_guide}
{wiki_section}

The script should cover everything that happened in the manga AFTER the anime ended.
Use your training knowledge of {anime_name} to tell this story accurately and emotionally.
Include all major reveals, character arcs, and the ending.

Format with [MUSIC CUE], [BEAT], [HOST], [VISUAL] markers throughout.
Make it dramatic. Make it personal. Make it unforgettable."""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=8000,
        messages=[{"role": "user", "content": user_prompt}],
        system=SYSTEM_PROMPT,
    )

    return message.content[0].text


def extract_scene_prompts(script: str) -> list[dict]:
    """
    Parses [VISUAL] markers from the script to extract image generation prompts.
    Returns list of dicts with 'timestamp' and 'prompt'.
    """
    scenes = []
    lines = script.split("\n")
    for i, line in enumerate(lines):
        if "[VISUAL]" in line or "[visual]" in line.lower():
            # Extract the description after [VISUAL]:
            desc = line.replace("[VISUAL]", "").replace("[visual]", "").strip().strip(":")
            if desc:
                scenes.append({
                    "index": len(scenes),
                    "description": desc,
                    "image_prompt": f"anime art style, cinematic, painterly, {desc}, 16:9, dramatic lighting"
                })
    return scenes
