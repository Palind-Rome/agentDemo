"""
主入口 —— 交互式 Agent 系统
=============================
组装所有模块，提供交互式 REPL 界面

运行方式:
  1. 复制 .env.example 为 .env，填入你的 API Key
  2. 运行:
     python main.py                   # 在 agentDemo 目录工作
     python main.py --cwd ../myproj   # 在其他目录工作

  也可以从任意位置运行:
     python D:/路径/agentDemo/main.py --cwd .
"""

import os
import sys
import argparse

# ============================================================
# 关键：确保 agentDemo 目录在 Python 模块搜索路径中
# 这样无论你从哪个目录运行 main.py，都能找到 agent.py、tool.py 等模块
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from session import Session
from agent import BUILD_AGENT, PLAN_AGENT, EXPLORE_AGENT, get_agent, list_subagents
from hook import HookManager, create_audit_plugin
from llm import LLMClient
from loop import agentic_loop, set_llm_client


def print_banner():
    print("""
╔══════════════════════════════════════════════════════╗
║               AgentDemo - Agentic Loop 演示          ║
║                                                      ║
║   基于 OpenCode 架构设计的简化 Agent 实现            ║
║   学习目的：理解 Agentic Loop 核心机制               ║
╚══════════════════════════════════════════════════════╝
""")


def print_help():
    print("""
可用命令:
  /help     - 显示帮助
  /agents   - 列出可用 Agent
  /switch   - 切换 Agent（如: /switch plan）
  /session  - 显示当前会话信息
  /new      - 开始新的会话
  /history  - 显示消息历史
  /cwd      - 显示当前工作目录
  /quit     - 退出

直接输入文字即为与 Agent 对话。
""")


def load_dotenv():
    """
    从 .env 文件加载环境变量（不依赖第三方库）

    为什么不用 python-dotenv？
    —— 减少依赖。.env 格式很简单，几行代码就能解析。

    查找顺序：
    1. agentDemo/.env（脚本所在目录）
    2. 当前工作目录/.env

    .env 文件格式：
      KEY=value
      # 这是注释
    """
    env_paths = [
        os.path.join(SCRIPT_DIR, ".env"),   # agentDemo 目录下
        os.path.join(os.getcwd(), ".env"),   # 当前工作目录下
    ]

    loaded_from = None
    for env_path in env_paths:
        if os.path.isfile(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # 跳过空行和注释
                    if not line or line.startswith("#"):
                        continue
                    # 解析 KEY=VALUE
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip()
                        # 去掉引号（如果有的话）
                        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                            value = value[1:-1]
                        # 只在环境变量未设置时才写入（不覆盖已有的）
                        if key and key not in os.environ:
                            os.environ[key] = value
            loaded_from = env_path
            break  # 只加载第一个找到的 .env

    return loaded_from


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="AgentDemo - Agentic Loop 演示")
    parser.add_argument(
        "--cwd",
        type=str,
        default=None,
        help="指定工作目录。Agent 的文件操作将在此目录下进行。"
             "例: python main.py --cwd ../myproject",
    )
    return parser.parse_args()


