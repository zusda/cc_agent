

# SessionHistory.py

from cc_agent.config import USER_DIR, MAX_MESSAGES, COMPACT_COUNT
from cc_agent.message.message import Message, createContextMessage
import asyncio

from cc_agent.model.compress_model import CompressModel


# 一个session对应一个
class SessionHistory:
    def __init__(self, user_id, session_id):
        """一个 session 的历史消息管理器：负责读、写、压缩，Agent 不直接碰 session 文件。

        对应磁盘上的一个文件 USER_DIR/<user_id>/<session_id>.jsonl，每行是一条 Message 的 JSON。
        内存里只保留一个"窗口" self.messages：从文件里最后一条 context 消息（含）开始，一直到文件末尾。
        context 消息是旧消息压缩后的摘要，它之前的消息不再读进内存，但仍留在文件里。

        属性：
            user_id, session_id   这个 session 属于谁、叫什么
            path                  session 文件的路径（Path 对象）
            messages              内存窗口，Message 对象列表，按 seq 递增排列
            saved_seq             文件里已经写到的最大 seq
            next_seq              下一条新消息该用的 seq（= 窗口里最大 seq + 1）

        方法：
            load()                从文件重新读出窗口，覆盖 self.messages
            add(message)          给新消息编号并放进窗口，不写文件
            save()                把还没落盘的消息追加到文件尾
            compress(start, end)  把一段消息压成摘要文本（占位，尚未实现）
            checkCompact()        窗口达到上限时触发 compact
            compact()             把最旧的一批消息压成 context，重排窗口并落盘

        典型用法（Agent 一轮 loop 里）：
            wrapper.messages           读历史，拼 context
            wrapper.add(message)       本轮新消息逐条加入
            wrapper.save()             落盘
            wrapper.checkCompact()     必要时压缩
        """
        self.user_id = user_id
        self.session_id = session_id
        self.path = USER_DIR / user_id / "session" / (session_id + ".jsonl")
        if not self.path.exists():
            raise FileNotFoundError(
                f"session 文件不存在: user={user_id}, session={session_id}"
            )
        self.messages = []
        self.load()
        self.loaded_len = 0


    def load(self):
        # """读入全部行，从后往前取，遇到 context 消息（包含它）或到头为止。
        # 会覆盖当前 self.messages。"""
        with self.path.open("r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        messages = []
        for line in reversed(lines):
            message = Message.fromJson(line)
            messages.append(message)
            if message.role == "context":
                break
        messages.reverse()                        # 恢复成文件顺序（seq 递增）
        self.messages = messages
        # 窗口最后一条就是文件最后一条，seq 最大
        self.saved_seq = messages[-1].seq if messages else 0
        self.next_seq = self.saved_seq + 1




    def add(self, message):
        """seq 接着文件中最大的 seq 往后排，不写文件。"""
        message.seq = self.next_seq
        self.next_seq += 1
        self.messages.append(message)



    def save(self):
        """增量：把 seq 大于 saved_seq 的消息追加到文件尾。"""
        with self.path.open("a", encoding="utf-8") as f:
            for message in self.messages:
                if message.seq > self.saved_seq:
                    f.write(message.toJson() + "\n")
        self.saved_seq = self.next_seq - 1

    async def compress(self, start, end):
        """压缩 self.messages[start:end]，返回压缩后的文本。"""
        old_messages = self.messages[start:end]
        compress_model = CompressModel()
        return await compress_model.generate(old_messages)

    async def checkCompact(self):
        """窗口达到上限时触发压缩。"""
        if len(self.messages) >= MAX_MESSAGES:
            await self.compact()

    # async def compact(self):
    #     """最旧的 COMPACT_COUNT 条压成 context，连同剩余消息一起追加到文件尾，然后 load。"""
    #     self.save()                               # 先落盘，未保存的消息不丢
    #     i, j = 0, COMPACT_COUNT                   # 要压缩的 message 下标范围，从 0 到 COMPACT_COUNT
    #     first = self.messages[i].seq
    #     last = self.messages[j - 1].seq
    #     text = await self.compress(i, j)
    #     context = createContextMessage(text, first, last)
    #
    #     self.messages = [context] + self.messages[j:]   # 重新覆盖messages
    #     for message in self.messages:             # 按文件时间顺序重新编号
    #         message.seq = self.next_seq
    #         self.next_seq += 1
    #     self.save()                               # 新 seq 都大于 saved_seq，整体追加

        
    async def compact(self):
        """最旧的 COMPACT_COUNT 条压成 context，连同剩余消息一起追加到文件尾。"""
        self.save()                               # 先落盘，未保存的消息不丢
        i, j = 0, COMPACT_COUNT                   # 要压缩的 message 下标范围 [i, j)

        # 切分点 j 不能落在一组工具调用中间：
        # 窗口剩余部分的第一条如果是 tool_call 或 tool 结果，说明它的同组消息被压进了摘要，
        # 所以把 j 往后挪，直到窗口剩余部分从 user 或 agent 的文字消息开始
        while j < len(self.messages) and (
            self.messages[j].type == "tool_call" or self.messages[j].role == "tool"
        ):
            j += 1

        first = self.messages[i].seq
        last = self.messages[j - 1].seq
        text = await self.compress(i, j)
        context = createContextMessage(text, first, last)

        self.messages = [context] + self.messages[j:]
        for message in self.messages:             # 按文件时间顺序重新编号
            message.seq = self.next_seq
            self.next_seq += 1
        self.save()










