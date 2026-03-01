# AgentDemo —— 基于 OpenCode 架构的简化 Agent 实现

> 学习目的：通过 Python 实现一个简化版的 Agentic Loop，理解 OpenCode 中 Agent 系统的核心设计思想。

## 架构总览

```
用户输入
   │
   ▼
┌─────────┐     ┌──────────┐     ┌──────────┐
│ main.py │────▶│ loop.py  │────▶│ llm.py   │
│ (入口)   │     │(核心循环) │     │(LLM调用)  │
└─────────┘     └──────────┘     └──────────┘
                     │  ▲
              工具调用│  │工具结果
                     ▼  │
                ┌──────────┐
                │ tool.py  │
                │(工具系统)  │
                └──────────┘
                     │
         ┌───────────┼───────────┐
         ▼           ▼           ▼
    permission.py  hook.py   agent.py
    (权限检查)     (钩子/插件) (Agent配置)
```

## 文件说明 & 对应 OpenCode 源码

| 文件 | 功能 | 对应 OpenCode |
|------|------|---------------|
| `agent.py` | Agent 定义（配置，不是代码逻辑） | `packages/opencode/src/agent/agent.ts` |
| `tool.py` | 工具基类 + 注册表 + 内置工具 | `packages/opencode/src/tool/tool.ts` + `registry.ts` |
| `session.py` | 会话和消息管理 | `packages/opencode/src/session/` |
| `permission.py` | 权限系统（allow/deny/ask） | `packages/opencode/src/permission/next.ts` |
| `hook.py` | Hook 插件系统（扩展点） | `packages/opencode/src/plugin/index.ts` |
| `llm.py` | LLM API 调用封装 | `packages/opencode/src/session/llm.ts` |
| `loop.py` | **Agentic Loop 核心循环** | `packages/opencode/src/session/prompt.ts` 的 `loop()` |
| `main.py` | 入口 + 交互式 REPL | TUI 入口 |

## 核心设计思想

### 1. Agent = 配置，不是代码
```python
# agent.py - Agent 只是一份声明式配置
BUILD_AGENT = Agent(
    name="build",
    permissions={"write_file": "ask", "bash": "ask"},  # 权限声明
    system_prompt="你是一个全能编程助手...",
)
```
智能不在 Agent 代码里，而是通过 system_prompt 告诉 LLM 该怎么做。

### 2. Agentic Loop —— LLM 自己决定何时停止
```python
# loop.py - 核心 5 行伪代码
while True:
    response = LLM(messages, tools)
    if response.finish_reason == "stop":
        break  # LLM 说"我说完了"
    for tool_call in response.tool_calls:
        result = execute_tool(tool_call)
        messages.append(tool_result)
    # continue → 把工具结果再发给 LLM
```

### 3. Task Tool —— Agent 中的 Agent
```python
# tool.py 中的 task 工具
def _task(args, context):
    child_session = Session(parent_id=context["session_id"])
    return agentic_loop(child_session, subagent, args["prompt"])
    # ↑ 开启全新循环，不是 push 到任务队列！
```

### 4. 权限系统 —— 每个工具独立控制
```
Agent.permissions = {
    "write_file": "ask",   # 每次都问用户
    "bash": "ask",         # 危险操作需确认
    "read_file": "allow",  # 自动放行
    "*": "allow",          # 默认放行
}
```

### 5. Hook 插件系统 —— 不改代码就能扩展
```python
hooks.register("tool.execute.before", lambda inp, out: print(f"即将执行: {inp}"))
hooks.register("tool.execute.after", lambda inp, out: log_to_file(out))
```

## 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 配置 API（.env 文件，一次配好永久生效）

```bash
# 复制模板
copy .env.example .env       # Windows
cp .env.example .env          # Linux/Mac

# 然后编辑 .env，填入你的 API Key
```

**.env 文件示例:**

```env
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
OPENAI_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

### 3. 运行
```bash
# 在 agentDemo 目录下工作
python main.py

# 在其他目录工作（比如你的项目目录）
python 某目录 --cwd .

# 或者用相对路径
python ../main.py --cwd .
```

> **`--cwd` 参数说明：**
> Agent 的文件读写、命令执行都在这个目录下进行。
> 不指定则默认在运行命令时的当前目录。

### 4. 示例对话
```
[build] > 创建一个输出hello world的python程序。

============================================================
📨 进入 Agentic Loop...
============================================================

────────────────────────────────────────────────────────────
🤖 Agent: build |
🔧 可用工具: ['read_file', 'write_file', 'list_dir', 'bash', 'task']
────────────────────────────────────────────────────────────

