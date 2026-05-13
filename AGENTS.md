# miniBOT Agent 开发规范

本文档存放面向编码 agent 的开发规范。项目结构导航请看 [PROJECT_MAP.md](PROJECT_MAP.md)。

miniBOT 是一个受 YUXI 资源编排思路启发的小型全栈脚手架：前端使用 Vue 3 + Vite，后端使用 FastAPI + SQLAlchemy async + PostgreSQL，并通过 `create_agent + context + middleware` 串联 MCP、Skill、Subagent 资源和大模型调用。

## 1. 工作原则

### 先理解再编码

- 改代码前先确认涉及的入口、数据结构和调用链。
- 不确定需求时，先说明假设；范围不清时先问清楚。
- 优先做能直接满足目标的最小改动，不做额外功能。
- 遇到多个可行方案时，说明取舍，不要静默选择复杂方案。

### 保持改动克制

- 只修改与当前任务直接相关的文件。
- 不顺手重构无关代码、不格式化整仓库、不删除已有无关代码。
- 新增抽象必须有明确收益：复用、隔离副作用、降低认知负担。
- 如果发现无关问题，可以在结果中说明，不要擅自扩大修复范围。

### 以验证闭环

- 每个任务都要有可执行的验证方式。
- 前端改动至少运行 `npm run build`。
- 后端改动至少运行 `python -m compileall app`；涉及运行时导入时，优先使用 `backend/.venv/Scripts/python.exe`。
- 涉及数据库或 API 行为时，启动 PostgreSQL 后做真实接口验证。

## 2. 开发与调试流程

启动 PostgreSQL：

```powershell
docker compose up -d postgres
```

启动后端：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

后端默认读取 `.env`，配置前缀为 `MINIBOT_`。默认数据库：

```text
postgresql+asyncpg://minibot:minibot@localhost:5432/minibot
```

模型配置支持分用途管理：

```env
MINIBOT_DEFAULT_MODEL_PROVIDER=mock
MINIBOT_DEFAULT_MODEL_NAME=mock
MINIBOT_CHAT_MODEL_PROVIDER=openai
MINIBOT_CHAT_MODEL_NAME=qwen-plus
MINIBOT_DEEP_RESEARCH_MODEL_PROVIDER=openai
MINIBOT_DEEP_RESEARCH_MODEL_NAME=qwen-plus
MINIBOT_OPENAI_API_KEY=your_api_key
MINIBOT_OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MINIBOT_OPENAI_TEMPERATURE=0.2
MINIBOT_TAVILY_API_KEY=your_tavily_api_key
MINIBOT_RUNTIME_TOOL_CALL_LIMIT=3
```

启动前端：

```powershell
cd frontend
npm install
npm run dev
```

默认访问：

```text
http://localhost:5173
```

## 3. 前端开发规范

- 使用 Vue 3 `<script setup>`。
- API 请求统一放在 `frontend/src/apis`，组件不要直接写散落的 `fetch`。
- 跨组件状态放在 `frontend/src/stores`，保持小型 reactive store，不引入新的状态管理库。
- 组件放在 `frontend/src/components`，页面组合放在 `frontend/src/views`。
- 样式集中维护在 `frontend/src/styles.css`，除非出现明确的局部样式隔离需求。
- 图标优先使用 `lucide-vue-next`。
- 对话历史由后端 PostgreSQL 持久化，前端通过 `conversationStore.js` 调用 conversations API，不再使用 `localStorage` 作为主存储。
- 修改后端 API 契约时，同步更新 `frontend/src/apis/resources.js` 和调用方。

## 4. 后端开发规范

