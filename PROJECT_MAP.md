# miniBOT 项目导航地图

本文档用于快速定位 miniBOT 的目录、入口、数据流和常见修改位置。开发规范请看 [AGENTS.md](AGENTS.md)。

## 1. 总览

miniBOT 是一个前后端分离的模块化助手脚手架。

```text
miniBOT
|-- backend/              FastAPI 后端
|-- frontend/             Vue 3 + Vite 前端
|-- docker-compose.yml    PostgreSQL / MinIO 开发依赖
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
  -> 读取历史消息和知识库选择
  -> 读取扩展管理中启用的 MCP / Tool 和独立 skills 表
  -> 创建 AgentContext
  -> create_agent 构建基础 prompt + middleware 增量追加运行时提示词
  -> RuntimeConfigMiddleware 按上下文提供具体 LangChain Tools
  -> chat_model
  -> 保存 assistant message
  -> 前端刷新当前会话
```

知识库文档入库链路：

```text
前端上传文档
  -> POST /api/knowledge-bases/{kb_id}/documents
  -> KnowledgeService
  -> MinIO 保存原始文件
  -> PostgreSQL 保存 knowledge_documents 元数据，status=uploaded/parsing
  -> document_parsers 转 Markdown
  -> MinIO 保存 Markdown 副本
  -> 根据知识库 metadata 中的 chunk_preset_id 选择分块策略
  -> 按 knowledge_bases.metadata.kb_type 选择 Milvus 或 LightRAG backend
  -> Milvus：embedding + Milvus 入库
  -> LightRAG：独立 Milvus collections + Neo4j 图谱入库
  -> PostgreSQL 更新 status=indexed 或 failed
```

## 2. 后端地图

