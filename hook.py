"""
Hook 插件系统
=============
对应 OpenCode: packages/opencode/src/plugin/index.ts

核心思想：
  Hook 就是一个"函数数组"，在特定时刻遍历调用。

  核心代码在关键位置预留"插槽"（hook 点），外部插件可以往插槽里
  注册自己的处理函数。当代码执行到 hook 点时，遍历调用所有注册的函数。

  两个参数：
  - input（只读上下文）：告诉插件"现在什么情况"
  - output（可修改数据）：插件可以修改这个数据来影响后续行为

实现原理：
  1. HookManager 维护一个 dict: { "hook名称": [回调函数列表] }
  2. register() 往指定 hook 名称下追加回调函数
  3. trigger() 遍历该 hook 名称下的所有回调函数，逐个调用
  4. 每个回调函数可以修改 output（因为 dict 是引用传递）
"""

from typing import Any, Callable


class HookManager:
    """
    Hook 管理器
    对应 OpenCode: Plugin.trigger()
    """
    def __init__(self):
        # { "hook名称": [回调函数, 回调函数, ...] }
        self._hooks: dict[str, list[Callable]] = {}

    def register(self, hook_name: str, callback: Callable):
        """
        注册一个 hook 回调

        参数:
          hook_name: hook 名称，如 "tool.execute.before"
          callback: 回调函数，签名为 callback(input: dict, output: dict)
        """
        if hook_name not in self._hooks:
            self._hooks[hook_name] = []
        self._hooks[hook_name].append(callback)

    def trigger(self, hook_name: str, input_data: dict, output_data: dict) -> dict:
        """
        触发一个 hook

        对应 OpenCode: Plugin.trigger(name, input, output)

        遍历所有注册到 hook_name 的回调函数，逐个调用。
        每个回调可以修改 output_data（引用传递）。

        参数:
          hook_name: hook 名称
          input_data: 只读上下文（告诉插件现在什么情况）
          output_data: 可修改数据（插件通过修改它来影响行为）

        返回: 可能被修改后的 output_data
        """
        callbacks = self._hooks.get(hook_name, [])
        for callback in callbacks:
            callback(input_data, output_data)
        return output_data


# ============================================================
# 示例插件：安全审计
# ============================================================

def create_audit_plugin():
    """
    创建一个安全审计插件
    记录所有工具的调用

    返回一个函数，接受 HookManager 并注册 hook 回调。
    对应 OpenCode 中插件的 init(hooks) 模式。
    """
    log = []

    def on_tool_before(input_data: dict, output_data: dict):
        tool_name = input_data.get("tool", "unknown")
        args = output_data.get("args", {})
        entry = f"[审计] 工具 '{tool_name}' 即将执行，参数: {args}"
        log.append(entry)
        print(f"  🔍 {entry}")

    def on_tool_after(input_data: dict, output_data: dict):
        tool_name = input_data.get("tool", "unknown")
        result = output_data.get("result", "")
        preview = result[:100] + "..." if len(result) > 100 else result
        entry = f"[审计] 工具 '{tool_name}' 执行完成，结果: {preview}"
        log.append(entry)

    def register(hooks: 'HookManager'):
        """将审计插件注册到 HookManager"""
        hooks.register("tool.execute.before", on_tool_before)
        hooks.register("tool.execute.after", on_tool_after)

    return register
