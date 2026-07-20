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
            "temperature": self.config.get('temperature', 0.7),
            "max_tokens": self.config.get('max_tokens', 1024),
        }
        
        response = self.client.chat.completions.create(**payload)
        # usage_info = {}
        # if response.usage:
        #     usage_info = {
        #         "prompt_tokens": response.usage.prompt_tokens,
        #         "completion_tokens": response.usage.completion_tokens,
        #         "total_tokens": response.usage.total_tokens
        #     }
        # print("OpenAI API Usage:", usage_info)
        return response.choices[0].message.content
    