```text
backend/app
|-- main.py                  FastAPI app、CORS、lifespan、路由挂载
|-- schemas.py               通用请求/响应 Pydantic schema
|-- agent/                   旧兼容入口，转发到 agents/buildin
|-- agents/
|   |-- checkpoints.py       PostgreSQL LangGraph checkpointer lifecycle
|   |-- state.py             parent/subagent shared BaseAgentState
|   |-- backends/
|   |   |-- filesystem.py    Agent 虚拟文件系统 backend，统一处理 `/mnt/...` 写入
|   |   `-- sandbox/
|   |       |-- client.py     provisioner 与 agent-sandbox HTTP 客户端
|   |       |-- middleware.py 延迟创建后的 sandbox_id 状态持久化
|   |       |-- paths.py      虚拟路径、宿主目录和 Skill 同步
|   |       `-- provider.py   按用户和会话获取、缓存、保活沙盒
|   |-- buildin/
|   |   `-- chatbot/         智能助手
|   |       |-- context.py   AgentContext 运行时上下文
|   |       |-- graph.py     create_agent 构建入口
|   |       |-- prompt.py    基础提示词和运行时提示词片段组装
|   |       |-- state.py     messages、artifacts 与并行 subagent runs Agent 状态
|   |       `-- runtime.py   一次智能助手对话运行编排
|   |   `-- subagent/
|   |       |-- graph.py     isolated subagent create_agent entry
|   |       |-- runner.py    child context builder and child agent runner
|   |       |-- state.py     SubAgentState without parent subagent run records
|   |       `-- tools.py     middleware-owned task tool with parallel-safe state updates
|   |-- middlewares/
|   |   |-- subagent_middleware.py task delegation policy, profiles, runs and thread lifecycle
|   |   |-- knowledge_base.py  知识库工具注入中间件
|   |   |-- runtime_config.py  运行时工具注册与模型可见性筛选
|   |   |-- Skills_middleware.py  Skill DB 加载、摘要注入、读取激活和依赖按需加载
|   |   |-- runtime_prompt.py  资源和工具策略增量注入
|   |   |-- summary.py         长上下文压缩与工具结果卸载
|   |   `-- system_message.py  system message 追加工具
|   |-- skills/
|   |   |-- parser.py          SKILL.md frontmatter 与依赖解析
|   |   |-- service.py         Skill 目录校验、哈希、安装和内置同步
|   |   `-- buildin/           随应用发布并在启动时自动同步的内置 Skills
|   `-- toolkits/
|       |-- registry.py      YUXI 风格 @tool 注册与元数据
|       |-- resolver.py      已授权资源到 Tool 的解析
|       |-- dependencies.py  Skill Tool/MCP 依赖 provider 注册与解析
|       |-- governance.py    工具调用事件与结果记录
|       |-- buildin/         系统内置工具
|       |-- sandbox/         受控沙盒文件工具
|       `-- kbs/             知识库工具集
|-- core/
|   `-- config.py            环境变量与默认配置
|-- api/
|   |-- router.py            /api 路由聚合
|   `-- routes/
|       |-- health.py
|       |-- resources.py
|       |-- skills.py
|       |-- selections.py
|       |-- conversations.py
|       `-- chat.py
|-- db/
|   |-- session.py           async engine、session、create_all
|   |-- models.py            SQLAlchemy 模型
|   `-- repositories.py      数据访问层
|-- repositories/
|   `-- skill_repository.py  独立 skills 表的数据访问
|-- services/
|   |-- conversation_service.py  会话和消息业务服务
|   |-- knowledge_service.py     知识库、文档上传和解析编排服务
|   |-- selection_service.py     用户知识库选择服务
|   `-- resource_service.py      资源解析服务
|-- knowledge/
|   |-- backends/
|   |   |-- base.py              Milvus / LightRAG 统一知识库接口
|   |   |-- factory.py           按 kb_type 选择 backend
|   |   |-- milvus.py            原有向量知识库实现
|   |   `-- lightrag.py          LightRAG + Neo4j 图知识库实现
|   `-- chunking/
|       `-- ragflow_like/        多策略 Markdown 分块
|-- storage/
|   |-- base.py                  对象存储抽象
|   |-- factory.py               存储服务工厂
|   `-- minio.py                 MinIO 对象存储实现
|-- document_parsers/
|   `-- factory.py               文档转 Markdown 解析入口
|-- graph/
|   |-- builder.py           旧兼容入口，转发到 agents/buildin/chatbot/graph.py
|   |-- prompt.py            旧兼容入口，转发到 agents/buildin/chatbot/prompt.py
|   `-- middleware/          LangChain AgentMiddleware
|-- llm/
|   |-- base.py              BaseChatModel 别名
|   |-- chat_model.py        OpenAI-compatible / mock ChatModel
|   `-- factory.py           chat_model / deep_research_model 工厂
`-- plugins/
    |-- types.py             资源类型和资源 schema
    `-- registry.py          内置资源种子数据与名称解析
```

沙盒调用链：

```text
模型调用 sandbox_read_file / sandbox_write_file / sandbox_ls / sandbox_glob / sandbox_grep
  -> SandboxMiddleware 持久化 sandbox_id
  -> ProvisionerSandboxProvider 按 user_id + conversation_id 获取沙盒
  -> HTTP 调用 sandbox-provisioner
  -> provisioner 动态创建或复用 Docker 容器
  -> agent-sandbox 文件 API 执行受控文件操作
  -> workspace/outputs 写入宿主持久化目录