def main():
    """主函数"""
    # ========================================
    # 0. 解析命令行参数 + 加载 .env
    # ========================================
    args = parse_args()

    # 加载 .env 文件（在读取环境变量之前！）
    env_file = load_dotenv()

    print_banner()

    if env_file:
        print(f"✅ 已从 {env_file} 加载配置")
    else:
        print("ℹ️  未找到 .env 文件（可复制 .env.example → .env 来配置）")

    # 处理工作目录
    if args.cwd:
        work_dir = os.path.abspath(args.cwd)
        if not os.path.isdir(work_dir):
            print(f"❌ 工作目录不存在: {work_dir}")
            sys.exit(1)
        os.chdir(work_dir)
    print(f"📂 工作目录: {os.getcwd()}")

    # ========================================
    # 1. 初始化 LLM 客户端
    # 对应 OpenCode: LLM.from() 创建 LLM 实例
    # ========================================
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", None)
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

    if not api_key:
        print("\n⚠️  未设置 OPENAI_API_KEY！")
        print("   请在 .env 文件中配置，或设置环境变量。")
        print()

        api_key = input("或者现在直接输入 API Key (回车跳过): ").strip()
        if not api_key:
            print("没有 API Key，无法运行。退出。")
            sys.exit(1)

        custom_url = input("输入 API Base URL (回车使用 OpenAI 默认): ").strip()
        if custom_url:
            base_url = custom_url
        custom_model = input("输入模型名称 (回车使用 gpt-4o-mini): ").strip()
        if custom_model:
            model = custom_model

    llm_client = LLMClient(api_key=api_key, base_url=base_url, model=model)
    set_llm_client(llm_client)  # 注入到 loop 模块

    print(f"✅ LLM 已配置: model={model}")
    if base_url:
        print(f"   base_url={base_url}")

    # ========================================
    # 2. 初始化 Hook 系统
    # 对应 OpenCode: Plugin.init() 加载插件
    # ========================================
    hooks = HookManager()
    audit_plugin = create_audit_plugin()
    audit_plugin(hooks)
    print("✅ Hook 系统已初始化（审计插件已加载）")

    # ========================================
    # 3. 初始化 Agent 和 Session
    # 对应 OpenCode: AgentStore.get() + SessionStore.create()
    # ========================================
    current_agent = BUILD_AGENT  # 默认使用 build agent
    session = Session()

    print(f"✅ 当前 Agent: {current_agent.name} ({current_agent.description})")
    print(f"✅ 会话 ID: {session.id}")
    print()
    print_help()

    # ========================================
    # 4. REPL 交互循环
    # 对应 OpenCode: TUI 的用户输入处理
    # ========================================
    while True:
        try:
            user_input = input(f"\n[{current_agent.name}] > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n👋 再见!")
            break

        if not user_input:
            continue

        # 处理命令
        if user_input.startswith("/"):
            cmd = user_input.lower().split()

            if cmd[0] == "/quit":
                print("👋 再见!")
                break

            elif cmd[0] == "/help":
                print_help()

            elif cmd[0] == "/agents":
                print(f"\n可用 Agent:")
                print(f"  - build : {BUILD_AGENT.description}  [primary]")
                print(f"  - plan  : {PLAN_AGENT.description}  [primary]")
                print(f"  - explore: {EXPLORE_AGENT.description}  [subagent]")
                print(f"\n当前: {current_agent.name}")

            elif cmd[0] == "/switch":
                if len(cmd) < 2:
                    print("用法: /switch <agent名称>  (如: /switch plan)")
                else:
                    new_agent = get_agent(cmd[1])
                    if new_agent:
                        current_agent = new_agent
                        session = Session()  # 切换 Agent 时创建新会话
                        print(f"✅ 切换到 Agent: {current_agent.name}")
                        print(f"   新会话 ID: {session.id}")
                    else:
                        print(f"❌ 未知 Agent: {cmd[1]}")

            elif cmd[0] == "/session":
                print(f"\n会话信息:")
                print(f"  ID: {session.id}")
                print(f"  Agent: {current_agent.name}")
                print(f"  消息数: {len(session.messages)}")
                print(f"  父会话: {session.parent_id or '无'}")

            elif cmd[0] == "/new":
                session = Session()
                print(f"✅ 新会话已创建: {session.id}")

            elif cmd[0] == "/cwd":
                print(f"📂 当前工作目录: {os.getcwd()}")
                print(f"📦 脚本目录: {SCRIPT_DIR}")

            elif cmd[0] == "/history":
                if not session.messages:
                    print("（无消息记录）")
                else:
                    print(f"\n消息历史 ({len(session.messages)} 条):")
                    for i, msg in enumerate(session.messages):
                        role_icon = {"user": "👤", "assistant": "🤖", "tool": "🔧"}.get(msg.role, "❓")
                        content = (msg.content or "")[:80]
                        if msg.tool_calls:
                            tool_names = [tc["function"]["name"] for tc in msg.tool_calls]
                            content = f"[调用工具: {', '.join(tool_names)}]"
                        if msg.tool_call_id:
                            content = f"[{msg.name} 结果] {content}"
                        print(f"  {i+1}. {role_icon} {msg.role}: {content}")

            else:
                print(f"未知命令: {cmd[0]}，输入 /help 查看帮助")

            continue

        # ========================================
        # 用户输入 → 进入 Agentic Loop
        # 这里就是整个系统的核心入口点！
        #
        # 对应 OpenCode: SessionPrompt.prompt(userMessage)
        # 内部会进入 while(true) 循环，
        # LLM 自主决定调用工具还是返回结果
        # ========================================
        print(f"\n{'='*60}")
        print(f"📨 进入 Agentic Loop...")
        print(f"{'='*60}")

        try:
            result = agentic_loop(
                session=session,
                agent=current_agent,
                user_message=user_input,
                hook_manager=hooks,
                depth=0,
            )
            print(f"\n{'='*60}")
            print(f"📩 Agent 最终回复:")
            print(f"{'='*60}")
            print(result or "(无文本回复)")
        except Exception as e:
            print(f"\n❌ 执行出错: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
