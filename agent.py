"""
Agent 定义模块
=============
对应 OpenCode: packages/opencode/src/agent/agent.ts

核心思想：Agent = 配置，不是代码。
Agent 本身不包含"智能逻辑"，它只是一个声明式的配置对象，定义了：
  - 名称和描述
  - 角色模式（primary / subagent）
  - 权限规则（允许/禁止哪些工具）
  - 系统提示词（system prompt）

真正的"智能"来自 LLM，Agent 定义的是 LLM 的"角色边界"。
"""

from dataclasses import dataclass, field


@dataclass
class Agent:
    """一个 Agent 就是一份配置"""
    name: str                                         # Agent 名称
    description: str                                  # 描述（给用户看）
    mode: str                                         # "primary"（用户直接交互）或 "subagent"（被其他 Agent 调用）
    system_prompt: str = ""                           # 自定义系统提示词
    permissions: dict = field(default_factory=dict)   # 权限规则: { "工具名": "allow" | "deny" | "ask" }
    max_steps: int = 50                               # 最大循环步数（防止无限循环）


# ============================================================
# 内置 Agent 定义
# 对应 OpenCode 中 agent.ts 里定义的 build, plan, explore 等
# ============================================================

# 默认全能 Agent（对应 OpenCode 的 build）
BUILD_AGENT = Agent(
    name="build",
    description="默认开发 Agent，拥有完整工具权限。可以读写文件、执行命令、调用子 Agent。",
    mode="primary",
    system_prompt=(
        "你是一个专业的编程助手。你可以使用提供的工具来帮助用户完成软件开发任务。\n"
        "规则:\n"
        "- 使用工具完成任务，不要猜测文件内容\n"
        "- 先理解需求，再动手实现\n"
        "- 如果任务复杂，可以使用 task 工具调用子 Agent 来帮忙\n"
        "- 完成任务后简洁地告诉用户结果\n"
    ),
    permissions={
        "*": "allow",          # 默认允许所有工具
        "task": "allow",       # 允许调用子 Agent
    },
)

# 只读分析 Agent（对应 OpenCode 的 plan）
PLAN_AGENT = Agent(
    name="plan",
    description="只读分析 Agent，禁止编辑文件。适合探索和理解代码。",
    mode="primary",
    system_prompt=(
        "你是一个代码分析助手。你只能读取和分析代码，不能修改任何文件。\n"
        "规则:\n"
        "- 只使用读取类工具（read_file, list_dir, bash）\n"
        "- 不要尝试使用 write_file 工具\n"
        "- 给出详细的分析和建议\n"
    ),
    permissions={
        "*": "allow",
        "write_file": "deny",  # ★ 禁止写文件
        "task": "deny",        # 禁止调用子 Agent
    },
)

# 代码探索子 Agent（对应 OpenCode 的 explore）
EXPLORE_AGENT = Agent(
    name="explore",
    description="代码探索专用子 Agent。只有搜索和读取工具，适合快速查找文件和代码。",
    mode="subagent",
    system_prompt=(
        "你是一个代码搜索专家。你的任务是高效地查找文件和代码内容。\n"
        "规则:\n"
        "- 只使用 read_file, list_dir, bash(仅用于 grep/find 等搜索命令)\n"
        "- 不要修改任何文件\n"
        "- 返回清晰的搜索结果\n"
    ),
    permissions={
        "*": "deny",           # 默认禁止所有
        "read_file": "allow",  # 只允许读取
        "list_dir": "allow",   # 只允许列目录
        "bash": "allow",       # 允许 bash（但实际只应搜索）
        "task": "deny",        # ★ 禁止再调用子 Agent（防止无限嵌套）
    },
)


# Agent 注册表：所有可用的 Agent
AGENTS: dict[str, Agent] = {
    "build": BUILD_AGENT,
    "plan": PLAN_AGENT,
    "explore": EXPLORE_AGENT,
}


def get_agent(name: str) -> Agent:
    """获取 Agent 配置"""
    if name not in AGENTS:
        raise ValueError(f"Agent '{name}' 不存在。可用: {list(AGENTS.keys())}")
    return AGENTS[name]


def list_subagents() -> list[Agent]:
    """列出所有子 Agent（给 task 工具用）"""
    return [a for a in AGENTS.values() if a.mode == "subagent"]
