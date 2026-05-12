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
前端选择资源
  -> 保存 user selection
  -> 用户发送消息
  -> 后端保存用户消息
  -> 读取当前会话历史消息
  -> 解析 MCP / Skill / Subagent
  -> LangGraph middleware
  -> llm provider
  -> 保存 assistant 回复
  -> 前端刷新当前会话消息
```

## 2. 后端地图

```text
backend/app
|-- main.py                 FastAPI app、CORS、lifespan、路由挂载
|-- schemas.py              通用请求/响应 Pydantic schema
|-- core/
|   `-- config.py           环境变量与默认配置
|-- api/
|   |-- router.py           /api 路由聚合
|   `-- routes/
|       |-- health.py       健康检查
|       |-- resources.py    MCP / Skill / Subagent 资源接口
|       |-- selections.py   用户资源选择接口
|       |-- conversations.py 会话和消息接口
|       `-- chat.py         聊天入口，保存消息并调用 LangGraph
|-- db/
|   |-- session.py          async engine、session、create_all
|   |-- models.py           SQLAlchemy 模型
|   `-- repositories.py     数据访问层
|-- llm/
|   |-- base.py             统一模型接口
|   |-- factory.py          根据配置创建模型 provider
|   `-- providers/
|       |-- mock.py         本地 mock provider
|       `-- openai_compatible.py OpenAI-compatible provider
|-- plugins/
|   |-- types.py            资源类型和资源 schema
|   `-- registry.py         内置资源种子数据与名称解析
`-- graph/
    |-- state.py            LangGraph state 定义
    |-- builder.py          graph 构建和 assistant 节点
    `-- middleware/         LangGraph 中间件目录
        |-- base.py
        |-- compose.py
        |-- runtime_resource.py
        `-- skill_prompt.py
```

### 后端启动入口

- 应用入口：`backend/app/main.py`
- 路由前缀：`/api`
- 启动命令：

```powershell
cd backend
uvicorn app.main:app --reload
```

### 后端配置入口

配置文件：`backend/app/core/config.py`

默认配置：

- `app_name`: `miniBOT`
- `api_prefix`: `/api`
- `database_url`: `postgresql+asyncpg://minibot:minibot@localhost:5432/minibot`
- `default_model_provider`: `mock`
- `default_model_name`: `mock`
- `openai_base_url`: `https://api.openai.com/v1`

环境变量前缀：`MINIBOT_`

## 3. 前端地图

```text
frontend
|-- package.json           npm 脚本和依赖
|-- vite.config.js         Vite 配置
|-- index.html             HTML 入口
`-- src/
    |-- main.js            Vue app mount
    |-- App.vue            根组件
    |-- styles.css         全局样式
    |-- apis/
    |   |-- base.js        fetch 封装和 API base
    |   `-- resources.js   资源、选择、会话、聊天 API
    |-- stores/
    |   |-- selectionStore.js     MCP / Skill / Subagent 选择状态
    |   `-- conversationStore.js  会话和消息状态
    |-- components/
    |   |-- ResourceSelector.vue
    |   |-- ConversationSidebar.vue
    |   `-- ChatBox.vue
    `-- views/
        `-- HomeView.vue
```

## 4. 数据库地图

模型定义：`backend/app/db/models.py`

当前表：

```text
plugin_resources
|-- id
|-- kind
|-- name
|-- display_name
|-- description
|-- enabled
|-- config
|-- created_at
`-- updated_at

user_selections
|-- id
|-- user_key
|-- mcps
|-- skills
|-- subagents
|-- created_at
`-- updated_at

conversations
|-- id
|-- user_key
|-- title
|-- archived
|-- created_at
`-- updated_at

conversation_messages
|-- id
|-- conversation_id
|-- role
|-- content
|-- metadata
`-- created_at
```

数据库初始化：

- `backend/app/db/session.py`
- 应用启动时执行 `Base.metadata.create_all`
- 当前没有 Alembic 迁移系统

