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
- 涉及数据库、对象存储或 API 行为时，启动 PostgreSQL 和 MinIO 后做真实接口验证。

## 2. 开发与调试流程

启动 PostgreSQL、MinIO 和 Agent 沙盒 provisioner：

```powershell
docker compose up -d postgres minio sandbox-provisioner
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

默认对象存储：

```env
MINIBOT_STORAGE_PROVIDER=minio
MINIBOT_STORAGE_BUCKET=minibot
MINIBOT_MINIO_ENDPOINT=localhost:9000
MINIBOT_MINIO_ACCESS_KEY=minibot
MINIBOT_MINIO_SECRET_KEY=minibot123
MINIBOT_MINIO_SECURE=false
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
MINIBOT_OPENAI_TIMEOUT_SECONDS=180
MINIBOT_TAVILY_API_KEY=your_tavily_api_key
MINIBOT_EXCHANGE_RATE_BASE_URL=https://api.frankfurter.dev/v1
MINIBOT_EXCHANGE_RATE_TIMEOUT_SECONDS=15
MINIBOT_RUNTIME_TOOL_CALL_LIMIT=3
```

沙盒配置：

```env
MINIBOT_SANDBOX_ENABLED=true
MINIBOT_SANDBOX_PROVISIONER_URL=http://localhost:8002
MINIBOT_SANDBOX_INTERNAL_TOKEN=minibot-sandbox-dev-token
MINIBOT_SANDBOX_DATA_DIR=./data/runtime
MINIBOT_SANDBOX_EXEC_TIMEOUT_SECONDS=180
MINIBOT_SANDBOX_KEEPALIVE_INTERVAL_SECONDS=30
MINIBOT_SANDBOX_MAX_OUTPUT_BYTES=262144
MINIBOT_SANDBOX_MAX_WRITE_BYTES=81920
```

非本地开发环境必须替换默认 `MINIBOT_SANDBOX_INTERNAL_TOKEN`，并确保后端与
`sandbox-provisioner` 使用相同值。

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
- 业务流程放在 `backend/app/services`，包括会话、知识库选择和资源解析；不要把业务流程堆进 API route。
- 知识库文档上传、原始文件/Markdown 保存和解析状态更新放在 `backend/app/services/knowledge_service.py`。
- 文件转 Markdown 的具体解析器放在 `backend/app/document_parsers`，不要把不同文件类型解析逻辑堆进 route。
- 原始文件和 Markdown 文件通过 `backend/app/storage` 的对象存储抽象保存，业务层不要直接调用 MinIO SDK。
- 内置 agent 能力放在 `backend/app/agents/buildin`，其中 `chatbot` 对应智能助手。
- 智能助手的一次 Agent 对话运行编排放在 `backend/app/agents/buildin/chatbot/runtime.py`，runtime 只负责串联 service、构建 context 和调用 agent。
- Subagent 使用逻辑 `thread_id` 隔离子任务状态；同一轮多个独立 `task` 由 LangGraph 并发执行，`ChatBotState.subagent_runs` 必须通过 reducer 按 `child_thread_id` 合并，禁止用普通 list 覆盖并行结果。
- 每次父 Agent 和子 Agent 执行都写入 `agent_runs`；子运行必须记录 `parent_agent_run_id`、`thread_id`、幂等 `request_id` 和终态。续跑只能传回此前 `task` 返回的 child thread ID，且不得并行续跑同一 child thread。
- 主 Agent 与 Subagent 图都必须挂载 PostgreSQL `AsyncPostgresSaver`；调用图时在 `configurable.thread_id` 传入逻辑线程。应用启动由 `checkpoint_manager.initialize()` 创建或迁移 LangGraph checkpoint 表，禁止以“上一次最终回答注入 prompt”代替 checkpoint 续跑。
- Windows 环境下 PostgreSQL checkpoint 使用 psycopg async pool，应用启动前必须切换为 `WindowsSelectorEventLoopPolicy`，否则 Proactor loop 无法建立异步连接。
- `/api/chat/stream` 的工具过程采用 Yuxi 风格 `tool_calls` 模型：每个 `tool_event` 必须带稳定 `id`、`tool_name`、状态与受限的 `args` 展示字段；前端按 id 合并为消息内的工具调用组。子 Agent 的模型文本只能通过独立的 `subagent_token` 事件推送，必须附带 `subagent_type`、`child_thread_id`、`run_id` 和父 `tool_call_id`，前端不得将其混入主回答 token。仅允许展示经裁剪的查询、任务说明、虚拟路径等用户可见输入；禁止推送文件内容、API key 或其他敏感参数。
- `/api/chat/stream` 主回答必须直接消费父 LangGraph `astream(stream_mode=["messages", "values"])` 的 `AIMessageChunk` 并立即推送 `token`；最终答案从 checkpoint state 读取后持久化。禁止在 `ainvoke()` 完成后对完整 answer 人为切片伪造流式输出。
- 智能助手运行时上下文放在 `backend/app/agents/buildin/chatbot/context.py`，不要把资源、用户、模型用途散落到 state dict 中。
- `backend/app/agents/buildin/chatbot/graph.py` 使用 LangChain `create_agent` 构建 agent，不手写 node/edge 编排。
- Agent 业务中间件放在 `backend/app/agents/middlewares`，新增上下文裁剪、记忆、工具权限等能力时优先新增独立 middleware 文件。
- 知识库工具由 `backend/app/agents/middlewares/knowledge_base.py` 注册，工具实现继续放在 `backend/app/agents/toolkits/kbs`。
- 上下文压缩放在 `backend/app/agents/middlewares/summary.py`；默认按估算 token 达到 90K 触发，先将超阈值 ToolMessage 结果卸载到 `/mnt/user-data/workspace/.minibot/summary_offload`，卸载后仍超过 `summary_max_retention_ratio * summary_trigger_tokens` 时再清理历史并生成滚动摘要，始终保留 System Message。
- 智能助手提示词组装放在 `backend/app/agents/buildin/chatbot/prompt.py`；基础 prompt 在 `create_agent` 时构建，资源、Skill 和工具策略由 middleware 在每次模型调用前增量追加，不要在 provider 中拼 prompt。
- Skill 元数据存放在独立 `skills` 表中，`AgentContext.skills` 只保存 slug；不在 runtime 中预加载或缓存 Skill 元数据。`SkillsMiddleware.abefore_agent` 直接通过 Repository 加载提示元数据和依赖图、展开 `skill_dependencies`，并将 Skill 提示段合并到 `AgentContext.system_prompt`；`awrap_model_call` 再次从数据库读取依赖图并处理动态依赖；读取可见 Skill 的 `/mnt/skills/<slug>/SKILL.md` 后由同步或异步 tool wrapper 写入 `activated_skills`。`RuntimeConfigMiddleware.awrap_model_call` 每次从 context 读取最新 system prompt 并覆盖模型请求。
- 普通 Tool 与 MCP 在 graph 构建时按当前用户已启用资源注入；Skill 依赖必须经过 `backend/app/agents/toolkits/dependencies.py` 的 provider 和统一工具 resolver，在读取对应 `SKILL.md` 并激活后才动态追加。Skill 依赖不得绕过资源启用状态或用户可见范围。
- 内置 Skill 放在 `backend/app/agents/skills/buildin/<slug>/SKILL.md`，应用启动时自动扫描并同步资源元数据；新增内置 Skill 不要在种子函数中重复硬编码。
- 工具调用日志统一由 `backend/app/agents/toolkits/governance.py` 记录开始、完成和失败；Skill 可见范围、激活和依赖注入由 `SkillsMiddleware` 记录。日志不得输出文件内容、完整查询正文、API key 或其他敏感参数。
- 大模型接入放在 `backend/app/llm`，不要把 provider、API key、HTTP 请求细节写进 agent graph。
- 运行时工具统一放在 `backend/app/agents/toolkits`：`registry.py` 自动注册可信 Tool，`resolver.py` 将已授权资源解析为具体 LangChain Tool 与 MCP Tool，`governance.py` 负责事件记录；普通 Tool/MCP 在 graph 创建时注入，middleware 自带 Tool 自动注入，已激活 Skill 的依赖在后续模型调用中动态追加，工具调用上限由统一的 `ToolCallLimitMiddleware` 负责。
- 系统内置工具放在 `backend/app/agents/toolkits/buildin`，使用 `registry.py` 提供的 YUXI 风格 `@tool(category=..., tags=..., display_name=...)` 注册，模块导入时自动收集具体 LangChain Tool。
- 可信外置 API 工具放在 `backend/app/agents/toolkits/external/<slug>`；使用 `category="external"` 注册，启动时同步为 `origin="plugin"` 且默认禁用，管理员启用后才允许用户在工作区选择。外部密钥只放环境变量，不写入资源配置、日志或流事件。
- Agent 沙盒抽象、路径和生命周期放在 `backend/app/agents/backends/sandbox`；工具层不能直接调用 Docker SDK 或拼接宿主机路径。
- Agent 中间件写入 `/mnt/...` 虚拟路径时优先通过 `backend/app/agents/backends` 的文件系统 backend，不在 middleware 中直接解析宿主机路径。
- 沙盒文件工具放在 `backend/app/agents/toolkits/sandbox`，由 `SandboxMiddleware` 自动注入，不属于扩展管理的普通 Tool；当前只提供 `read_file`、`write_file`、`ls`、`glob`、`grep` 对应的受控能力，不提供宿主机执行模式。
- 沙盒按 `user_id + conversation_id` 隔离并延迟创建；`workspace` 为用户级共享目录，`uploads`、`outputs` 和只读 `skills` 为会话级目录。
- Agent 只使用 `/mnt/user-data/workspace`、`/mnt/user-data/uploads`、`/mnt/user-data/outputs`、`/mnt/skills` 虚拟路径，不得向模型暴露宿主机真实路径。
- `uploads` 和 `skills` 必须只读挂载；只有 `workspace` 与 `outputs` 可写。最终交付物必须写入 outputs，再通过 `present_artifacts` 展示。
- Docker 容器创建和回收由 `docker/sandbox_provisioner` 独立服务负责，后端只通过带内部 token 的 HTTP API 获取沙盒。
- 当前沙盒不实现本地宿主机执行、通用 Bash、warm pool 或 Kubernetes backend；新增这些能力前必须单独评估权限、网络和资源限制。
- `seed_builtin_resources` 会从全局工具注册表自动同步 `category="buildin"` 的资源元数据；内置工具首次注册或默认策略版本迁移时开启，并保留管理员后续设置的启用状态。
- 新增内置工具时必须定义独立输入 schema；`PluginResource.name` 必须与 Registry 中的稳定工具名一致，数据库配置不能直接指定任意 Python 执行器。
- 模型用途通过 `model_use` 区分，当前支持 `chat_model`，预留 `deep_research_model`。
- 通用数据库访问放在 `backend/app/db/repositories.py`；Skill 数据访问固定放在 `backend/app/repositories/skill_repository.py`。
- SQLAlchemy 模型放在 `backend/app/db/models.py`。
- 请求/响应 schema 放在 `backend/app/schemas.py` 或对应资源类型模块中。
- 资源注册、种子数据和名称解析放在 `backend/app/plugins/registry.py`。
- `plugin_resources.kind` 当前只允许 `mcp`、`tool`；Skill 使用独立表和 `/api/skills`，新增类型时必须同步更新模型、schema、校验、种子数据、API 和前端选择器。
- `PluginResource.name` 是稳定运行时 key，`display_name` 只用于 UI 展示。
- 当前没有迁移系统，数据库表由 `Base.metadata.create_all` 在应用启动时创建；结构变更要注意已有数据库兼容性。

## 5. 需求沟通规范

需求不明确时，需要主动挖掘需求细节，对齐验收标准，明确优先级和范围，避免模糊需求导致过度设计和不必要工作。

## 6. API 契约规范

所有业务路由挂载在 `/api` 下。

当前主要接口：

- `GET /api/resources?kind=mcp|tool`
- `POST /api/resources`
- `GET /api/skills`
- `GET /api/selections/{user_id}`
- `PUT /api/selections/{user_id}`
- `GET /api/selections/{user_id}/resolved`
- `GET /api/conversations?user_id=default`
- `POST /api/conversations`
- `PATCH /api/conversations/{conversation_id}?user_id=default`
- `DELETE /api/conversations/{conversation_id}?user_id=default`
- `GET /api/conversations/{conversation_id}/messages?user_id=default`
- `POST /api/chat`
- `GET /api/knowledge-bases?user_id=default`
- `POST /api/knowledge-bases`
- `DELETE /api/knowledge-bases/{knowledge_base_id}?user_id=default`
- `GET /api/knowledge-bases/{knowledge_base_id}/documents?user_id=default`
- `POST /api/knowledge-bases/{knowledge_base_id}/documents?user_id=default`
- `DELETE /api/knowledge-documents/{document_id}?user_id=default`

`/api/chat` 负责：

1. 创建或校验会话。
2. 保存用户消息。
3. 读取用户选择的知识库范围。
4. 读取扩展管理中启用的 MCP、Tool，以及独立 `skills` 表中的 Skill；所有已启用 Tool/MCP 在 graph 创建时直接注入，Skill 依赖从同一启用资源范围动态解析。
5. 根据 Skill slug 构建运行时提示元数据和依赖图。
6. 构建 `AgentContext`。
7. 调用 `create_agent` 生成的 agent。
8. 保存 assistant 回复和工具调用事件。
9. 返回 `conversation_id`、会话信息、消息列表、资源和回答。

## 7. 数据库规范

当前核心表：

- `plugin_resources`：MCP、Tool 元数据。
- `skills`：Skill 名称、描述、依赖、目录、版本、内置标记和内容哈希。
- `plugin_resources(kind=tool)`：运行时工具元数据，例如 `tavily_search`。
- `user_selections`：用户选择的知识库 ID；旧 MCP、Skill、Subagent 列仅为现有数据库兼容保留。
- `conversations`：对话会话元信息。
- `conversation_messages`：对话消息明细。
- `agent_runs`：父/子 Agent 运行记录，保存逻辑线程、父子关联、状态、结果与错误。
- LangGraph checkpoint 表（`checkpoints`、`checkpoint_blobs`、`checkpoint_writes`、`checkpoint_migrations`）由 `AsyncPostgresSaver.setup()` 管理，不映射为应用 SQLAlchemy 模型。
- `knowledge_bases`：知识库元信息。
- `knowledge_documents`：知识库文档元数据、对象存储 key 和解析状态。

约定：

- 继续沿用 `user_id` 作为当前无认证阶段的用户标识。
- `user_selections.knowledge_base_ids` 保存右侧工作区启用的知识库 ID，写入时必须按 `user_id` 过滤访问范围。Tool/MCP 是否可用仅由扩展管理中的启用状态决定。
- 会话删除默认采用归档语义，避免误删历史数据。
- 会话归档时必须通过 `AsyncPostgresSaver.adelete_thread()` 清理 `conversation:<id>` 及该会话 `agent_runs.checkpoint_thread_id` 关联的所有子 Agent checkpoint；保留会话消息和运行审计记录。
- 消息 `role` 只使用 `user`、`assistant`、`system`、`tool`。
- 消息扩展信息放在 JSONB `metadata` 中，不要把运行时上下文硬编码进文本字段。
- 知识库原始文档和 Markdown 副本保存在对象存储中，PostgreSQL 只保存 object key、状态、hash、文件大小等元数据。

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
- 当前没有认证系统，`user_id` 仍是客户端传入的简单标识。
- 当前真实模型能力取决于运行时配置；默认模型仍可使用 `mock`。

## 11. 知识库分块补充

- 多策略 Markdown 分块实现放在 `backend/app/knowledge/chunking/ragflow_like`，由 `dispatcher.py` 统一调度；通用策略位于 `parsers/general.py`，按分隔符形成 section，再按 token 上限合并，超长 chunk 兜底硬切。
- 文档上传解析成功后由 `backend/app/services/knowledge_service.py` 串联分块、embedding 和 Milvus 入库。
- `knowledge_chunks` 只保存 chunk 元数据；chunk 正文和向量保存在 Milvus collection 中。
- chunk 查询接口为 `GET /api/knowledge-documents/{document_id}/chunks?user_id=default`。
- 知识库通过 `knowledge_bases.metadata.kb_type` 区分 `milvus` 与 `lightrag`；旧数据默认按 `milvus` 处理。
- LightRAG 作为与 Milvus 平级的知识库 backend，使用独立 Milvus database 保存内部向量集合，并使用 Neo4j 保存图谱；具体实现放在 `backend/app/knowledge/backends`。
- 文档删除接口为 `DELETE /api/knowledge-documents/{document_id}?user_id=default`，必须先清理对应 backend 索引，再删除 PostgreSQL 元数据。
- 知识库删除必须清理对应 backend、MinIO 前缀和 `user_selections.knowledge_base_ids` 引用，再删除 PostgreSQL 元数据；存在 `uploaded`、`parsing`、`chunking`、`embedding` 或 `indexing` 文档时返回 409。



## 12.代码可阅读性规范

在生成代码函数的过程中，加入必要的注释，方便快速阅读代码
