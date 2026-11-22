from src.extraction.llm_client import GroqClient
from openai import APIStatusError

client = GroqClient()

try:
    response = client.client.chat.completions.create(
        model=client.model,
        messages=[
            {"role": "user", "content": "Reply with OK"}
        ],
        max_tokens=10,
    )

    print(response.choices[0].message.content)

except APIStatusError as error:
    print("STATUS:", error.status_code)
    print("BODY:", error.response.text)

except Exception as error:
    print(type(error).__name__, error)