```

沙盒虚拟文件系统：

```text
/mnt/user-data/workspace   用户级共享，可写
/mnt/user-data/uploads     会话级，只读
/mnt/user-data/outputs     会话级，可写
/mnt/skills                当前会话可见 Skill，只读
```

`docker/sandbox_provisioner` 是独立 FastAPI 服务，默认监听宿主机
`127.0.0.1:8002`。管理接口需要 `X-Sandbox-Token`，动态沙盒端口也只绑定回环地址。

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
    |   |-- ExtensionManagementView.vue
    |   |-- MarkdownMessage.vue
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

`agents/buildin/chatbot/runtime.py` 负责一次完整智能助手运行编排。主回答直接消费父 LangGraph `astream(messages, values)` 的 `AIMessageChunk` 推送 SSE，结束后从 checkpoint state 读取最终结果并保存。工具过程采用 Yuxi 风格的消息内 `tool_calls`：SSE 按稳定调用 ID 更新临时调用，最终以同一结构保存到 assistant metadata；子任务工具和文本按父 `task` 调用嵌套展示。

```text
调用 ConversationService 准备会话和消息
调用 SelectionService 读取用户知识库选择
调用 ResourceService 解析资源
构建 AgentContext
调用 create_agent 生成的 agent
委托 ConversationService 保存 assistant 回复并构造响应
```

右侧工作区选择知识库后，通过 selections API 将 `knowledge_base_ids` 保存到
`user_selections`。聊天运行时读取该字段并写入 `AgentContext.knowledge_base_ids`，
知识库工具只允许查询这个 ID 列表内且属于当前 `user_id` 的知识库。

`services/` 负责业务流程：

```text
ConversationService  会话创建、消息保存、历史消息转换、聊天响应构造
SelectionService     用户知识库选择读取和默认值处理
ResourceService      已启用 MCP / Tool 与独立 Skill 资源解析
```

`agents/buildin/chatbot/graph.py` 只负责智能助手 agent 构建：

```text
选择模型用途 model_use
加载对应 BaseChatModel
挂载 AgentMiddleware
由 RuntimeConfigMiddleware 注册并筛选具体运行时工具
返回 compiled agent
```

`agents/toolkits/` 统一负责系统工具：

```text
registry.py               YUXI 风格 @tool 装饰器、Tool 实例和展示元数据
resolver.py               根据 AgentContext.tools 选择当前已授权 Tools
governance.py             工具调用状态、结果和事件记录
buildin/tools.py          ask_user_question / present_artifacts / tavily_search
buildin/install_skill.py  install_skill
buildin/subagent/tools.py middleware-owned task subagent delegation tool
kbs/tools.py              list_kbs / query_kb
```

应用启动时 `seed_builtin_resources` 会从注册表自动同步 `category="buildin"` 的工具资源，
因此新增内置工具不需要再手工维护另一份资源清单；首次注册或默认策略版本迁移时开启，
前端显示“内置工具”标签，后续管理员开关不会被应用重启覆盖。

`ask_user_question` 使用 LangGraph `interrupt` 语义；内置工具首次注册时统一默认开启。
其中交互提问仍需要前端问题卡片和会话恢复协议配合，管理员可在扩展管理页按实际能力关闭。

`agents/middlewares/` 统一负责供 Agent 模型调用使用的中间件：

```text
RuntimeConfigMiddleware    按 AgentContext.tools 筛选模型本轮可见的具体工具
ToolCallLimitMiddleware    统一限制单次 Agent 运行的工具调用总数
KnowledgeBaseMiddleware    注册 list_kbs / query_kb 知识库工具
SkillsMiddleware          生命周期内直接查询 Skill Repository，注入 prompt、展开依赖并处理动态激活
RuntimeConfigMiddleware   每次模型调用读取 context.system_prompt，并覆盖本次模型请求
SummaryMiddleware          估算 token 达到 90K 时先卸载大 ToolMessage，必要时再生成滚动摘要并裁剪历史
RuntimePromptMiddleware    每次模型调用前增量追加资源和工具策略
```

Skill 依赖工具配置：

```text
allow_skill_dependency=false  禁止该 Tool 被 Skill 依赖激活
expose_directly=false         不直接暴露给模型，仅在 Skill 激活后按需暴露
```

旧 Tool 未配置这两个字段时均按 `true` 处理，保持原有运行行为。

`llm/` 负责模型管理：

```text
chat_model             当前聊天模型
deep_research_model    预留深度研究模型
mock                   本地开发默认模型
openai-compatible      兼容 OpenAI Chat Completions 的模型服务
```

OpenAI-compatible 模型读取超时由 `MINIBOT_OPENAI_TIMEOUT_SECONDS` 控制，
默认 180 秒；超时会转换为可保存、可返回的 `model_timeout` 结果。

## 5. 数据库地图

模型定义：`backend/app/db/models.py`

当前核心表：

```text
plugin_resources
skills
user_selections
conversations
conversation_messages
agent_runs（父 Agent 与子 Agent 运行记录、逻辑 thread_id、状态和结果）
LangGraph checkpoint 表（由 AsyncPostgresSaver 自动创建与迁移）
knowledge_bases
knowledge_documents
user_selections.knowledge_base_ids
```

当前没有 Alembic 迁移系统，应用启动时通过 `Base.metadata.create_all` 创建缺失表。

## 6. API 地图

```text
GET    /api/health
GET    /api/resources?kind=mcp|tool
POST   /api/resources
GET    /api/skills
GET    /api/selections/{user_id}
PUT    /api/selections/{user_id}
GET    /api/selections/{user_id}/resolved
GET    /api/conversations?user_id=default
POST   /api/conversations
PATCH  /api/conversations/{conversation_id}?user_id=default
DELETE /api/conversations/{conversation_id}?user_id=default
GET    /api/conversations/{conversation_id}/messages?user_id=default
POST   /api/chat
POST   /api/chat/stream
GET    /api/knowledge-bases?user_id=default
POST   /api/knowledge-bases
GET    /api/knowledge-chunk-presets
GET    /api/knowledge-bases/{knowledge_base_id}/documents?user_id=default
POST   /api/knowledge-bases/{knowledge_base_id}/documents?user_id=default
DELETE /api/knowledge-documents/{document_id}?user_id=default
```

## 7. 常见任务定位

修改聊天运行流程：
- `backend/app/agents/buildin/chatbot/runtime.py`
- `backend/app/services/`
- `backend/app/api/routes/chat.py`

修改 agent 构建和 middleware：
- `backend/app/agents/buildin/chatbot/graph.py`
- `backend/app/agents/middlewares/`
- `backend/app/agents/buildin/chatbot/context.py`

修改上下文压缩：
- `backend/app/agents/middlewares/summary.py`
- `backend/app/agents/buildin/chatbot/context.py`
- `backend/app/core/config.py`

修改提示词：
- `backend/app/agents/buildin/chatbot/prompt.py`
- `backend/app/core/config.py`

修改模型接入：
- `backend/app/llm/factory.py`
- `backend/app/llm/chat_model.py`
- `.env.example`

修改运行时工具：
- `backend/app/agents/toolkits/`
- `backend/app/agents/middlewares/runtime_config.py`
- `backend/app/plugins/registry.py`
- `backend/app/agents/buildin/chatbot/prompt.py`

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

修改扩展管理：
- `frontend/src/components/ExtensionManagementView.vue`
- `frontend/src/components/ConversationSidebar.vue`
- `frontend/src/apis/resources.js`

修改知识库上传和解析：
- `backend/app/api/routes/knowledge.py`
- `backend/app/services/knowledge_service.py`
- `backend/app/knowledge/chunking/ragflow_like/dispatcher.py`
- `backend/app/knowledge/chunking/ragflow_like/parsers/`
- `backend/app/document_parsers/factory.py`
- `backend/app/storage/`
- `backend/app/db/models.py`

知识库文档上传采用进程内后台索引：

```text
POST 上传
  -> MinIO 保存原文件
  -> PostgreSQL 创建 status=uploaded 的文档
  -> 接口立即返回
  -> FastAPI BackgroundTasks 使用独立 AsyncSession
  -> 解析、分块、embedding / LightRAG 建图
  -> status=indexed 或 failed
  -> 前端每 3 秒轮询处理中状态
