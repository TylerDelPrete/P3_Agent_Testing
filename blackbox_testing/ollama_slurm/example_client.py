"""Run on your workstation after the SSH tunnel is established.
Install: pip install openai
"""
import os
from openai import OpenAI

client = OpenAI(
    base_url=os.getenv('LLM_BASE_URL', 'http://127.0.0.1:6767/v1'),
    api_key=os.getenv('LLM_API_KEY', 'ollama'),
)
response = client.chat.completions.create(
    model=os.getenv('LLM_MODEL', 'gemma3:1b'),
    messages=[{'role': 'user', 'content': 'Reply with one sentence describing prompt injection.'}],
    temperature=0,
)
print(response.choices[0].message.content)
