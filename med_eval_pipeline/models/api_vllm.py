import requests
import json
import logging
from .base_api import BaseAPI

class API_vllm(BaseAPI):
    def __init__(self, config: dict):
        super().__init__(config)
        self.model_name = config.get('model_name')
        self.api_key = config.get('api_key', "EMPTY")
        self.base_url = config.get('base_url', "http://localhost:8000/v1")

        # Construct full URL for chat completions
        if self.base_url.endswith('/'):
            self.url = f"{self.base_url}chat/completions"
        else:
            self.url = f"{self.base_url}/chat/completions"

    def generate_inner(self, prompt: str) -> str:
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }
        
        messages = [{"role": "user", "content": prompt}]
        
        # Support add_nothink_postfix if configured (adapted for text)
        if self.config.get('add_nothink_postfix', False):
             messages[-1]['content'] += "\n/nothink"
             messages.append({"role": "assistant", "content": "<think></think>"})

        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "temperature": self.config.get('temperature', 0.0),
            "max_tokens": self.config.get('max_tokens', 1024),
            "top_p": self.config.get('top_p', 1.0),
            "top_k": self.config.get('top_k'),
            "repetition_penalty": self.config.get('repetition_penalty'),
            "frequency_penalty": self.config.get('frequency_penalty'),
            "decoder_input_details": self.config.get('decoder_input_details'),
            "stop": self.config.get('stop'),
            "stop_token_ids": self.config.get('stop_token_ids'),
            "skip_special_tokens": False,
            "include_stop_str_in_output": self.config.get('include_stop_str_in_output', False)
        }
        
        if 'force_thinking_token_nums' in self.config:
            payload['force_thinking_token_nums'] = self.config['force_thinking_token_nums']
            
        # Remove keys with None values
        payload = {k: v for k, v in payload.items() if v is not None}

        try:
            response = requests.post(
                self.url, 
                headers=headers, 
                data=json.dumps(payload), 
                verify=False,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                return response.json()['choices'][0]['message']['content']
            else:
                logging.error(f"VLLM API request failed with status {response.status_code}: {response.text}")
                raise Exception(f"VLLM API request failed: {response.status_code}")
                
        except Exception as e:
            logging.error(f"VLLM API request failed: {e}")
            raise e