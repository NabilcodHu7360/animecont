import os

DEFAULT_MODELS = {
    "gemini": "gemini-2.0-flash",
    "anthropic": "claude-3-5-sonnet-20241022",
    "ollama": "llama3.1",
}

def _complete_gemini(system, user, model, max_tokens):
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    m = genai.GenerativeModel(model, system_instruction=system)
    resp = m.generate_content(
        user,
        generation_config={"max_output_tokens": max_tokens, "temperature": 0.8},
    )
    return resp.text

def _complete_anthropic(system, user, model, max_tokens):
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    msg = client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")

def _complete_ollama(system, user, model, max_tokens):
    import requests
    resp = requests.post(
        "http://localhost:11434/api/chat",
        json={"model": model, "stream": False,
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}]},
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]

_PROVIDERS = {
    "gemini": _complete_gemini,
    "anthropic": _complete_anthropic,
    "ollama": _complete_ollama,
}

def complete(system, user, provider="gemini", model=None, max_tokens=8000):
    if provider not in _PROVIDERS:
        raise ValueError(f"Unknown provider {provider!r}. Options: {list(_PROVIDERS)}")
    model = model or DEFAULT_MODELS[provider]
    return _PROVIDERS[provider](system, user, model, max_tokens)