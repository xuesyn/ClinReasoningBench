from abc import ABC, abstractmethod
import time
import logging

class BaseAPI(ABC):
    def __init__(self, config: dict):
        self.config = config
        self.max_retry = config.get('max_retry', 3)
        self.timeout = config.get('timeout', 120)

    @abstractmethod
    def generate_inner(self, prompt: str) -> str:
        """
        具体的模型调用逻辑，由子类实现。
        """
        pass

    def generate(self, prompt: str, n: int = 1) -> list[str]:
        """
        调用模型生成 n 个结果，包含重试逻辑。
        """
        results = []
        for _ in range(n):
            for i in range(self.max_retry):
                try:
                    response = self.generate_inner(prompt)
                    results.append(response)
                    break  # Success
                except Exception as e:
                    logging.warning(f"API call failed (attempt {i+1}/{self.max_retry}): {e}")
                    if i == self.max_retry - 1:
                        logging.error("API call failed after all retries.")
                        results.append(f"Error: {e}") # Append error message on final failure
                    time.sleep(2 ** i) # Exponential backoff
        return results
