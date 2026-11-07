# cc_agent/agent/agent.py
import json

from cc_agent.message.message import (
    createUserMessage,
    createAiMessage,
    create_AiToolCall_Message,
    create_ToolResult_Message,
)
from cc_agent.mcp_server.client import execute_tool, ToolExecuteError
from cc_agent.model.OllamaOpenAI import OllamaOpenAI
from cc_agent.skill import Skill

# model_cfg.type 到聊天模型类的映射。
# OllamaOpenAI 把 api_key 写死成 "ollama"，所以 deepseek（需要真实 key）暂不支持。
DICT_TYPE2MODEL = {
    "ollama": OllamaOpenAI,
    "vllm": OllamaOpenAI,
}

MAX_STEPS = 15   # 单轮 generate 最多调用模型的次数

LOAD_SKILL_NAME = "load_skill"   # 内置工具名。MCP 工具名一定带 server__ 前缀，所以不会重名

def parse_skill(model_cfg):
    """按 model_cfg.skill 里记录的名字，到 model_cfg.belong 对应的目录加载 skill，返回 {名字: Skill}。

    文件找不到会直接抛 FileNotFoundError：配置里记了名字但文件没了，应该尽早报错。
    """
    dict_name2skill = {}
    for skill_name in model_cfg.skill:
        dict_name2skill[skill_name] = Skill.load(skill_name, model_cfg.belong)
    #  {name: skill类实例}
    return dict_name2skill


def build_skill_prompt(dict_name2skill):
    """可用 skill 的列表文本，接在 system prompt 后面；没有 skill 返回空字符串。"""
    if not dict_name2skill:
        return ""
    skill_lines = ["", "", f"你可以使用以下 skill。需要某个 skill 的详细指令时，调用 {LOAD_SKILL_NAME} 工具并传入它的名字："]
    for skill in dict_name2skill.values():
        skill_lines.append(skill.prompt_line())
    return "\n".join(skill_lines)


def build_load_skill_tool(dict_name2skill):
    """load_skill 工具的 OpenAI 格式定义。enum 限定只能填已有的名字，小模型不容易编出不存在的名字。"""
    return {
        "type": "function",
        "function": {
            "name": LOAD_SKILL_NAME,
            "description": "加载某个 skill 的完整指令。",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "enum": list(dict_name2skill),
                        "description": "skill 的名字",
                    },
                },
                "required": ["skill_name"],
            },
        },
    }

def parse(model_cfg):
    """从 model_cfg 得到 (模型对象, 工具列表)。工具名已带 server 别名前缀，如 local__add。"""
    if model_cfg.type not in DICT_TYPE2MODEL:
        raise NotImplementedError(f"unsupported model type: {model_cfg.type}")
    model_class = DICT_TYPE2MODEL[model_cfg.type]
    llm = model_class(model_cfg.model_name, model_cfg.url)
    tools = model_cfg.to_openai_tools()
    return llm, tools


def to_openai_messages(system_prompt, messages):
    """把 Message 列表转成 OpenAI 格式的 dict 列表，system 放最前面。

    - context 消息（压缩摘要）并进 system 文本，保证只有一条 system
    - 连续的 tool_call 消息合并成一条带 tool_calls 的 assistant 消息
    """
    system_text = system_prompt
    openai_messages = []
    pending_calls = []

    for message in messages:
        if message.type == "tool_call":
            pending_calls.append({
                "id": message.call_id,
                "type": "function",
                "function": {
                    "name": message.content["name"],
                    "arguments": json.dumps(message.content["arguments"] or {}, ensure_ascii=False),
                },
            })
            continue

        if pending_calls:
            openai_messages.append({"role": "assistant", "content": "", "tool_calls": pending_calls})
            pending_calls = []

        if message.role == "context":
            system_text += "\n\n以下是更早对话的摘要：\n" + message.content
        elif message.role == "user":
            openai_messages.append({"role": "user", "content": message.content})
        elif message.role == "agent":
            openai_messages.append({"role": "assistant", "content": message.content})
        elif message.role == "tool":
            openai_messages.append({"role": "tool", "tool_call_id": message.call_id, "content": message.content})
        else:
            raise ValueError(f"unknown role: {message.role}")

    if pending_calls:
        openai_messages.append({"role": "assistant", "content": "", "tool_calls": pending_calls})

    return [{"role": "system", "content": system_text}] + openai_messages


