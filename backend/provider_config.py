"""
backend/provider_config.py
──────────────────────────
Lookup table mapping each monitored api_name (as it appears in the `apis`
database table) to the adapter and credentials needed to call that provider's
real API.

Keys must match api_name values in the database exactly (case-sensitive).

Fields per entry:
    adapter         — module name inside backend/adapters/ to use
    base_url        — base URL for OpenAI-compatible providers (omit for Gemini)
    api_key_env     — name of the environment variable that holds the API key
    default_model   — model to use when the caller doesn't specify one

Adding a new provider:
    1. Add an entry here.
    2. If the provider uses a new wire format, create backend/adapters/<name>.py
       with a call() function matching the existing adapter signatures.
    3. Update the dispatch block in backend/proxy.py if a new adapter module
       is introduced.

Providers intentionally NOT listed here (monitored for uptime only):
    - Anthropic       — distinct wire format; adapter not yet implemented
    - xAI (Grok)      — distinct wire format; adapter not yet implemented
    - Mistral AI      — could be added (OpenAI-compatible); not yet configured
    - Cohere          — distinct wire format; adapter not yet implemented
    - Perplexity      — OpenAI-compatible; not yet configured
    - Meta (Llama)    — no direct hosted API endpoint we call
    - Microsoft Azure — requires resource-specific base URLs; not yet configured
    - Amazon Bedrock  — requires AWS Signature v4 auth; not yet configured
    - IBM Watsonx     — distinct auth flow; not yet configured
    - Hugging Face    — multiple endpoint styles; not yet configured
"""

PROVIDER_CONFIG: dict[str, dict] = {
    # ── OpenAI ────────────────────────────────────────────────────────────────
    "OpenAI": {
        "adapter":       "openai_compatible",
        "base_url":      "https://api.openai.com/v1",
        "api_key_env":   "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
    },

    # ── Groq ──────────────────────────────────────────────────────────────────
    "Groq": {
        "adapter":       "openai_compatible",
        "base_url":      "https://api.groq.com/openai/v1",
        "api_key_env":   "GROQ_API_KEY",
        "default_model": "llama-3.3-70b-versatile",
    },

    # ── Fireworks AI ──────────────────────────────────────────────────────────
    "Fireworks AI": {
        "adapter":       "openai_compatible",
        "base_url":      "https://api.fireworks.ai/inference/v1",
        "api_key_env":   "FIREWORKS_API_KEY",
        "default_model": "accounts/fireworks/models/deepseek-v4-flash",
    },

    # ── Together AI ───────────────────────────────────────────────────────────
    # API key not currently configured in .env — this provider will return a clear 'missing API key' error if selected as a backup, rather than crashing
    "Together AI": {
        "adapter":       "openai_compatible",
        "base_url":      "https://api.together.xyz/v1",
        "api_key_env":   "TOGETHER_API_KEY",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    },

    # ── DeepSeek ──────────────────────────────────────────────────────────────
    # API key not currently configured in .env — this provider will return a clear 'missing API key' error if selected as a backup, rather than crashing
    "DeepSeek": {
        "adapter":       "openai_compatible",
        "base_url":      "https://api.deepseek.com/v1",
        "api_key_env":   "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
    },

    # ── Google Cloud (Gemini) ─────────────────────────────────────────────────
    # Note: "Google Cloud" is the api_name in the database.
    # The proxy routes to Gemini via the google_gemini adapter.
    "Google Cloud": {
        "adapter":       "google_gemini",
        "api_key_env":   "GOOGLE_API_KEY",
        "default_model": "gemini-2.5-flash",
    },
}
