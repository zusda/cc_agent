# compress_model.py
from ollama import AsyncClient
from .model import Model


class CompressModel(Model):
    """使用 Ollama Qwen3 压缩消息。"""

    SYSTEM_PROMPT = """
请压缩以下文本，要求：
1. 保留所有关键事实、数字和逻辑关系。
2. 删除重复和冗余描述。
3. 不要改变原文含义。
4. 尽量控制在原文 Token 数量的 70%。
"""

    def __init__(self, model_name="qwen3:8b", host="http://localhost:11434"):
        self.model_name = model_name
        self.client = AsyncClient(host=host)

    async def generate(self, messages, tools=None):
        # 将消息组合成文本
        text = ""

        for message in messages:
            if message.type != "plain":
                continue

            text += f"{message.role}: {message.content}\n"

        # 调用 Qwen3 压缩
        response = await self.client.chat(
            model=self.model_name,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            stream=False
        )

        return response.message.content