## 5. API 地图

### 健康检查

```text
GET /api/health
```

### 资源接口

```text
GET  /api/resources?kind=mcp|skill|subagent
POST /api/resources
```

### 资源选择接口

```text
GET /api/selections/{user_key}
PUT /api/selections/{user_key}
GET /api/selections/{user_key}/resolved
```

### 会话接口

```text
GET    /api/conversations?user_key=default
POST   /api/conversations
PATCH  /api/conversations/{conversation_id}?user_key=default
DELETE /api/conversations/{conversation_id}?user_key=default
GET    /api/conversations/{conversation_id}/messages?user_key=default
POST   /api/conversations/{conversation_id}/messages?user_key=default
```

### 聊天接口

```text
POST /api/chat
```

请求核心字段：

```json
{
  "user_key": "default",
  "conversation_id": 1,
  "message": "你好"
}
```

`conversation_id` 可以为空；为空时后端会自动创建新会话。

## 6. 关键数据流

### 资源选择流

```text
HomeView onMounted
  -> selectionStore.loadWorkspace
  -> GET /api/resources
  -> GET /api/selections/default
  -> ResourceSelector 勾选资源
  -> persistSelection
  -> PUT /api/selections/default
```

### 会话加载流

```text
HomeView onMounted
  -> conversationStore.loadConversations
  -> GET /api/conversations?user_key=default
  -> 默认选中最新会话
  -> GET /api/conversations/{id}/messages
  -> ChatBox 展示消息
```

### 聊天发送流

```text
ChatBox submit
  -> POST /api/chat
  -> chat.py 创建/校验 conversation
  -> 保存 user message
  -> 读取当前 conversation 历史消息
  -> 读取 user selection
  -> resolve_resources_by_name
  -> build_chat_graph().ainvoke
  -> graph middleware 补充运行时上下文
  -> get_chat_model 调用 mock 或 OpenAI-compatible provider
  -> 保存 assistant message
  -> 返回 conversation + messages
  -> conversationStore.applyChatResponse
```

## 7. 常见任务定位

### 修改大模型接入

优先查看：

- `backend/app/llm/base.py`
- `backend/app/llm/factory.py`
- `backend/app/llm/providers/`
- `backend/app/core/config.py`
- `backend/app/graph/builder.py`

### 修改 LangGraph 中间件

优先查看：

- `backend/app/graph/middleware/`
- `backend/app/graph/state.py`
- `backend/app/graph/builder.py`

### 修改左侧对话历史

优先查看：

- `frontend/src/components/ConversationSidebar.vue`
- `frontend/src/stores/conversationStore.js`
- `backend/app/api/routes/conversations.py`

### 修改聊天行为

优先查看：

- `frontend/src/components/ChatBox.vue`
- `backend/app/api/routes/chat.py`
- `backend/app/graph/builder.py`
- `backend/app/graph/middleware/`
- `backend/app/llm/`

### 新增资源类型

需要同步检查：

- `backend/app/plugins/types.py`
- `backend/app/plugins/registry.py`
- `backend/app/db/models.py`
- `backend/app/api/routes/resources.py`
- `frontend/src/stores/selectionStore.js`
- `frontend/src/views/HomeView.vue`

### 修改数据库字段

需要同步检查：

- `backend/app/db/models.py`
- `backend/app/db/repositories.py`
- `backend/app/schemas.py`
- 对应 API 路由
- `frontend/src/apis/resources.js`
- 前端 store 和组件

## 8. 验证命令

前端构建：

```powershell
cd frontend
npm run build
```

后端语法和导入检查：

```powershell
cd backend
.\.venv\Scripts\python.exe -m compileall app
.\.venv\Scripts\python.exe -c "from app.main import app; print(app.title)"
```

数据库依赖检查：

```powershell
docker ps --filter name=minibot-postgres
```
