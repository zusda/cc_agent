# OllamaOpenAI.py
from openai import AsyncOpenAI

from cc_agent.model.model import Model


class OllamaOpenAI(Model):
    def __init__(self, model_name, base_url="http://localhost:11434/v1"):
        self.model_name = model_name
        # Ollama 的 OpenAI 兼容接口不校验 key，但 SDK 要求必须填一个非空字符串
        self.client = AsyncOpenAI(base_url=base_url, api_key="ollama")

    async def generate(self, messages, tools=None):
        # messages 由外部拼好：system + history + 本轮消息，这里原样透传
        request = {
            "model": self.model_name,
            "messages": messages,
        }

        # 没有工具就整个不传，空列表有的后端会报错
        if tools:
            request["tools"] = tools

        completion = await self.client.chat.completions.create(**request)

        # 原样返回模型的回复，是否调用工具由 loop 判断
        return completion.choices[0].message




