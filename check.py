from anthropic import Anthropic
from config import settings

client = Anthropic(api_key=settings.anthropic_api_key)

try:
    response = client.completions.create(
        model="claude-3-sonnet-20240229",
        prompt="Hello world",
        max_tokens_to_sample=10
    )
    print(response.completion)
except Exception as e:
    print("Error calling Anthropic API:", e)
