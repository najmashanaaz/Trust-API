"""
backend/adapters/openai_compatible.py
──────────────────────────────────────
Generic adapter for any provider that implements the OpenAI Chat Completions
wire format.  Confirmed compatible with:
    - OpenAI        (https://api.openai.com/v1)
    - Groq          (https://api.groq.com/openai/v1)
    - Fireworks AI  (https://api.fireworks.ai/inference/v1)
    - Together AI   (https://api.together.xyz/v1)
    - DeepSeek      (https://api.deepseek.com/v1)

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


def call(
    standard_request: dict,
    base_url: str,
    api_key: str,
    model: str,
) -> dict:
    """
    Sends a chat-completion request to any OpenAI-compatible endpoint.

    Parameters
    ----------
    standard_request : dict
        Must contain a "messages" key with a list of role/content dicts.
    base_url : str
        Provider base URL, e.g. "https://api.groq.com/openai/v1".
        This function appends "/chat/completions" automatically.
    api_key : str
        Bearer token for the provider.
    model : str
        Model identifier, e.g. "gpt-4o-mini" or "llama-3.3-70b-versatile".

    Returns
    -------
    dict  {"content": str, "raw": dict}

    Raises
    ------
    RuntimeError
        On any HTTP error or unexpected response shape, with a clear message.
        The caller (proxy.py) is responsible for catching this.
    """
    url = f"{base_url.rstrip('/')}/chat/completions"

    payload = {
        "model":    model,
        "messages": standard_request["messages"],
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }

    response = requests.post(url, json=payload, headers=headers, timeout=30, verify=False)

    if not response.ok:
        raise RuntimeError(
            f"HTTP {response.status_code} from {url}: {response.text[:300]}"
        )

    data = response.json()

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(
            f"Unexpected response shape from {url}: {str(data)[:300]}"
        ) from exc

    return {"content": content, "raw": data}