- 路由层保持轻量，主要负责参数接收、依赖注入和响应组织。
- 一次 Agent 对话运行的编排逻辑放在 `backend/app/agent/runtime.py`。
- 运行时上下文放在 `backend/app/agent/context.py`，不要把资源、用户、模型用途散落到 state dict 中。
- `backend/app/graph/builder.py` 使用 LangChain `create_agent` 构建 agent，不手写 node/edge 编排。
- `backend/app/graph/middleware` 只放 `AgentMiddleware`，新增上下文裁剪、记忆、工具权限等能力时优先新增独立 middleware 文件。
- 提示词组装放在 `backend/app/graph/prompt.py`，middleware 负责决定何时注入，不要在 provider 中拼 prompt。
- 大模型接入放在 `backend/app/llm`，不要把 provider、API key、HTTP 请求细节写进 `graph/builder.py`。
- 运行时工具放在 `backend/app/tools`，agent 初始只绑定工具路由能力，具体工具由 `dynamic_tool_call` 按名称加载执行。
- 模型用途通过 `model_use` 区分，当前支持 `chat_model`，预留 `deep_research_model`。
- 数据库访问放在 `backend/app/db/repositories.py`。
- SQLAlchemy 模型放在 `backend/app/db/models.py`。
- 请求/响应 schema 放在 `backend/app/schemas.py` 或对应资源类型模块中。
- 资源注册、种子数据和名称解析放在 `backend/app/plugins/registry.py`。
- 资源 `kind` 当前允许 `mcp`、`skill`、`subagent`、`tool`；新增类型时必须同步更新模型、schema、校验、种子数据、API 和前端选择器。
- `PluginResource.name` 是稳定运行时 key，`display_name` 只用于 UI 展示。
- 当前没有迁移系统，数据库表由 `Base.metadata.create_all` 在应用启动时创建；结构变更要注意已有数据库兼容性。

## 5. 需求沟通规范

需求不明确时，需要主动挖掘需求细节，对齐验收标准，明确优先级和范围，避免模糊需求导致过度设计和不必要工作。

## 6. API 契约规范

所有业务路由挂载在 `/api` 下。

当前主要接口：

- `GET /api/resources?kind=mcp|skill|subagent|tool`
- `POST /api/resources`
- `GET /api/selections/{user_key}`
- `PUT /api/selections/{user_key}`
- `GET /api/selections/{user_key}/resolved`
- `GET /api/conversations?user_key=default`
- `POST /api/conversations`
- `PATCH /api/conversations/{conversation_id}?user_key=default`
- `DELETE /api/conversations/{conversation_id}?user_key=default`
- `GET /api/conversations/{conversation_id}/messages?user_key=default`
- `POST /api/conversations/{conversation_id}/messages?user_key=default`
- `POST /api/chat`

`/api/chat` 负责：

1. 创建或校验会话。
2. 保存用户消息。
3. 读取用户资源选择。
4. 解析 MCP、Skill、Subagent 资源。
5. 读取启用的运行时工具资源。
6. 构建 `AgentContext`。
7. 调用 `create_agent` 生成的 agent。
8. 保存 assistant 回复和工具调用事件。
9. 返回 `conversation_id`、会话信息、消息列表、资源和回答。

## 7. 数据库规范

当前核心表：

- `plugin_resources`：MCP、Skill、Subagent 元数据。
- `plugin_resources(kind=tool)`：运行时工具元数据，例如 `tavily_search`。
- `user_selections`：用户选择的资源名称列表。
- `conversations`：对话会话元信息。
- `conversation_messages`：对话消息明细。

约定：

- 继续沿用 `user_key` 作为当前无认证阶段的用户标识。
- 会话删除默认采用归档语义，避免误删历史数据。
- 消息 `role` 只使用 `user`、`assistant`、`system`、`tool`。
- 消息扩展信息放在 JSONB `metadata` 中，不要把运行时上下文硬编码进文本字段。

## 8. 文档维护规范

- 改动项目结构、启动方式、API 契约或核心数据流时，同步更新 [PROJECT_MAP.md](PROJECT_MAP.md)。
- 改动开发流程、验证命令、约定或 agent 行为要求时，同步更新本文件。
- 非必要不新增零散文档；新增文档时要在 `PROJECT_MAP.md` 中挂入口。

## 9. 提交规范

- 提交信息建议使用中文，标题简洁说明变更目的。
- 可以参考 Conventional Commits，例如：
  - `feat: 持久化对话历史`
  - `fix: 修复会话切换后的消息加载`
  - `docs: 更新项目导航地图`
- 提交前检查 `git diff`，确认没有混入无关格式化或临时调试代码。

## 10. 当前已知限制

- 项目还没有正式测试套件。
- 项目还没有数据库迁移系统。
- 当前没有认证系统，`user_key` 仍是客户端传入的简单标识。
- 当前真实模型能力取决于运行时配置；默认模型仍可使用 `mock`。
