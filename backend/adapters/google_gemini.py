"""
backend/adapters/google_gemini.py
──────────────────────────────────
Adapter for Google's Gemini API, which uses a completely different
request/response format from the OpenAI-compatible providers.

Key differences from OpenAI wire format:
  - Auth:    query param  ?key={api_key}  (not a Bearer header)
  - Roles:   "user" / "model"             (not "user" / "assistant")
  - Body:    {"contents": [{"role": ..., "parts": [{"text": ...}]}]}
  - System messages are not a first-class concept — they must be merged
    into the first user turn as a prefix.
  - Response: response["candidates"][0]["content"]["parts"][0]["text"]

Standard request shape expected by this adapter:
    {
        "messages": [{"role": "user"|"assistant"|"system", "content": "..."}]
    }

Standard response shape returned:
    {
        "content": "<reply text>",
        "raw":     <full original provider response dict>
    }
"""

import requests


def _convert_messages(messages: list[dict]) -> list[dict]:
    """
    Converts standard OpenAI-style messages into Gemini's `contents` format.

    Rules applied:
    1. "system" role has no direct Gemini equivalent.  Any system messages
       are collected and prepended (as plain text) to the first user message.
       If there is no user message, a synthetic one is created.
    2. "assistant" role maps to Gemini's "model" role.
    3. "user" role stays "user".
    4. Consecutive messages from the same role are merged (Gemini requires
       alternating user/model turns).
    """
    # Step 1: collect system text and filter it out of the main list
    system_parts: list[str] = []
    filtered: list[dict] = []
    for msg in messages:
        if msg["role"] == "system":
            system_parts.append(msg["content"])
        else:
            filtered.append(msg)

    # Step 2: prepend system text to the first user message (or create one)
    if system_parts:
        system_prefix = "\n".join(system_parts)
        if filtered and filtered[0]["role"] == "user":
            filtered[0] = {
                "role":    "user",
                "content": f"{system_prefix}\n\n{filtered[0]['content']}",
            }
        else:
            filtered.insert(0, {"role": "user", "content": system_prefix})

    # Step 3: map roles and build Gemini contents list
    # Also merge consecutive same-role turns (Gemini requires strict alternation)
    contents: list[dict] = []
    for msg in filtered:
        gemini_role = "model" if msg["role"] == "assistant" else "user"
        if contents and contents[-1]["role"] == gemini_role:
            # Merge into previous turn
            contents[-1]["parts"][0]["text"] += "\n" + msg["content"]
        else:
            contents.append({
                "role":  gemini_role,
                "parts": [{"text": msg["content"]}],
            })

    return contents


def call(
    standard_request: dict,
    api_key: str,
    model: str,
) -> dict:
    """
    Sends a generateContent request to the Google Gemini API.

    Parameters
    ----------
    standard_request : dict
        Must contain a "messages" key with a list of role/content dicts.
    api_key : str
        Google API key (passed as a query parameter, not a header).
    model : str
        Gemini model name, e.g. "gemini-1.5-flash".

    Returns
    -------
    dict  {"content": str, "raw": dict}

    Raises
    ------
    RuntimeError
        On any HTTP error or unexpected response shape.
        The caller (proxy.py) is responsible for catching this.
    """
    url = (
        f"https://generativelanguage.googleapis.com"
        f"/v1beta/models/{model}:generateContent"
        f"?key={api_key}"
    )

    contents = _convert_messages(standard_request["messages"])

    payload = {"contents": contents}

    headers = {"Content-Type": "application/json"}

    response = requests.post(url, json=payload, headers=headers, timeout=30, verify=False)

    if not response.ok:
        raise RuntimeError(
            f"HTTP {response.status_code} from Gemini API: {response.text[:300]}"
        )

    data = response.json()

    try:
        content = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(
            f"Unexpected Gemini response shape: {str(data)[:300]}"
        ) from exc

    return {"content": content, "raw": data}
