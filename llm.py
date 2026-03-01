"""
LLM 调用抽象层
==============
对应 OpenCode: packages/opencode/src/session/llm.ts + provider/provider.ts

核心思想：
  - 封装 LLM API 调用，支持工具调用（function calling）
  - 模型无关：通过 OpenAI 兼容接口，可对接任何提供商
  - 构建 system prompt + 历史消息 + 工具定义 → 发送给 LLM

支持的提供商（只要兼容 OpenAI 接口）：
  - OpenAI (gpt-4o, gpt-4o-mini, ...)
  - DeepSeek (deepseek-chat, deepseek-reasoner)
  - Ollama 本地模型 (qwen2.5, llama3, ...)
  - 其他兼容 OpenAI 的服务
"""

import os
import json
from openai import OpenAI
from session import Message


# 默认配置，可通过环境变量覆盖
DEFAULT_CONFIG = {
    "api_key": os.environ.get("OPENAI_API_KEY", ""),
    "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    "model": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
}


class LLMClient:
    """
    LLM 客户端
    对应 OpenCode: LLM.stream() + Provider.getLanguage()
    """
    def __init__(self, api_key: str = "", base_url: str = "", model: str = ""):
        self.api_key = api_key or DEFAULT_CONFIG["api_key"]
        self.base_url = base_url or DEFAULT_CONFIG["base_url"]
        self.model = model or DEFAULT_CONFIG["model"]

        if not self.api_key:
            raise ValueError(
                "未设置 API Key。请设置环境变量 OPENAI_API_KEY，\n"
                "或使用 Ollama 本地模型（设置 OPENAI_BASE_URL=http://localhost:11434/v1 "
                "和 OPENAI_API_KEY=ollama）"
            )

        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def chat(self, system_prompt: str, messages: list[dict], tools: list[dict] = None) -> Message:
        """
        调用 LLM，返回 assistant 消息

        对应 OpenCode: LLM.stream() 中调用 streamText()
        OpenCode 使用流式响应，这里简化为非流式。

        参数:
          system_prompt: Agent 的系统提示词 + 环境信息
          messages: 历史消息列表（OpenAI 格式）
          tools: 工具定义列表（OpenAI function calling 格式）

        返回: Message 对象
        """
        # 构建请求
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        kwargs = {
            "model": self.model,
            "messages": full_messages,
        }

        # 只有在有工具时才传 tools 参数
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        # 调用 API
        response = self.client.chat.completions.create(**kwargs)

        # 解析响应
        choice = response.choices[0]
        msg = choice.message

        # 构建 Message
        result = Message(role="assistant")
        result.content = msg.content or ""
        result.finish_reason = choice.finish_reason or ""

        # 处理工具调用
        if msg.tool_calls:
            result.tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
            result.finish_reason = "tool_calls"

        return result