```

后台任务不复用请求数据库会话。检索服务只查询 `status=indexed` 的文档，避免索引中的部分数据参与问答。
当前实现是单进程内任务，服务重启不会自动恢复未完成任务；需要持久化任务恢复时再接入 Redis/ARQ。

知识库与文档删除链路：

```text
前端二次确认
  -> 检查文档是否处于处理中，处理中返回 409
  -> backend 清理 Milvus collection 或 LightRAG 文档/图谱/向量数据
  -> MinIO 删除文档对象或 knowledge-bases/{kb_id}/ 前缀
  -> 删除 user_selections 中的知识库引用
  -> PostgreSQL 级联删除 knowledge_bases / documents / chunks
```

对应接口为 `DELETE /api/knowledge-bases/{knowledge_base_id}` 和
`DELETE /api/knowledge-documents/{document_id}`。

## 8. 知识库分块补充

当前知识库上传链路在 Markdown 解析后，会读取知识库 `metadata` 中保存的
`chunk_preset_id` 和 `chunk_parser_config`，执行对应分块策略：

```text
Markdown
  -> backend/app/knowledge/chunking/ragflow_like/dispatcher.py
  -> general / separator / book / laws / qa
  -> knowledge_chunks
  -> 按 kb_type 分派
     -> milvus: embedding + Milvus dense/BM25
     -> lightrag: LightRAG 独立 Milvus collections + Neo4j
  -> knowledge_documents.status=indexed
