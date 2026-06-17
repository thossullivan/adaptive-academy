"""Robust extraction of JSON from model text — one shared home (was copy-pasted 9×).

The old per-module `_strip_fences` only stripped when the text *started* with a code fence,
so the single most common real failure — a one-line preamble before the fence ("Here is the
JSON:\\n```json…") — sailed through to `json.loads` and 502'd the user (a silent grade-loss on
the Assessor path). This tolerates a leading preamble and prose on either side, and falls back
to the original so a genuinely malformed payload still raises a real parse error.
"""


def extract_json(text: str) -> str:
    """Pull the JSON object/array out of model output that may be fenced and/or prose-wrapped."""
    s = (text or "").strip()

    # If fenced anywhere (even after a preamble), take the first fenced block's body.
    if "```" in s:
        parts = s.split("```")
        if len(parts) >= 2:
            s = parts[1]
            lead = s.lstrip()
            if lead[:4].lower() == "json":
                s = lead[4:]
        s = s.strip()

    # If prose still brackets the JSON, trim to the outermost object/array span.
    if not s.startswith(("{", "[")):
        opens = [i for i in (s.find("{"), s.find("[")) if i != -1]
        closes = [i for i in (s.rfind("}"), s.rfind("]")) if i != -1]
        if opens and closes:
            a, b = min(opens), max(closes)
            if b > a:
                s = s[a : b + 1]

    return s.strip()
