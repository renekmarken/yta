"""Small AI client: Gemini (free) with automatic endpoint/model fallback, optional OpenAI.

Works with both kinds of Google keys:
  * Google AI Studio keys (usually start with "AIza")
  * Vertex AI express-mode keys (e.g. start with "AQ.")
"""
import json
import re
import time

import requests

from . import config

_state = {"endpoint": None, "model": None, "auto_models": None, "no_search": False}

AISTUDIO = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
VERTEX = "https://aiplatform.googleapis.com/v1/publishers/google/models/{m}:generateContent"


class AIError(RuntimeError):
    pass


def _endpoints():
    order = ["aistudio", "vertex"]
    if _state["endpoint"]:
        order = [_state["endpoint"]] + [e for e in order if e != _state["endpoint"]]
    return order


def _auto_models():
    """Ask AI Studio which Flash models exist (used when the configured names are retired)."""
    if _state["auto_models"] is not None:
        return _state["auto_models"]
    found = []
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                         params={"pageSize": 200}, timeout=30,
                         headers={"x-goog-api-key": config.GEMINI_API_KEY})
        for m in r.json().get("models", []):
            name = m["name"].split("/")[-1]
            if ("generateContent" in m.get("supportedGenerationMethods", []) and "flash" in name
                    and not re.search(r"image|tts|audio|live|embed|exp", name)):
                found.append(name)
    except Exception:
        pass

    def rank(n):
        ver = re.findall(r"(\d+(?:\.\d+)?)", n)
        return (float(ver[0]) if ver else 0, "lite" not in n, "preview" not in n)
    _state["auto_models"] = sorted(found, key=rank, reverse=True)[:4]
    return _state["auto_models"]


def _call_gemini(endpoint, model, prompt, json_mode, grounded, temperature):
    parts = prompt if isinstance(prompt, list) else [{"text": prompt}]      # a list: text + images
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": temperature}}
    if json_mode and not grounded:
        body["generationConfig"]["responseMimeType"] = "application/json"
    if grounded:
        body["tools"] = [{"google_search": {}} if endpoint == "aistudio" else {"googleSearch": {}}]
    if endpoint == "aistudio":
        return requests.post(AISTUDIO.format(m=model), json=body, timeout=180,
                             headers={"x-goog-api-key": config.GEMINI_API_KEY})
    return requests.post(VERTEX.format(m=model), json=body, timeout=180,
                         params={"key": config.GEMINI_API_KEY})


def _extract(resp_json):
    cand = (resp_json.get("candidates") or [{}])[0]
    parts = cand.get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    sources = []
    for ch in cand.get("groundingMetadata", {}).get("groundingChunks", []) or []:
        web = ch.get("web") or {}
        if web.get("uri"):
            sources.append({"title": web.get("title", ""), "url": web["uri"]})
    if not text:
        raise AIError(f"empty response: {str(resp_json)[:300]}")
    return text, sources


def _try_model(endpoint, model, prompt, json_mode, grounded, temperature):
    """Returns (status, payload): ok | bad_key | no_tools | next."""
    err = ""
    for attempt in range(4):
        try:
            r = _call_gemini(endpoint, model, prompt, json_mode, grounded, temperature)
        except requests.RequestException as e:
            err = str(e)
            time.sleep(5)
            continue
        if r.status_code == 200:
            try:
                return "ok", _extract(r.json())
            except AIError as e:
                return "next", str(e)
        err = f"{endpoint}/{model} HTTP {r.status_code}: {r.text[:300]}"
        if r.status_code == 429 and grounded:
            return "search_quota", err                  # web search is optional: don't wait on it
        if r.status_code == 429 and ("PerDay" in r.text or "limit: 0" in r.text):
            return "next", err                           # daily quota used up: waiting won't help
        if r.status_code in (429, 500, 503):            # rate limit / overloaded: wait, retry
            time.sleep(15 * (attempt + 1))
            continue
        if r.status_code in (401, 403) or "API key not valid" in r.text or "API_KEY_INVALID" in r.text:
            return "bad_key", err
        if grounded and r.status_code == 400 and ("tool" in r.text.lower() or "search" in r.text.lower()):
            return "no_tools", err
        return "next", err
    return "next", err


def gemini(prompt, json_mode=False, grounded=False, temperature=0.7):
    if not config.GEMINI_API_KEY:
        raise AIError("GEMINI_API_KEY is not set")
    if grounded and _state["no_search"]:
        raise AIError("Gemini web search quota used up earlier in this run")
    errors = []
    for endpoint in _endpoints():
        models = list(dict.fromkeys(([_state["model"]] if _state["model"] else []) + config.GEMINI_MODELS))
        auto_added, use_tools, i = False, grounded, 0
        while i < len(models):
            status, payload = _try_model(endpoint, models[i], prompt, json_mode, use_tools, temperature)
            if status == "ok":
                _state["endpoint"], _state["model"] = endpoint, models[i]
                return payload
            errors.append(payload)
            if status == "search_quota":
                _state["no_search"] = True
                raise AIError("Gemini web search quota used up: " + payload)
            if status == "bad_key":
                break                                    # this key belongs to the other endpoint
            if status == "no_tools":
                use_tools = False                        # retry same model without web search
                continue
            i += 1
            if i == len(models) and endpoint == "aistudio" and not auto_added:
                auto_added = True
                models += [m for m in _auto_models() if m not in models]
    raise AIError("Gemini failed: " + " || ".join(errors[-3:]))


def see(prompt, images, json_mode=True, temperature=0.2):
    """Ask Gemini about pictures: `images` are PNG bytes, shown in order after the prompt.
    Returns the text answer."""
    import base64
    parts = [{"text": prompt}]
    for i, png in enumerate(images, 1):
        parts += [{"text": f"Image {i}:"}, {"inline_data": {"mime_type": "image/png", "data": base64.b64encode(png).decode()}}]
    text, _ = gemini(parts, json_mode=json_mode, temperature=temperature)
    return text


def openai_chat(prompt, json_mode=False, temperature=0.7):
    body = {"model": config.OPENAI_MODEL, "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = requests.post("https://api.openai.com/v1/chat/completions", timeout=180, json=body,
                      headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def ask(prompt, json_mode=False, grounded=False, temperature=0.7):
    """Returns (text, sources). Tries Gemini first, then OpenAI if configured."""
    errors = []
    if config.GEMINI_API_KEY:
        try:
            return gemini(prompt, json_mode, grounded, temperature)
        except AIError as e:
            errors.append(str(e))
    if config.OPENAI_API_KEY and not grounded:
        return openai_chat(prompt, json_mode, temperature), []
    raise AIError(" | ".join(errors) or "Set GEMINI_API_KEY (free) or OPENAI_API_KEY")


def parse_json(text):
    """Parse JSON even if the model wrapped it in prose or ``` fences."""
    t = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
    if not starts:
        raise AIError(f"no JSON in response: {t[:200]}")
    s = min(starts)
    closer = "}" if t[s] == "{" else "]"
    e = t.rfind(closer)
    return json.loads(t[s:e + 1])


def resolve_url(url, timeout=10):
    """Follow Google's grounding redirect links to the real article URL."""
    if "grounding-api-redirect" not in url:
        return url
    try:
        r = requests.head(url, allow_redirects=False, timeout=timeout)
        return r.headers.get("Location", url)
    except requests.RequestException:
        return url