class Agent:
    def __init__(self, history, model_cfg, system_prompt=""):
        self.history = history          # 同一个对象的引用，不是副本
        self.model_cfg = model_cfg
        self.llm, self.tools = parse(model_cfg)
        self.dict_name2skill = parse_skill(model_cfg)

        self.system_prompt = system_prompt + build_skill_prompt(self.dict_name2skill)
        if self.dict_name2skill:        # 没有 skill 时不给模型一个没用的工具
            self.tools.append(build_load_skill_tool(self.dict_name2skill))

    async def run_tool(self, call_message):
        """执行一条 tool_call 消息，返回工具结果消息。任何出错都变成结果文本交给模型，不中断 loop。"""
        prefixed_name = call_message.content["name"]
        arguments = call_message.content["arguments"]
        call_id = call_message.call_id

        if not isinstance(arguments, dict):
            return create_ToolResult_Message("tool error: arguments must be a JSON object", call_id)
        if prefixed_name == LOAD_SKILL_NAME:
            return self.run_load_skill(arguments, call_id)
        if "__" not in prefixed_name:
            return create_ToolResult_Message(f"tool error: unknown tool {prefixed_name}", call_id)

        server_name, raw_name = prefixed_name.split("__", 1)
        if server_name not in self.model_cfg.dict_server2url:
            return create_ToolResult_Message(f"tool error: unknown server {server_name}", call_id)

        url = self.model_cfg.dict_server2url[server_name]
        try:
            result = await execute_tool(url, raw_name, arguments)
        except ToolExecuteError as error:
            return create_ToolResult_Message(f"tool error: {error}", call_id)
        return create_ToolResult_Message(str(result), call_id)

    def run_load_skill(self, arguments, call_id):
        """返回某个 skill 的完整指令正文。名字不对时把可用的名字列出来，让模型自己更正。"""
        skill_name = arguments.get("skill_name")
        if not isinstance(skill_name, str) or skill_name not in self.dict_name2skill:
            available = ", ".join(self.dict_name2skill)
            return create_ToolResult_Message(f"tool error: unknown skill {skill_name!r}, available: {available}", call_id)
        return create_ToolResult_Message(self.dict_name2skill[skill_name].content, call_id)

    async def generate(self, user_input):
        """跑一轮：用户输入 -> (模型 -> 工具)* -> 最终回复。返回最终回复文本。

        两个并行的列表：
        - turn_messages：Message 对象，本轮结束时一次性存进 history
        - openai_messages：OpenAI 格式的 dict，每一步只追加，直接传给模型
        """

        # ===== 1. turn_start：准备本轮的两个列表 =====
        # turn_messages：元素是 Message 对象（你自己定义的数据类）。用途是本轮结束时 history.add 逐条存档。它永远不会发给模型。
        turn_messages = [createUserMessage(user_input)]

        # openai_messages：元素是 OpenAI 格式的 dict（{"role": ..., "content": ...}）。用途是每一步直接传给 self.llm.generate，让模型看到完整对话。它永远不会存进 history。
        # history 和用户输入只在这里转换一次，之后每步只往 openai_messages 追加
        openai_messages = to_openai_messages(self.system_prompt, self.history.messages + turn_messages)

        # ===== 6. 重复流程：每次循环就是一次 "2 -> 3 -> 4 -> 5"，直到第 3 步发现没有 toolCall =====
        for step in range(MAX_STEPS):

            # ===== 2. model.complete()：调用模型，生成 assistant message =====
            reply = await self.llm.generate(openai_messages, self.tools)

            # ===== 3. 判断 assistant message 是否包含 toolCall =====
            if not reply.tool_calls:
                # --- 没有 toolCall：agent_end，流程结束 ---
                final_text = reply.content or ""
                turn_messages.append(createAiMessage(final_text))
                for message in turn_messages:       # 整轮消息一次性入库
                    self.history.add(message)
                self.history.save()                 # 落盘
                await self.history.checkCompact()   # 窗口满了就压缩
                return final_text

            # --- 有 toolCall：模型的回复对象原样放进 openai_messages，下一次调用模型时它能看到自己发起过哪些调用 ---
            openai_messages.append(reply)

            # --- 同一份回复转成 Message，放进 turn_messages 供入库 ---
            if reply.content:                       # 模型调用工具之前说的话（如果有）
                turn_messages.append(createAiMessage(reply.content))

            # 如果回复中多个工具调用。需要拆解成多个tool call message放到history中
            call_messages = []
            for tool_call in reply.tool_calls:
                arguments = self.parse_arguments(tool_call.function.arguments)
                call_message = create_AiToolCall_Message(
                    tool_call.function.name,
                    arguments,
                    tool_call.id,                   # 为空时 create_AiToolCall_Message 会自动生成
                )
                # 让 reply 里的 id 和 Message 里的 call_id 一致，工具结果才能和调用配对
                tool_call.id = call_message.call_id
                # tool_call 和 reply.tool_calls 里的元素是同一个对象，通过 .id = 赋值会直接改到 reply；
                # reply 已放进 openai_messages，所以发给模型的调用 id 也同步变成 call_message.call_id

                call_messages.append(call_message)
            turn_messages.extend(call_messages)     # 一个调用一条 Message

            for call_message in call_messages:
                # ===== 4. execute tool：执行工具 =====
                tool_result = await self.run_tool(call_message)

                # ===== 5. append toolResult：把工具结果追加到对话中 =====
                turn_messages.append(tool_result)
                openai_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_result.call_id,
                    "content": tool_result.content,
                })

            # 回到 for 的开头，再次执行第 2 步

        # 超过 MAX_STEPS 还没有最终回复：本轮消息直接丢弃，history 保持不变
        raise RuntimeError(f"超过 {MAX_STEPS} 步仍没有最终回复，本轮消息未写入 history")

    def parse_arguments(self, raw_arguments):
        """模型给的参数字符串 -> dict。空字符串当成没有参数；非法 JSON 返回 None，由 run_tool 报错给模型。"""
        if not raw_arguments or not raw_arguments.strip():
            return {}
        try:
            return json.loads(raw_arguments)
        except json.JSONDecodeError:
            return None
