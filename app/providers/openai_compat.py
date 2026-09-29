import time

import httpx


class ProviderError(RuntimeError):
    pass


class OpenAICompatProvider:
    """任何 OpenAI 兼容接口：DeepSeek / Ollama / vLLM / OpenAI。

    瞬时故障（读超时、连接错误、429、5xx）自动重试；4xx 直接报错不重试。
    """

    name = "openai_compat"

    def __init__(self, base_url: str, api_key: str, model: str,
                 temperature: float = 0.0, timeout: float = 60.0,
                 max_retries: int = 2, retry_sleep: float = 1.0,
                 client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep
        self.client = client or httpx.Client(timeout=timeout)

    def chat(self, messages, temperature=None):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_err = ProviderError(f"LLM HTTP {resp.status_code}: {resp.text[:200]}")
                else:
                    resp.raise_for_status()
                    return resp.json()["choices"][0]["message"]["content"]
            except httpx.TransportError as e:
                last_err = e
            except httpx.HTTPStatusError as e:
                raise ProviderError(f"LLM HTTP {e.response.status_code}: {e.response.text[:200]}") from e
            except (KeyError, IndexError, TypeError) as e:
                raise ProviderError(f"LLM 调用失败: {e}") from e
            if attempt < self.max_retries and self.retry_sleep:
                time.sleep(self.retry_sleep)
        raise ProviderError(f"LLM 调用失败（已重试 {self.max_retries} 次）: {last_err}") from last_err