🔄 Loop 第 1 轮
  📤 发送给 LLM（1 条消息，5 个工具）
  💬 LLM 回复: 我将为您创建一个输出 "hello world" 的 Python 程序。首先来看看当前目录结构，然后创建文件。


  🔧 LLM 请求调用 1 个工具
  🔧 调用工具: list_dir({})
  🔍 [审计] 工具 'list_dir' 即将执行，参数: {}
  📥 工具结果: 目录 . 的内容:


🔄 Loop 第 2 轮
  📤 发送给 LLM（3 条消息，5 个工具）
  💬 LLM 回复: 当前目录是空的。现在我来创建一个输出 "hello world" 的 Python 程序文件。


  🔧 LLM 请求调用 1 个工具
  🔧 调用工具: write_file({"file_path": "hello_world.py", "content": "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n\n\"\"\)
  🔍 [审计] 工具 'write_file' 即将执行，参数: {'file_path': 'hello_world.py', 'content': '#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n\n"""\n这是一个简单的Python程序，用于输出hello world\n"""\n\ndef main():\n    """主函数"""\n    # 输出hello world\n    print("hello world")\n    return 0\n\nif __name__ == "__main__":\n    # 调用主函数\n    main()'}
  📥 工具结果: 成功写入文件: hello_world.py

🔄 Loop 第 3 轮
  📤 发送给 LLM（5 条消息，5 个工具）
  💬 LLM 回复: 现在让我验证一下文件是否创建成功，以及是否能正确运行。




  🔧 LLM 请求调用 1 个工具
  🔧 调用工具: read_file({"file_path": "hello_world.py"})
  🔍 [审计] 工具 'read_file' 即将执行，参数: {'file_path': 'hello_world.py'}
  📥 工具结果: 文件内容 (hello_world.py):
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
这是一个简单的Python程序，用于输出hello world
"""

def main():
    """主函数"""
    # 输出hell...

🔄 Loop 第 4 轮
  📤 发送给 LLM（7 条消息，5 个工具）
  💬 LLM 回复: 现在让我运行这个Python程序来验证它是否能正确输出"hello world"。




  🔧 LLM 请求调用 1 个工具
  🔧 调用工具: bash({"command": "python hello_world.py"})
  🔍 [审计] 工具 'bash' 即将执行，参数: {'command': 'python hello_world.py'}
  📥 工具结果: hello world

🔄 Loop 第 5 轮
  📤 发送给 LLM（9 条消息，5 个工具）
  💬 LLM 回复: 完成！我已经成功创建了一个输出 "hello world" 的 Python 程序。

**结果总结：**
1. 创建了 `hello_world.py` 文件，包含完整的Python程序代码
2. 程序使用了良好的代码结构，包含文档字符串和明确的main函数
3. 程序已成功验证可以正确输出 "hello world"
4. 您可以随时运行 `python hello_world.py` 来查看...
  ✅ LLM 完成 (finish_reason=stop)

============================================================
📩 Agent 最终回复:
============================================================
完成！我已经成功创建了一个输出 "hello world" 的 Python 程序。

**结果总结：**
1. 创建了 `hello_world.py` 文件，包含完整的Python程序代码
2. 程序使用了良好的代码结构，包含文档字符串和明确的main函数
3. 程序已成功验证可以正确输出 "hello world"
4. 您可以随时运行 `python hello_world.py` 来查看结果

程序特点：
- 使用 `#!/usr/bin/env python3` 作为shebang行，支持跨平台运行
- 包含UTF-8编码声明（`# -*- coding: utf-8 -*-`）
- 有详细的文档字符串说明
- 使用 `if __name__ == "__main__":` 结构，既可直接运行也可作为模块导入
```

## REPL 命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/agents` | 列出所有 Agent |
| `/switch plan` | 切换到 plan Agent |
| `/session` | 显示会话信息 |
| `/new` | 创建新会话 |
| `/history` | 查看消息历史 |
| `/quit` | 退出 |

## 学习路线

建议按以下顺序阅读源码：

1. **`agent.py`** → 理解"Agent = 配置"
2. **`tool.py`** → 理解工具系统和注册表
3. **`session.py`** → 理解消息如何组织
4. **`llm.py`** → 理解 LLM 调用
5. **`loop.py`** → **最核心！** 理解 Agentic Loop
6. **`permission.py`** → 理解安全机制
7. **`hook.py`** → 理解插件扩展
8. **`main.py`** → 理解如何把所有模块组装起来
