


# message.py
import json
import uuid
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class Message:
    role: str                      # 谁发出的: user / agent / tool
    type: str                      # 消息目的: plain / tool_call
    content: Any                   # plain 为文本；tool_call 为 dict
    seq: int | None = None         # 在 session 中的序号，由 MessageWrapper.add 赋值
    call_id: str | None = None     # 仅 tool call / tool result 使用，用于配对
    start: int | None = None       # 仅 context：压缩范围起点（seq，含）
    end: int | None = None         # 仅 context：压缩范围终点（seq，含）

    def toJson(self):
        """单条消息 -> json 字符串。"""
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def fromJson(cls, text):
        """json 字符串 -> 单条消息。"""
        # cls 是类本身（class 的缩写）
        # data = json.loads(text)
        # # {"role": "agent", "type": "tool_call", "content": {...}, "seq": None, "call_id": "a1b2c3d4"}
        #
        # msg = cls(**data)
        # # 等价于 Message(role="agent", type="tool_call", content={...}, seq=None, call_id="a1b2c3d4")
        return cls(**json.loads(text))



def createUserMessage(text):
    return Message(role="user", type="plain", content=text)


def createAiMessage(text):
    return Message(role="agent", type="plain", content=text)


def create_AiToolCall_Message(name, arguments, call_id=None):
    """call_id 不传则自动生成（ollama 等本地模型通常不提供）。"""
    return Message(
        role="agent",
        type="tool_call",
        content={"name": name, "arguments": arguments},
        call_id=call_id or uuid.uuid4().hex[:8],
    )


def create_ToolResult_Message(text, call_id):
    return Message(role="tool", type="plain", content=text, call_id=call_id)



def createContextMessage(text, start, end):
    return Message(role="context", type="plain", content=text, start=start, end=end)




