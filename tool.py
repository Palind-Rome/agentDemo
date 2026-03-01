"""
工具系统
========
对应 OpenCode: packages/opencode/src/tool/tool.ts + registry.ts + 各工具文件

核心思想：
  - 每个工具有三个要素：description（给 LLM 看）、parameters（JSON Schema）、execute（执行逻辑）
  - 工具的 description 让 LLM 知道什么时候该用这个工具
  - 工具的 execute 返回纯文本结果，因为 LLM 只能理解文本
  - 工具通过注册表统一管理，根据 Agent 的权限动态筛选
"""

import os
import json
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolParameter:
    """工具参数定义（简化版 JSON Schema）"""
    name: str
    type: str            # "string", "integer", "boolean"
    description: str
    required: bool = True


@dataclass
class Tool:
    """
    工具定义
    对应 OpenCode 的 Tool.define()
    """
    name: str
    description: str                     # 给 LLM 看的描述，让它知道什么时候用这个工具
    parameters: list[ToolParameter]      # 参数定义
    execute_fn: Callable                 # 执行函数

    def execute(self, args: dict, context: dict) -> str:
        """执行工具，返回文本结果"""
        return self.execute_fn(args, context)

    def to_openai_schema(self) -> dict:
        """转换为 OpenAI function calling 格式"""
        properties = {}
        required = []
        for param in self.parameters:
            properties[param.name] = {
                "type": param.type,
                "description": param.description,
            }
            if param.required:
                required.append(param.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


# ============================================================
# 内置工具实现
# 对应 OpenCode 的 tool/read.ts, tool/write.ts, tool/bash.ts 等
# ============================================================

def _read_file(args: dict, context: dict) -> str:
    """读取文件内容"""
    file_path = args["file_path"]
    # 安全检查：不允许离开工作目录（简化版）
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        return f"错误：文件 '{file_path}' 不存在"
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
        return f"文件内容 ({file_path}):\n{content}"
    except Exception as e:
        return f"读取失败: {e}"


def _write_file(args: dict, context: dict) -> str:
    """写入/创建文件"""
    file_path = args["file_path"]
    content = args["content"]
    abs_path = os.path.abspath(file_path)
    try:
        dir_name = os.path.dirname(abs_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"成功写入文件: {file_path}"
    except Exception as e:
        return f"写入失败: {e}"


def _list_dir(args: dict, context: dict) -> str:
    """列出目录内容"""
    dir_path = args.get("dir_path", ".")
    abs_path = os.path.abspath(dir_path)
    if not os.path.isdir(abs_path):
        return f"错误：'{dir_path}' 不是一个目录"
    try:
        entries = os.listdir(abs_path)
        result = []
        for entry in sorted(entries):
            full = os.path.join(abs_path, entry)
            prefix = "📁 " if os.path.isdir(full) else "📄 "
            result.append(f"{prefix}{entry}")
        return f"目录 {dir_path} 的内容:\n" + "\n".join(result)
    except Exception as e:
        return f"列目录失败: {e}"


def _bash(args: dict, context: dict) -> str:
    """执行 shell 命令"""
    command = args["command"]
    timeout = args.get("timeout", 30)
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=context.get("cwd", "."),
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if result.returncode != 0:
            output += f"\n[退出码: {result.returncode}]"
        return output.strip() or "(无输出)"
    except subprocess.TimeoutExpired:
        return f"命令超时（{timeout}秒）"
    except Exception as e:
        return f"执行失败: {e}"


def _task(args: dict, context: dict) -> str:
    """
    调用子 Agent —— 最重要的工具！
    对应 OpenCode: tool/task.ts

    设计要点：
    1. 创建一个全新的子会话
    2. 在子会话中启动一个全新的 loop（不是压入 tasks 等下一轮）
    3. 子 Agent 的 task 工具被禁用（防止无限嵌套）
    4. 子 loop 完成后，把结果作为文本返回给父 loop 的 LLM
    """
    # 延迟导入，避免循环依赖（loop → tool → task → loop）
    from loop import agentic_loop
    from session import Session
    from agent import get_agent

    subagent_name = args["subagent_type"]
    prompt = args["prompt"]
    description = args.get("description", "子任务")

    # ① 获取子 Agent 配置
    subagent = get_agent(subagent_name)
    if subagent.mode != "subagent":
        return f"错误：'{subagent_name}' 不是子 Agent，不能通过 task 调用"

    # ② 创建子会话（独立的消息历史）
    parent_session_id = context.get("session_id", "unknown")
    child_session = Session(parent_id=parent_session_id)

    print(f"\n  {'='*50}")
    print(f"  🔀 启动子 Agent: {subagent.name}")
    print(f"  📝 任务: {description}")
    print(f"  📦 子会话: {child_session.id}")
    print(f"  {'='*50}")

    # ③ 在子会话中启动全新的 loop（★ 这是关键！不是等下一轮！）
    result = agentic_loop(
        session=child_session,
        agent=subagent,
        user_message=prompt,
        hook_manager=context.get("hook_manager"),
        depth=context.get("depth", 0) + 1,  # 嵌套深度 +1
    )

    print(f"\n  {'='*50}")
    print(f"  ✅ 子 Agent '{subagent.name}' 完成")
    print(f"  {'='*50}\n")

    # ④ 把子 Agent 的最终文本回复打包返回
    return (
        f"task_id: {child_session.id}\n\n"
        f"<task_result>\n{result}\n</task_result>"
    )


# ============================================================
# 工具注册表
# 对应 OpenCode: tool/registry.ts
# ============================================================

# 所有可用的工具
TOOL_REGISTRY: dict[str, Tool] = {}


def register_tool(tool: Tool):
    """注册一个工具"""
    TOOL_REGISTRY[tool.name] = tool


def get_tools_for_agent(agent) -> list[Tool]:
    """
    根据 Agent 的权限配置，返回该 Agent 可用的工具列表
    对应 OpenCode: ToolRegistry.tools() + LLM.resolveTools()

    权限规则：
    - "allow" → 包含这个工具
    - "deny"  → 移除这个工具
    - "*" 是通配符，匹配所有未明确指定的工具
    """
    tools = []
    default_action = agent.permissions.get("*", "allow")

    for name, tool in TOOL_REGISTRY.items():
        action = agent.permissions.get(name, default_action)
        if action == "allow":
            tools.append(tool)
        # "deny" 的工具直接跳过，不会出现在 LLM 的工具列表中
    return tools


# ============================================================
# 注册所有内置工具
# ============================================================

register_tool(Tool(
    name="read_file",
    description="读取指定文件的内容。当你需要查看代码或文件时使用。",
    parameters=[
        ToolParameter("file_path", "string", "要读取的文件路径"),
    ],
    execute_fn=_read_file,
))

register_tool(Tool(
    name="write_file",
    description="创建或覆盖写入一个文件。当你需要创建新文件或修改文件时使用。",
    parameters=[
        ToolParameter("file_path", "string", "要写入的文件路径"),
        ToolParameter("content", "string", "要写入的完整文件内容"),
    ],
    execute_fn=_write_file,
))

register_tool(Tool(
    name="list_dir",
    description="列出目录中的文件和子目录。用于了解项目结构。",
    parameters=[
        ToolParameter("dir_path", "string", "要列出的目录路径，默认为当前目录", required=False),
    ],
    execute_fn=_list_dir,
))

register_tool(Tool(
    name="bash",
    description="执行 shell 命令。用于运行程序、安装依赖、搜索文件等。",
    parameters=[
        ToolParameter("command", "string", "要执行的 shell 命令"),
        ToolParameter("timeout", "integer", "超时时间（秒），默认30", required=False),
    ],
    execute_fn=_bash,
))

register_tool(Tool(
    name="task",
    description=(
        "启动子 Agent 来处理复杂的子任务。子 Agent 在独立的会话中运行，完成后返回结果。\n"
        "可用的子 Agent:\n"
        "- explore: 代码探索专家。用于搜索文件、查找代码、分析项目结构。\n"
        "\n"
        "使用场景：\n"
        "- 需要大量搜索/探索时，用 explore\n"
        "- 不要用于简单的单文件读取（直接用 read_file 更快）"
    ),
    parameters=[
        ToolParameter("subagent_type", "string", "子 Agent 名称，如 'explore'"),
        ToolParameter("prompt", "string", "给子 Agent 的详细任务描述"),
        ToolParameter("description", "string", "子任务的简短描述（3-5个字）", required=False),
    ],
    execute_fn=_task,
))
