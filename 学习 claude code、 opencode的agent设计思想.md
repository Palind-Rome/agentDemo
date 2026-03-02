> by Palind

claude code 不是开源软件，其插件和文档仓库是：[anthropics/claude-code](https://github.com/anthropics/claude-code)，暴露一些接口开发插件。

OpenCode 开源，仓库是：[anomalyco/opencode](https://github.com/anomalyco/opencode)。

LangChain 时代的 Workflow 不适用于灵活的编码任务，因为开发者预先定义 DAG、Chain，LLM在固定流程中被调用。现代的代码 Agent 关注大模型的 Tool-Use 推理和多智能体协作，LLM 自己决定下一步做什么，开发者提供工具和约束。

我克隆了 OpenCode 的仓库，其源码在 `opencode/packages/opencode` 位置，是一个基于 TypeScript、使用 Bun 作为运行时的现代后端项目，通过询问 Copilot 学习了结构。我的总结如下：

### Agent，Permission

agent 通过 `packages/opencode/src/agent/agent.ts` 配置，包括名称、描述、角色模式、Permission、最大步数等。

agent 的 能力通过 permission 控制，`packages/opencode/src/permission/next.ts` 定义权限，权限可以 merge，例如 默认权限 + Agent 专属权限 + 用户自定义权限 → 最终权限。

例子：`agent.ts` 中定义了名为 `plan` 的 agent，代码如下：

```typescript
      plan: {
        name: "plan",
        description: "Plan mode. Disallows all edit tools.",
        options: {},
        permission: PermissionNext.merge(
          defaults,
          PermissionNext.fromConfig({
            question: "allow",
            plan_exit: "allow",
            external_directory: {
              [path.join(Global.Path.data, "plans", "*")]: "allow",
            },
            edit: {
              "*": "deny",
              [path.join(".opencode", "plans", "*.md")]: "allow",
              [path.relative(Instance.worktree, path.join(Global.Path.data, path.join("plans", "*.md")))]: "allow",
            },
          }),
          user,
        ),
        mode: "primary",
        native: true,
      },
```

其 `permission: PermissionNext.merge` 部分的 `edit` 部分含义为，`"*": "deny"` 禁止所有编辑，后面两行代码为允许编辑计划文件。

### Agentic Loop

核心设计在 `packages/opencode/src/session/prompt.ts` 中的 `export const loop`。

我个人的总结如下：

| 名词              | 含义                                                         |
| ----------------- | ------------------------------------------------------------ |
| **Session**       | 一次完整对话（包含多条消息）                                 |
| **Message**       | 一条消息（user 发的，或 assistant 回的）                     |
| **Part**          | 消息的组成部分（一条 assistant 消息可能包含：文本 + 工具调用 + 推理过程等多个 part） |
| **Step**          | Loop 循环的一轮迭代                                          |
| **finish reason** | LLM 停止生成的原因：`stop`（说完了）、tool-calls（要调用工具）、length（达到 token 上限） |

`loop`的入口是 `prompt` 函数，用户发送信息，然后进入 `loop`。进入 `while` 循环前，用 start、resume、cancel 管理生命周期，因为 OpenCode 是客户端-服务端架构。多个客户端可能对同一个 session 发送消息。如果一个循环已经在运行，新的请求不会创建第二个循环，而是注册一个回调等待结果。一个 session 同一时间最多只有一个 loop 在运行。

在 loop 循环中，首先读取 session 历史消息，找到最后一条用户消息、最后一条助手消息、最后一条已完成的助手消息。

接下来根据 finish 判断是否退出循环。如果 LLM 决定可以退出循环了，就中止 loop。如果 LLM 返回 finish = "tool-calls" 就执行工具后把结果返回给 LLM，继续循环。

根据当前状态，根据优先级，会存在三条路径：

```
                 ┌─── subtask（待处理的子任务）  → 路径 A
    tasks.pop()──┤
                 ├─── compaction（待处理的压缩） → 路径 B
                 │
                 └─── 无任务 ──────────────────→ 路径 C（普通 LLM 调用）
```

如果存在待处理的子任务 subtask，执行路径 A：进行工具、assistant 消息、工具调用状态的初始化，执行任务，更新消息状态、工具调用结果，回到 loop 的开头循环继续；由于设定了 finish = "tool-calls"，下一轮循环在退出检查中不会退出。

如果要进行压缩上下文，执行路径 B，压缩上下文。压缩后，如果返回的 result 为 stop，就停止循环；如果没有待办任务，但上下文溢出了，就创建压缩任务，下一轮会走路径 B。

如果没有任务，执行路径 C：获取 agent 配置（例如，用户选择了 build 或 plan），创建 Processor 流式处理器，解析工具集，构建系统 prompt，用 \<system-reminder\> 包装循环中用户又发的信息提醒 LLM 注意消息；最后一步把这些东西输入 processor.process 调用 LLM 得到结果，根据 LLM 结果决定下一步。

loop 结束后，找到最后一条 assistant 消息，返回给用户。

在 Loop 代码里出现了 Hook 调用，例如路径 A：

```typescript
// 工具执行前 hook
await Plugin.trigger("tool.execute.before", { tool: "task", sessionID, callID }, { args: taskArgs })

// 工具执行后 hook
await Plugin.trigger("tool.execute.after", { tool: "task", sessionID, callID, args: taskArgs }, result)
```

路径 C：

```typescript
// 消息转换 hook（让插件修改发送给 LLM 的消息）
await Plugin.trigger("experimental.chat.messages.transform", {}, { messages: msgs })
```

Hook 是指是一种扩展机制。它允许外部代码在系统运行的特定时刻插入自定义逻辑，而不需要修改系统核心代码。

`tasks.pop()` 在选择 ABC 路径时进行，那里面的 task 何时输入的？用户手动输入 subagent 调用。LLM 自主调用 task 工具。后者是最常见的情况，当用户正常对话时，走的是路径 C，LLM 收到工具列表，其中就包含 task 工具。LLM 自己决定要不要调用 task 工具来启动子 Agent。 如果 LLM 调用了 task 工具，TaskTool.execute() 被调用，TaskTool.execute() 内部会创建子 Session，启动子 Agent 的 loop，子 Agent 走路径 A。为了防止无限嵌套，子 agent 的工具列表中 task 被禁用，其 permission 也明确禁止 task。

### Tool

`packages/opencode/src/tool/tool.ts` 的 `Tool.define()` 定义工具，description 让 LLM 知道什么时候该用工具，execute 实际执行逻辑结果以文本形式返回给 LLM，parameters 参数转换为 JSON Schema 给 LLM。内置工具列表在packages/opencode/src/tool/registry.ts 中注册。

例子：packages/opencode/src/tool/task.ts 的 task 工具实现了 agent 调用 agent 的逻辑，可以创建子会话、向子会话发送prompt、返回子 agent 的结果。其简化版伪代码如下：

```typescript
// task.ts 核心逻辑
const TaskTool = Tool.define("task", async (ctx) => {
  const agents = await Agent.list()
    .then(x => x.filter(a => a.mode !== "primary"))  // 只列出子 Agent
  
  return {
    parameters: z.object({
      description: z.string(),       // 任务描述
      prompt: z.string(),            // 详细提示
      subagent_type: z.string(),     // 选择哪个子 Agent
      task_id: z.string().optional() // 可选：恢复之前的任务
    }),
    async execute(params, ctx) {
      // 1. 创建子会话
      const session = await Session.create({
        parentID: ctx.sessionID,
        title: params.description,
      })
      
      // 2. 向子会话发送 prompt
      const result = await SessionPrompt.prompt({
        sessionID: session.id,
        model: model,
        agent: agent.name,  // 使用指定的子 Agent
        parts: [{ type: "text", text: params.prompt }],
      })
      
      // 3. 返回子 Agent 的结果
      return {
        output: `task_id: ${session.id}\n<task_result>${text}</task_result>`,
      }
    }
  }
})
```

### Session，即会话

会话用 SQLite 持久化存储，核心在 packages/opencode/src/session/session.sql.ts。每条消息创建后不修改，新的状态通过新的 Part 追加。子 Agent 的对话在独立会话中进行，通过 parentID 关联。数据存储在服务端，TUI/Desktop 等客户端通过 API 访问。

当对话太长，token 接近上下文窗口限制时，自动触发上下文压缩，核心逻辑在 packages/opencode/src/session/compaction.ts。其保留最近的工具调用结果，裁剪更早的，用专门的 compaction Agent 将历史对话压缩成摘要，用压缩后的上下文继续工作。

### Provider，即 LLM 供应

不绑定任何 LLM 提供商。使用 Vercel AI SDK 作为统一接口，不同模型使用不同的 system prompt，针对不同模型转换参数（温度、top_p、最大输出 token 等）。