```

`kb_type` 当前支持 `milvus` 和 `lightrag`，保存在 `knowledge_bases.metadata` 中；
旧知识库缺少该字段时按 `milvus` 处理。LightRAG backend 按知识库缓存实例，并对同一知识库的
写入使用进程内串行锁。多进程部署时需要进一步替换为 PostgreSQL advisory lock 或 Redis 锁。

分块实现移植并裁剪自 Yuxi `ragflow_like`。当前未接入 Semantic 策略，因为其同步 embedding、
NLTK 和 scikit-learn 依赖与 miniBOT 当前异步 embedding 链路不直接兼容。第三方许可保存在
`backend/app/knowledge/chunking/ragflow_like/YUXI_LICENSE`。

新增数据表：

```text
knowledge_chunks
```

`knowledge_chunks` 只保存 chunk 元数据、顺序和字符位置；chunk 正文和向量由 Milvus collection 保存。

Milvus collection 的 `content` 字段启用 Chinese analyzer，并通过内置 BM25 Function 自动生成
`content_sparse`。`embedding` 和 `content_sparse` 分别使用 COSINE vector 索引和 BM25 sparse 索引。

知识库查询链路：

```text
知识库 middleware 解析本轮启用资源
  -> AgentContext.knowledge_base_ids
  -> middleware 注入 list_kbs / query_kb
  -> Agent ToolRuntime 调用 query_kb
  -> backend/app/agents/toolkits/kbs/tools.py
  -> backend/app/services/knowledge_retrieval_service.py
  -> query embedding
  -> Milvus vector / keyword / hybrid search
  -> 返回 chunk、文档名、score 和 citation_id
```

`query_kb` 默认使用 hybrid 模式，底层通过 `WeightedRanker` 融合 vector 和 BM25 结果。
Milvus 查询层参考 Yuxi 实现，支持 `search_mode`、`final_top_k`、`recall_top_k`、
`similarity_threshold`、`bm25_top_k`、`vector_weight`、`bm25_weight`、
`bm25_drop_ratio_search`、`include_distances` 和文档过滤。

统一检索结果采用 `content + metadata + score` 结构，`metadata` 中包含来源文档、chunk、知识库和
`citation_id`。`KnowledgeRetrievalService` 根据知识库 `kb_type` 调用对应 backend，
不把 LightRAG 逻辑写入 `MilvusVectorStore`。

知识库工具只根据 `ToolRuntime.context` 中的 `user_id` 和 `knowledge_base_ids` 确定访问范围，
不接受模型传入的用户身份或 collection 名称。

可由 Agent middleware 直接注入的知识库工具位于：

```text
backend/app/agents/toolkits/kbs/tools.py
```

当前提供：

```text
list_kbs   列出当前会话启用且用户有权访问的知识库
query_kb   按 kb_id、query_text 和可选 file_name 查询知识库
```

`query_kb` 使用 LangGraph `ToolRuntime` 从 `AgentContext` 获取 `user_id` 和
`knowledge_base_ids`，不会把用户身份暴露为模型工具参数。`KnowledgeBaseMiddleware`
通过 `get_kb_tools()` 将工具注册到 agent，访问范围仍由 `AgentContext` 控制。

新增接口：

```text
GET /api/knowledge-documents/{document_id}/chunks?user_id=default
```
- `backend/app/db/repositories.py`

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
