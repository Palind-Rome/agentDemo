"""
权限系统
========
对应 OpenCode: packages/opencode/src/permission/next.ts

核心思想：
  - 每个 Agent 有一套权限规则（permissions dict）
  - 在工具执行前，检查当前 Agent 是否有权使用这个工具
  - 三种动作：allow（直接允许）、deny（直接拒绝）、ask（询问用户）
  - 通配符 "*" 匹配所有未明确指定的工具

OpenCode 的权限系统更复杂，支持通配符匹配文件路径，还支持 doom loop 检测等。
这里做简化演示。
"""


def check_permission(agent, tool_name: str) -> str:
    """
    检查 Agent 是否有权使用指定工具

    对应 OpenCode: PermissionNext.evaluate()

    返回: "allow" | "deny" | "ask"
    """
    # 先查看是否有工具名的精确匹配
    if tool_name in agent.permissions:
        return agent.permissions[tool_name]

    # 没有精确匹配，使用通配符规则
    return agent.permissions.get("*", "allow")


def ask_user_permission(tool_name: str, args: dict) -> bool:
    """
    询问用户是否允许执行工具

    对应 OpenCode: PermissionNext.ask()
    OpenCode 中这会在 TUI 上弹出确认框。
    这里简化为命令行交互。
    """
    print(f"\n  ⚠️  权限请求: 工具 '{tool_name}' 需要您的确认")
    print(f"     参数: {args}")
    response = input("     允许执行? (y/n): ").strip().lower()
    return response in ("y", "yes", "")


def enforce_permission(agent, tool_name: str, args: dict) -> bool:
    """
    执行权限检查的完整流程

    返回 True 表示允许执行，False 表示拒绝
    """
    action = check_permission(agent, tool_name)

    if action == "allow":
        return True
    elif action == "deny":
        print(f"  ❌ 权限拒绝: Agent '{agent.name}' 没有权限使用工具 '{tool_name}'")
        return False
    elif action == "ask":
        return ask_user_permission(tool_name, args)
    else:
        return False
