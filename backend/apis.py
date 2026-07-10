"""
backend/apis.py
───────────────
PURPOSE:
    Defines the list of 16 official AI Provider and API Status Pages to monitor.
    Each entry includes: name, url, type (statuspage/custom), and category.

    Categories used:
        llm_provider  — large-language-model API providers
        cloud_infra   — general cloud / infrastructure providers
"""

APIS_TO_MONITOR = [
    {
        "name": "OpenAI",
        "url": "https://status.openai.com",
        "type": "statuspage",
        "category": "llm_provider",
    },
    {
        "name": "Google Cloud",
        "url": "https://status.cloud.google.com",
        "type": "custom",
        "category": "cloud_infra",
    },
    {
        "name": "Anthropic",
        "url": "https://status.anthropic.com",
        "type": "statuspage",
        "category": "llm_provider",
    },
    {
        "name": "xAI (Grok)",
        "url": "https://status.x.ai",
        "type": "statuspage",
        "category": "llm_provider",
    },
    {
        "name": "Mistral AI",
        "url": "https://status.mistral.ai",
        "type": "statuspage",
        "category": "llm_provider",
    },
    {
        "name": "Cohere",
        "url": "https://status.cohere.com",
        "type": "statuspage",
        "category": "llm_provider",
    },
    {
        "name": "DeepSeek",
        "url": "https://status.deepseek.com",
        "type": "statuspage",
        "category": "llm_provider",
    },
    {
        "name": "Perplexity",
        "url": "https://status.perplexity.ai",
        "type": "statuspage",
        "category": "llm_provider",
    },
    {
        "name": "Meta (Llama)",
        "url": "https://metastatus.com",
        "type": "custom",
        "category": "llm_provider",
    },
    {
        "name": "Microsoft Azure",
        "url": "https://status.azure.com",
        "type": "custom",
        "category": "cloud_infra",
    },
    {
        "name": "Amazon Bedrock (AWS)",
        "url": "https://health.aws.amazon.com/health/status",
        "type": "custom",
        "category": "cloud_infra",
    },
    {
        "name": "IBM Watsonx",
        "url": "https://cloud.ibm.com/status",
        "type": "custom",
        "category": "cloud_infra",
    },
    {
        "name": "Hugging Face",
        "url": "https://status.huggingface.co",
        "type": "statuspage",
        "category": "llm_provider",
    },
    {
        "name": "Groq",
        "url": "https://status.groq.com",
        "type": "statuspage",
        "category": "llm_provider",
    },
    {
        "name": "Together AI",
        "url": "https://status.together.ai",
        "type": "statuspage",
        "category": "llm_provider",
    },
    {
        "name": "Fireworks AI",
        "url": "https://status.fireworks.ai",
        "type": "statuspage",
        "category": "llm_provider",
    },
]
