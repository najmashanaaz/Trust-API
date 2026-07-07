"""
backend/apis.py
───────────────
PURPOSE:
    Defines the list of 16 official AI Provider and API Status Pages to monitor.
    Each dictionary contains the name of the AI service, the official status page url,
    and a flag indicating whether the provider is hosted on standard Statuspage.io
    (which exposes a clean JSON endpoint at url + '/api/v2/status.json').
"""

APIS_TO_MONITOR = [
    {
        "name": "OpenAI",
        "url": "https://status.openai.com",
        "type": "statuspage"
    },
    {
        "name": "Google Cloud",
        "url": "https://status.cloud.google.com",
        "type": "custom"
    },
    {
        "name": "Anthropic",
        "url": "https://status.anthropic.com",
        "type": "statuspage"
    },
    {
        "name": "xAI (Grok)",
        "url": "https://status.x.ai",
        "type": "statuspage"
    },
    {
        "name": "Mistral AI",
        "url": "https://status.mistral.ai",
        "type": "statuspage"
    },
    {
        "name": "Cohere",
        "url": "https://status.cohere.com",
        "type": "statuspage"
    },
    {
        "name": "DeepSeek",
        "url": "https://status.deepseek.com",
        "type": "statuspage"
    },
    {
        "name": "Perplexity",
        "url": "https://status.perplexity.ai",
        "type": "statuspage"
    },
    {
        "name": "Meta (Llama)",
        "url": "https://metastatus.com",
        "type": "custom"
    },
    {
        "name": "Microsoft Azure",
        "url": "https://status.azure.com",
        "type": "custom"
    },
    {
        "name": "Amazon Bedrock (AWS)",
        "url": "https://health.aws.amazon.com/health/status",
        "type": "custom"
    },
    {
        "name": "IBM Watsonx",
        "url": "https://cloud.ibm.com/status",
        "type": "custom"
    },
    {
        "name": "Hugging Face",
        "url": "https://status.huggingface.co",
        "type": "statuspage"
    },
    {
        "name": "Groq",
        "url": "https://status.groq.com",
        "type": "statuspage"
    },
    {
        "name": "Together AI",
        "url": "https://status.together.ai",
        "type": "statuspage"
    },
    {
        "name": "Fireworks AI",
        "url": "https://status.fireworks.ai",
        "type": "statuspage"
    }
]
