# model.py


class Model:
    """模型基类：只规定一件事——给一份 messages，返回模型的回复。

    不持有任何状态，不管理工具。同一个 model 对象可以被多个 Agent 共用。
    """

    async def generate(self, messages, tools=None):
        """子类必须实现。

        messages  OpenAI 兼容格式的消息列表（含 system 消息），由调用方拼好，原样使用
        tools     OpenAI 兼容格式的工具说明列表，由调用方每次传入；None 或空列表表示不带工具
        返回      模型的回复对象，是否有工具调用由调用方（Agent 的 loop）判断
        """
        raise NotImplementedError
