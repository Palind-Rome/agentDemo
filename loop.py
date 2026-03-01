"""
Agentic Loop —— 核心循环
========================
对应 OpenCode: packages/opencode/src/session/prompt.ts 的 loop() 函数

这是整个 Agent 系统最核心的部分。

核心思想：
  while True:
      1. 把历史消息 + 工具列表发送给 LLM
      2. LLM 返回响应
      3. 如果 LLM 说"我说完了"(finish_reason="stop") → break
      4. 如果 LLM 说"我要调用工具"(finish_reason="tool_calls"):
         a. 检查权限
         b. 触发 hook
         c. 执行工具
         d. 把工具结果加入消息历史
         e. continue（回到步骤 1）

  LLM 自己决定什么时候停下来。开发者不控制循环次数。
"""

import json
from session import Session, Message
from agent import Agent
from tool import get_tools_for_agent, TOOL_REGISTRY
from permission import enforce_permission
from hook import HookManager
from llm import LLMClient


# 全局 LLM 客户端（在 main.py 中初始化后注入）
_llm_client: LLMClient = None


def set_llm_client(client: LLMClient):
    """设置全局 LLM 客户端"""
    global _llm_client
    _llm_client = client


def agentic_loop(
    session: Session,
    agent: Agent,
    user_message: str,
    hook_manager: HookManager = None,
    depth: int = 0,
) -> str:
    """
    Agentic Loop 核心循环

    对应 OpenCode: SessionPrompt.loop()

    参数:
      session: 当前会话
      agent: 当前使用的 Agent 配置
      user_message: 用户输入的消息
      hook_manager: Hook 管理器（插件系统）
      depth: 嵌套深度（子 Agent 场景，用于日志缩进和安全限制）

    返回: LLM 最终的文本回复
    """
    indent = "  " * depth  # 子 Agent 的日志缩进
    hooks = hook_manager or HookManager()

    # ========================================
    # 步骤 0：准备
    # 对应 OpenCode prompt() 中创建用户消息
    # ========================================
    session.add_message(Message(role="user", content=user_message))

    # 获取当前 Agent 可用的工具
    available_tools = get_tools_for_agent(agent)
    tool_schemas = [t.to_openai_schema() for t in available_tools]
    tool_map = {t.name: t for t in available_tools}

    # 构建系统 prompt
    # 对应 OpenCode: SystemPrompt.provider() + SystemPrompt.environment()
    system_prompt = _build_system_prompt(agent)

    print(f"\n{indent}{'─'*60}")
    print(f"{indent}🤖 Agent: {agent.name} | 会话: {session.id}")
    print(f"{indent}🔧 可用工具: {[t.name for t in available_tools]}")
    print(f"{indent}{'─'*60}")

    # ========================================
    # 核心循环
    # 对应 OpenCode: prompt.ts while(true) { ... }
    # ========================================
    step = 0
    while True:
        step += 1
        print(f"\n{indent}🔄 Loop 第 {step} 轮")

        # 安全检查：防止无限循环（对应 OpenCode 的 agent.steps）
        if step > agent.max_steps:
            print(f"{indent}⚠️  达到最大步数 ({agent.max_steps})，强制退出")
            break

        # ========================================
        # 步骤 1：调用 LLM
        # 对应 OpenCode: processor.process() → LLM.stream()
        # ========================================
        print(f"{indent}  📤 发送给 LLM（{len(session.messages)} 条消息，{len(tool_schemas)} 个工具）")

        try:
            response = _llm_client.chat(
                system_prompt=system_prompt,
                messages=session.get_messages_for_llm(),
                tools=tool_schemas if tool_schemas else None,
            )
        except Exception as e:
            print(f"{indent}  ❌ LLM 调用失败: {e}")
            break

        # ========================================
        # 步骤 2：处理 LLM 响应
        # 对应 OpenCode: processor.process() 中的 for await (stream.fullStream)
        # ========================================

        # 如果有文本内容，展示给用户
        if response.content:
            print(f"{indent}  💬 LLM 回复: {response.content[:200]}{'...' if len(response.content) > 200 else ''}")

        # ========================================
        # 步骤 3：检查是否需要调用工具
        # 对应 OpenCode: finish_reason 判断
        # ========================================
        if response.finish_reason != "tool_calls" or not response.tool_calls:
            # LLM 说完了，不需要工具调用 → 退出循环
            # 对应 OpenCode: lastAssistant.finish 不是 "tool-calls" 时 break
            print(f"{indent}  ✅ LLM 完成 (finish_reason={response.finish_reason})")
            session.add_message(response)
            break

        # LLM 要调用工具 → 继续处理
        print(f"{indent}  🔧 LLM 请求调用 {len(response.tool_calls)} 个工具")
        session.add_message(response)

        # ========================================
        # 步骤 4：执行工具调用
        # 对应 OpenCode: processor.ts 中的 tool-call / tool-result 事件处理
        # ========================================
        for tool_call in response.tool_calls:
            tc_id = tool_call["id"]
            func = tool_call["function"]
            tool_name = func["name"]

            # 解析参数
            try:
                args = json.loads(func["arguments"])
            except json.JSONDecodeError:
                args = {}

            print(f"{indent}  🔧 调用工具: {tool_name}({json.dumps(args, ensure_ascii=False)[:100]})")

            # ---- 4a. 权限检查 ----
            # 对应 OpenCode: PermissionNext.ask()
            if not enforce_permission(agent, tool_name, args):
                tool_result = f"权限被拒绝：Agent '{agent.name}' 没有权限执行 '{tool_name}'"
                session.add_message(Message(
                    role="tool",
                    tool_call_id=tc_id,
                    content=tool_result,
                    name=tool_name,
                ))
                continue

            # ---- 4b. 触发 hook: tool.execute.before ----
            hook_output = {"args": args}
            hooks.trigger("tool.execute.before", {"tool": tool_name, "session_id": session.id}, hook_output)
            args = hook_output["args"]  # 插件可能修改了参数

            # ---- 4c. 执行工具 ----
            tool = tool_map.get(tool_name)
            if not tool:
                tool_result = f"错误：工具 '{tool_name}' 不存在"
            else:
                try:
                    # 构建工具执行上下文
                    context = {
                        "session_id": session.id,
                        "agent_name": agent.name,
                        "cwd": ".",
                        "hook_manager": hooks,
                        "depth": depth,
                    }
                    tool_result = tool.execute(args, context)
                except Exception as e:
                    tool_result = f"工具执行错误: {e}"

            # ---- 4d. 触发 hook: tool.execute.after ----
            hook_output = {"result": tool_result}
            hooks.trigger("tool.execute.after", {"tool": tool_name, "session_id": session.id}, hook_output)
            tool_result = hook_output["result"]  # 插件可能修改了结果

            # 展示工具结果
            preview = tool_result[:150] + "..." if len(tool_result) > 150 else tool_result
            print(f"{indent}  📥 工具结果: {preview}")

            # ---- 4e. 把工具结果加入消息历史 ----
            session.add_message(Message(
                role="tool",
                tool_call_id=tc_id,
                content=tool_result,
                name=tool_name,
            ))

        # continue → 回到 while True 开头，把工具结果发给 LLM
        # 对应 OpenCode: loop 中的 continue

    # ========================================
    # 循环结束，返回 LLM 最后的文本回复
    # 对应 OpenCode: loop 结束后 return item
    # ========================================
    return session.last_assistant_text()


def _build_system_prompt(agent: Agent) -> str:
    """
    构建系统 prompt

    对应 OpenCode:
      - SystemPrompt.provider()  → Agent 人设
      - SystemPrompt.environment() → 环境信息
      - InstructionPrompt.system() → 额外指令
    """
    import os
    import datetime

    env_info = (
        f"\n当前环境信息:\n"
        f"- 工作目录: {os.getcwd()}\n"
        f"- 操作系统: {os.name}\n"
        f"- 日期: {datetime.date.today()}\n"
    )

    return agent.system_prompt + env_info
