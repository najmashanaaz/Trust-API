"""
backend/package_mapping.py
──────────────────────────
PURPOSE:
    Maps common npm / pip package names to the status-page URL of the
    underlying AI service they depend on.

    Only maps packages to APIs that are actually in APIS_TO_MONITOR —
    no invented or unmonitored services.

    Used by:
        GET /api/package-reliability/{package_name}
        GET /api/dependency-scan
"""

# package name (npm or pip) → status page URL (must match api_url in apis table)
PACKAGE_TO_API: dict[str, str] = {
    # ── OpenAI ────────────────────────────────────────────────────────────────
    "openai":                     "https://status.openai.com",
    "@openai/sdk":                "https://status.openai.com",

    # ── Anthropic ─────────────────────────────────────────────────────────────
    "anthropic":                  "https://status.anthropic.com",
    "@anthropic-ai/sdk":          "https://status.anthropic.com",

    # ── Google Cloud ──────────────────────────────────────────────────────────
    "@google-cloud/aiplatform":   "https://status.cloud.google.com",
    "@google-cloud/storage":      "https://status.cloud.google.com",
    "@google-cloud/bigquery":     "https://status.cloud.google.com",
    "@google-cloud/pubsub":       "https://status.cloud.google.com",
    "google-cloud-aiplatform":    "https://status.cloud.google.com",
    "google-cloud-storage":       "https://status.cloud.google.com",
    "google-generativeai":        "https://status.cloud.google.com",

    # ── Cohere ────────────────────────────────────────────────────────────────
    "cohere":                     "https://status.cohere.com",
    "cohere-ai":                  "https://status.cohere.com",

    # ── Mistral AI ────────────────────────────────────────────────────────────
    "@mistralai/mistralai":       "https://status.mistral.ai",
    "mistralai":                  "https://status.mistral.ai",

    # ── Groq ──────────────────────────────────────────────────────────────────
    "groq":                       "https://status.groq.com",
    "groq-sdk":                   "https://status.groq.com",

    # ── Together AI ───────────────────────────────────────────────────────────
    "together-ai":                "https://status.together.ai",
    "together":                   "https://status.together.ai",
    "togetherclient":             "https://status.together.ai",

    # ── Hugging Face ──────────────────────────────────────────────────────────
    "huggingface_hub":            "https://status.huggingface.co",
    "@huggingface/inference":     "https://status.huggingface.co",
    "transformers":               "https://status.huggingface.co",

    # ── Fireworks AI ──────────────────────────────────────────────────────────
    "fireworks-ai":               "https://status.fireworks.ai",
    "fireworks_ai":               "https://status.fireworks.ai",

    # ── Perplexity ────────────────────────────────────────────────────────────
    "perplexity-client":          "https://status.perplexity.ai",

    # ── DeepSeek ──────────────────────────────────────────────────────────────
    "deepseek":                   "https://status.deepseek.com",

    # ── Microsoft Azure ───────────────────────────────────────────────────────
    "@azure/openai":              "https://status.azure.com",
    "azure-ai-inference":         "https://status.azure.com",
    "@azure/ai-inference":        "https://status.azure.com",
    "azure-cognitiveservices-language": "https://status.azure.com",

    # ── Amazon Bedrock (AWS) ──────────────────────────────────────────────────
    "@aws-sdk/client-bedrock-runtime": "https://health.aws.amazon.com/health/status",
    "boto3":                      "https://health.aws.amazon.com/health/status",
    "botocore":                   "https://health.aws.amazon.com/health/status",
    "amazon-bedrock-client":      "https://health.aws.amazon.com/health/status",

    # ── IBM Watsonx ───────────────────────────────────────────────────────────
    "ibm-watsonx-ai":             "https://cloud.ibm.com/status",
    "ibm_watson":                 "https://cloud.ibm.com/status",

    # ── xAI (Grok) ────────────────────────────────────────────────────────────
    "xai-sdk":                    "https://status.x.ai",
}
