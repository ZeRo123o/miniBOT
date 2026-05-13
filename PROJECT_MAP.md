# miniBOT 项目导航地图

本文档用于快速定位 miniBOT 的目录、入口、数据流和常见修改位置。开发规范请看 [AGENTS.md](AGENTS.md)。

## 1. 总览

miniBOT 是一个前后端分离的模块化助手脚手架。

```text
miniBOT
|-- backend/              FastAPI 后端
|-- frontend/             Vue 3 + Vite 前端
|-- docker-compose.yml    PostgreSQL 开发依赖
|-- README.md             项目说明
|-- AGENTS.md             agent 开发规范
`-- PROJECT_MAP.md        项目导航地图
```

核心链路：

```text
前端发送消息
  -> POST /api/chat
  -> AgentRuntime
  -> 保存 user message
  -> 读取历史消息和资源选择
  -> 解析 MCP / Skill / Subagent
  -> 创建 AgentContext
  -> create_agent + middleware 动态构建提示词
  -> dynamic_tool_call 按需加载运行时工具
  -> chat_model
  -> 保存 assistant message
  -> 前端刷新当前会话
```

## 2. 后端地图

```text
backend/app
|-- main.py                  FastAPI app、CORS、lifespan、路由挂载
|-- schemas.py               通用请求/响应 Pydantic schema
|-- agent/
|   |-- context.py           AgentContext 运行时上下文
|   `-- runtime.py           一次 Agent 对话运行的编排入口
|-- core/
|   `-- config.py            环境变量与默认配置
|-- api/
|   |-- router.py            /api 路由聚合
|   `-- routes/
|       |-- health.py
|       |-- resources.py
|       |-- selections.py
|       |-- conversations.py
|       `-- chat.py
|-- db/
|   |-- session.py           async engine、session、create_all
|   |-- models.py            SQLAlchemy 模型
|   `-- repositories.py      数据访问层
|-- graph/
|   |-- builder.py           create_agent 构建入口
|   |-- prompt.py            系统提示词和资源上下文组装
|   `-- middleware/          LangChain AgentMiddleware
|-- llm/
|   |-- base.py              BaseChatModel 别名
|   |-- chat_model.py        OpenAI-compatible / mock ChatModel
|   `-- factory.py           chat_model / deep_research_model 工厂
|-- tools/
|   |-- factory.py           动态工具路由 LangChain tools
|   |-- registry.py          运行时工具注册和调度
|   `-- tavily.py            Tavily Search 工具实现
`-- plugins/
    |-- types.py             资源类型和资源 schema
    `-- registry.py          内置资源种子数据与名称解析
```

## 3. 前端地图

```text
frontend
|-- package.json
|-- vite.config.js
|-- index.html
`-- src/
    |-- main.js
    |-- App.vue
    |-- styles.css
    |-- apis/
    |   |-- base.js
    |   `-- resources.js
    |-- stores/
    |   |-- selectionStore.js
    |   `-- conversationStore.js
    |-- components/
    |   |-- ChatBox.vue
    |   |-- ConversationSidebar.vue
    |   |-- MarkdownMessage.vue
    |   |-- ResourceSelector.vue
    |   `-- WorkspaceSidebar.vue
    `-- views/
        `-- HomeView.vue
```

## 4. 关键后端职责

`api/routes/chat.py` 只保留 HTTP 入口职责：

```text
接收 ChatRequest
  -> 调用 AgentRuntime.run
  -> 把 ValueError 转成 HTTPException
```

`agent/runtime.py` 负责一次完整 Agent 运行：

```text
准备会话
保存用户消息
读取历史消息
读取用户资源选择
解析资源
构建 AgentContext
调用 create_agent 生成的 agent
保存 assistant 回复
构造响应
```

`graph/builder.py` 只负责 agent 构建：

```text
选择模型用途 model_use
加载对应 BaseChatModel
挂载 AgentMiddleware
绑定 list_available_tools / dynamic_tool_call
返回 compiled agent
```

`tools/` 负责运行时动态工具：

```text
list_available_tools  列出当前允许的工具
dynamic_tool_call     按工具名称加载并执行工具
tavily_search         Tavily 网页搜索执行器
```

`graph/middleware/` 负责运行时能力：

```text
RuntimeResourceMiddleware  规范化运行时资源
SkillPromptMiddleware      根据 Skill 动态补充提示词片段
RuntimePromptMiddleware    统一生成最终 system prompt
```

`llm/` 负责模型管理：

```text
chat_model             当前聊天模型
deep_research_model    预留深度研究模型
mock                   本地开发默认模型
openai-compatible      兼容 OpenAI Chat Completions 的模型服务
```

## 5. 数据库地图

模型定义：`backend/app/db/models.py`

当前核心表：

```text
plugin_resources
user_selections
conversations
conversation_messages
```

当前没有 Alembic 迁移系统，应用启动时通过 `Base.metadata.create_all` 创建缺失表。

## 6. API 地图

```text
GET    /api/health
GET    /api/resources?kind=mcp|skill|subagent|tool
POST   /api/resources
GET    /api/selections/{user_key}
PUT    /api/selections/{user_key}
GET    /api/selections/{user_key}/resolved
GET    /api/conversations?user_key=default
POST   /api/conversations
PATCH  /api/conversations/{conversation_id}?user_key=default
DELETE /api/conversations/{conversation_id}?user_key=default
GET    /api/conversations/{conversation_id}/messages?user_key=default
POST   /api/conversations/{conversation_id}/messages?user_key=default
POST   /api/chat
```

## 7. 常见任务定位

修改聊天运行流程：
- `backend/app/agent/runtime.py`
- `backend/app/api/routes/chat.py`

修改 agent 构建和 middleware：
- `backend/app/graph/builder.py`
- `backend/app/graph/middleware/`
- `backend/app/agent/context.py`

修改提示词：
- `backend/app/graph/prompt.py`
- `backend/app/core/config.py`

修改模型接入：
- `backend/app/llm/factory.py`
- `backend/app/llm/chat_model.py`
- `.env.example`

修改运行时工具：
- `backend/app/tools/`
- `backend/app/plugins/registry.py`
- `backend/app/graph/prompt.py`

修改左侧历史对话：
- `frontend/src/components/ConversationSidebar.vue`
- `frontend/src/stores/conversationStore.js`
- `backend/app/api/routes/conversations.py`

修改中间聊天 UI：
- `frontend/src/components/ChatBox.vue`
- `frontend/src/components/MarkdownMessage.vue`
- `frontend/src/styles.css`

修改右侧工作区：
- `frontend/src/components/WorkspaceSidebar.vue`
- `frontend/src/stores/selectionStore.js`

## 8. 验证命令

前端：

```powershell
cd frontend
npm run build
```

后端：

```powershell
cd backend
.\.venv\Scripts\python.exe -m compileall app
.\.venv\Scripts\python.exe -c "from app.main import app; print(app.title)"
```
