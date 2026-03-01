"""
会话管理
========
对应 OpenCode: packages/opencode/src/session/

核心思想：
  - Session 是一次完整的对话，包含多条 Message
  - Message 有角色（user / assistant / tool）
  - 父子会话：子 Agent 的 task 工具会创建子会话，通过 parent_id 关联
  - 每次 loop 迭代都从 Session 的消息列表读取状态（消息即状态）

在 OpenCode 中，消息存储在 SQLite 数据库里（进程重启也不丢失）。
这里为了简化，直接存在内存中。
"""

import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Message:
    """
    一条消息
    对应 OpenCode 的 MessageV2 + Part

    OpenCode 中一条 Message 可以有多个 Part（text, tool, reasoning 等），
    这里简化为单条消息。
    """
    role: str               # "user" | "assistant" | "tool"
    content: str = ""       # 文本内容
    tool_calls: list = field(default_factory=list)   # assistant 消息中的工具调用
    tool_call_id: str = ""  # tool 消息对应的工具调用 ID
    name: str = ""          # tool 消息的工具名称
    finish_reason: str = "" # "stop" | "tool_calls" | ""


@dataclass
class Session:
    """
    会话
    对应 OpenCode 的 Session

    每个 Session 有独立的消息历史。
    子 Agent 通过 task 工具创建的子会话，有独立的 Session 实例。
    """
    id: str = field(default_factory=lambda: f"sess_{uuid.uuid4().hex[:8]}")
    parent_id: Optional[str] = None   # 父会话 ID（子 Agent 场景）
    messages: list[Message] = field(default_factory=list)
    title: str = ""

    def add_message(self, message: Message):
        """添加一条消息"""
        self.messages.append(message)

    def get_messages_for_llm(self) -> list[dict]:
        """
        将消息转换为 OpenAI API 格式
        对应 OpenCode: MessageV2.toModelMessages()
        """
        result = []
        for msg in self.messages:
            if msg.role == "user":
                result.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                entry = {"role": "assistant"}
                if msg.content:
                    entry["content"] = msg.content
                if msg.tool_calls:
                    entry["tool_calls"] = msg.tool_calls
                result.append(entry)
            elif msg.role == "tool":
                result.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content,
                })
        return result

    def last_assistant(self) -> Optional[Message]:
        """找到最后一条 assistant 消息"""
        for msg in reversed(self.messages):
            if msg.role == "assistant":
                return msg
        return None

    def last_assistant_text(self) -> str:
        """获取最后一条 assistant 消息的文本内容"""
        msg = self.last_assistant()
        if msg and msg.content:
            return msg.content
        return ""
