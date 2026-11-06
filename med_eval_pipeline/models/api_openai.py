from openai import OpenAI
from .base_api import BaseAPI

class API_openai(BaseAPI):
    def __init__(self, config: dict):
        super().__init__(config)
        self.client = OpenAI(
            api_key=config.get('api_key'),
            base_url=config.get('base_url'),
            timeout=self.timeout
        )
        self.model_name = config.get('model_name')

    def generate_inner(self, prompt: str) -> str:
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.config.get('temperature', 0.1),
            "max_tokens": self.config.get('max_tokens', 8192),
        }
        # Pass provider-specific options through the OpenAI SDK's escape hatch, e.g. to disable
        # reasoning-mode chain-of-thought on GLM/MaaS:  extra_body: {enable_thinking: false}
        extra_body = self.config.get('extra_body')
        if extra_body:
            payload['extra_body'] = extra_body

        response = self.client.chat.completions.create(**payload)
        msg = response.choices[0].message
        # reasoning models may leave `content` empty and put text in `reasoning_content`.
        content = msg.content or getattr(msg, "reasoning_content", None) or ""
        if not content:
            # An empty 200 is not an exception, so the retry loop in base_api would otherwise accept it
            # silently (-> zero score). Raise so it is retried; it is recorded as "Error: ..." only if it
            # stays empty across all retries.
            fr = response.choices[0].finish_reason
            raise ValueError(f"empty content from {self.model_name} (finish_reason={fr})")
        return content
    