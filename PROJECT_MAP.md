# miniBOT 椤圭洰瀵艰埅鍦板浘

鏈枃妗ｇ敤浜庡揩閫熷畾浣?miniBOT 鐨勭洰褰曘€佸叆鍙ｃ€佹暟鎹祦鍜屽父瑙佷慨鏀逛綅缃€傚紑鍙戣鑼冭鐪?[AGENTS.md](AGENTS.md)銆?

## 1. 鎬昏

miniBOT 鏄竴涓墠鍚庣鍒嗙鐨勬ā鍧楀寲鍔╂墜鑴氭墜鏋躲€?

```text
miniBOT
|-- backend/              FastAPI 鍚庣
|-- frontend/             Vue 3 + Vite 鍓嶇
|-- docker-compose.yml    PostgreSQL / MinIO 寮€鍙戜緷璧?
|-- README.md             椤圭洰璇存槑
|-- AGENTS.md             agent 寮€鍙戣鑼?
`-- PROJECT_MAP.md        椤圭洰瀵艰埅鍦板浘
```

鏍稿績閾捐矾锛?

```text
鍓嶇鍙戦€佹秷鎭?
  -> POST /api/chat
  -> AgentRuntime
  -> 淇濆瓨 user message
  -> 璇诲彇鍘嗗彶娑堟伅鍜岀煡璇嗗簱閫夋嫨
  -> 璇诲彇鎵╁睍绠＄悊涓惎鐢ㄧ殑 MCP / Tool 鍜岀嫭绔?skills 琛?  -> 鍒涘缓 AgentContext
  -> create_agent 鏋勫缓鍩虹 prompt + middleware 澧為噺杩藉姞杩愯鏃舵彁绀鸿瘝
  -> graph 鍒涘缓鏃舵敞鍏ユ櫘閫?Tool/MCP锛宮iddleware 鎸夐渶杩藉姞宸ュ叿
  -> chat_model
  -> 淇濆瓨 assistant message
  -> 鍓嶇鍒锋柊褰撳墠浼氳瘽
```

鐭ヨ瘑搴撴枃妗ｅ叆搴撻摼璺細

```text
鍓嶇涓婁紶鏂囨。
  -> POST /api/knowledge-bases/{kb_id}/documents
  -> KnowledgeService
  -> MinIO 淇濆瓨鍘熷鏂囦欢
  -> PostgreSQL 淇濆瓨 knowledge_documents 鍏冩暟鎹紝status=uploaded/parsing
  -> knowledge/parser 杞?Markdown
  -> MinIO 淇濆瓨 Markdown 鍓湰
  -> 鏍规嵁鐭ヨ瘑搴?metadata 涓殑 chunk_preset_id 閫夋嫨鍒嗗潡绛栫暐
  -> 鎸?knowledge_bases.metadata.kb_type 閫夋嫨 Milvus 鎴?LightRAG backend
  -> Milvus锛歟mbedding + Milvus 鍏ュ簱
  -> LightRAG锛氱嫭绔?Milvus collections + Neo4j 鍥捐氨鍏ュ簱
  -> PostgreSQL 鏇存柊 status=indexed 鎴?failed
```

## 2. 鍚庣鍦板浘

```text
backend/app
|-- main.py                  FastAPI app銆丆ORS銆乴ifespan銆佽矾鐢辨寕杞?
|-- schemas.py               閫氱敤璇锋眰/鍝嶅簲 Pydantic schema
|-- agent/                   鏃у吋瀹瑰叆鍙ｏ紝杞彂鍒?agents/buildin
|-- agents/
|   |-- checkpoints.py       PostgreSQL LangGraph checkpointer lifecycle
|   |-- state.py             parent/subagent shared BaseAgentState
|   |-- backends/
|   |   |-- filesystem.py    Agent 铏氭嫙鏂囦欢绯荤粺 backend锛岀粺涓€澶勭悊 `/mnt/...` 鍐欏叆
|   |   `-- sandbox/
|   |       |-- client.py     provisioner 涓?agent-sandbox HTTP 瀹㈡埛绔?
|   |       |-- middleware.py 寤惰繜鍒涘缓鍚庣殑 sandbox_id 鐘舵€佹寔涔呭寲
|   |       |-- paths.py      铏氭嫙璺緞銆佸涓荤洰褰曞拰 Skill 鍚屾
|   |       `-- provider.py   鎸夌敤鎴峰拰浼氳瘽鑾峰彇銆佺紦瀛樸€佷繚娲绘矙鐩?
|   |-- buildin/
|   |   `-- chatbot/         鏅鸿兘鍔╂墜
|   |       |-- context.py   AgentContext 杩愯鏃朵笂涓嬫枃
|   |       |-- graph.py     create_agent 鏋勫缓鍏ュ彛
|   |       |-- prompt.py    鍩虹鎻愮ず璇嶅拰杩愯鏃舵彁绀鸿瘝鐗囨缁勮
|   |       |-- state.py     messages銆乤rtifacts 涓庡苟琛?subagent runs Agent 鐘舵€?|   |       `-- runtime.py   涓€娆℃櫤鑳藉姪鎵嬪璇濊繍琛岀紪鎺?
|   |   `-- subagent/
|   |       |-- graph.py     isolated subagent create_agent entry
|   |       |-- runner.py    child context builder and child agent runner
|   |       |-- state.py     SubAgentState without parent subagent run records
|   |       `-- tools.py     middleware-owned task tool with parallel-safe state updates
|   |-- middlewares/
|   |   |-- subagent_middleware.py task delegation policy, profiles, runs and thread lifecycle
|   |   |-- knowledge_base.py  鐭ヨ瘑搴撳伐鍏锋敞鍏ヤ腑闂翠欢
|   |   |-- runtime_config.py  杩愯鏃跺伐鍏锋敞鍐屼笌妯″瀷鍙鎬х瓫閫?
|   |   |-- Skills_middleware.py  Skill DB 鍔犺浇銆佹憳瑕佹敞鍏ャ€佽鍙栨縺娲诲拰渚濊禆鎸夐渶鍔犺浇
|   |   |-- runtime_prompt.py  璧勬簮鍜屽伐鍏风瓥鐣ュ閲忔敞鍏?
|   |   |-- summary_middleware.py  long-context summarization
|   |   |-- tool_output_budget.py  ToolMessage output budgeting and offload
|   |   `-- system_message.py  system message 杩藉姞宸ュ叿
|   |-- mcp/                  Yuxi 椋庢牸 MCP service锛氬唴缃０鏄庛€佸彂鐜扮紦瀛樹笌宸ュ叿杩囨护
|   |-- skills/
|   |   |-- parser.py          SKILL.md frontmatter 涓庝緷璧栬В鏋?
|   |   |-- service.py         Skill 鐩綍鏍￠獙銆佸搱甯屻€佸畨瑁呭拰鍐呯疆鍚屾
|   |   `-- buildin/           闅忓簲鐢ㄥ彂甯冨苟鍦ㄥ惎鍔ㄦ椂鑷姩鍚屾鐨勫唴缃?Skills
|   `-- toolkits/
|       |-- registry.py      YUXI 椋庢牸 @tool 娉ㄥ唽涓庡厓鏁版嵁
|       |-- resolver.py      宸叉巿鏉冭祫婧愬埌 Tool 鐨勮В鏋?
|       |-- dependencies.py  Skill Tool/MCP 渚濊禆 provider 娉ㄥ唽涓庤В鏋?
|       |-- governance.py    宸ュ叿璋冪敤浜嬩欢涓庣粨鏋滆褰?
|       |-- buildin/         绯荤粺鍐呯疆宸ュ叿
|       |-- sandbox/         鍙楁帶娌欑洅鏂囦欢宸ュ叿
|       `-- kbs/             鐭ヨ瘑搴撳伐鍏烽泦
|-- core/
|   `-- config.py            鐜鍙橀噺涓庨粯璁ら厤缃?
|-- api/
|   |-- router.py            /api 璺敱鑱氬悎
|   `-- routes/
|       |-- health.py
|       |-- resources.py
|       |-- skills.py
|       |-- selections.py
|       |-- conversations.py
|       |-- model_providers.py
|       `-- chat.py
|-- db/
|   |-- session.py           async engine銆乻ession銆乧reate_all
|   |-- models.py            SQLAlchemy 妯″瀷
|   `-- repositories.py      鏁版嵁璁块棶灞?
|-- repositories/
|   `-- skill_repository.py  鐙珛 skills 琛ㄧ殑鏁版嵁璁块棶
|-- services/
|   |-- chat_run_service.py      后台聊天 Run、Redis Stream 事件与断线恢复
|   |-- conversation_service.py  浼氳瘽鍜屾秷鎭笟鍔℃湇鍔?
|   |-- knowledge_service.py     鐭ヨ瘑搴撱€佹枃妗ｄ笂浼犲拰瑙ｆ瀽缂栨帓鏈嶅姟
|   |-- selection_service.py     鐢ㄦ埛鐭ヨ瘑搴撻€夋嫨鏈嶅姟
|   `-- resource_service.py      宸插惎鐢ㄨ祫婧愯В鏋愭湇鍔?|-- knowledge/
|   |-- backends/
|   |   |-- base.py              Milvus / LightRAG 缁熶竴鐭ヨ瘑搴撴帴鍙?|   |   |-- factory.py           鎸?kb_type 閫夋嫨 backend
|   |   |-- milvus.py            鍘熸湁鍚戦噺鐭ヨ瘑搴撳疄鐜?|   |   `-- lightrag.py          LightRAG + Neo4j 鍥剧煡璇嗗簱瀹炵幇
|   |-- embedding/
|   |   |-- factory.py           Embedding 鏈嶅姟宸ュ巶
|   |   |-- openai.py            OpenAI-compatible Embedding 瀹炵幇
|   |   `-- mock.py              鏈湴寮€鍙?mock Embedding
|   |-- parser/
|   |   `-- factory.py           鏂囨。杞?Markdown 瑙ｆ瀽鍏ュ彛
|   |-- rerank/
|   |   |-- factory.py           Rerank 鏈嶅姟宸ュ巶
|   |   `-- http.py              OpenAI-compatible / DashScope Rerank 瀹炵幇
|   `-- chunking/
|       `-- ragflow_like/        澶氱瓥鐣?Markdown 鍒嗗潡
|-- storage/
|   |-- base.py                  瀵硅薄瀛樺偍鎶借薄
|   |-- factory.py               瀛樺偍鏈嶅姟宸ュ巶
|   |-- minio.py                 MinIO 瀵硅薄瀛樺偍瀹炵幇
|   `-- redis/                   Redis runtime cache client helpers
|-- graph/
|   |-- builder.py           鏃у吋瀹瑰叆鍙ｏ紝杞彂鍒?agents/buildin/chatbot/graph.py
|   |-- prompt.py            鏃у吋瀹瑰叆鍙ｏ紝杞彂鍒?agents/buildin/chatbot/prompt.py
|   `-- middleware/          LangChain AgentMiddleware
|-- llm/
|   |-- base.py              BaseChatModel 鍒悕
|   |-- chat_model.py        OpenAI-compatible / mock ChatModel
|   |-- factory.py           chat_model / deep_research_model 工厂
|   `-- providers/           Yuxi-style model_providers 配置、缓存和运行时解析
`-- plugins/
    |-- types.py             璧勬簮绫诲瀷鍜岃祫婧?schema
    `-- registry.py          鍐呯疆璧勬簮绉嶅瓙鏁版嵁涓庡悕绉拌В鏋?
```

娌欑洅璋冪敤閾撅細

```text
SandboxMiddleware 鑷姩娉ㄥ叆 sandbox_read_file / sandbox_write_file / sandbox_ls / sandbox_glob / sandbox_grep
  -> SandboxMiddleware 鎸佷箙鍖?sandbox_id
  -> ProvisionerSandboxProvider 鎸?user_id + conversation_id 鑾峰彇娌欑洅
  -> HTTP 璋冪敤 sandbox-provisioner
  -> provisioner 鍔ㄦ€佸垱寤烘垨澶嶇敤 Docker 瀹瑰櫒
  -> agent-sandbox 鏂囦欢 API 鎵ц鍙楁帶鏂囦欢鎿嶄綔
  -> workspace/outputs 鍐欏叆瀹夸富鎸佷箙鍖栫洰褰?
```

娌欑洅铏氭嫙鏂囦欢绯荤粺锛?

```text
/mnt/user-data/workspace   鐢ㄦ埛绾у叡浜紝鍙啓
/mnt/user-data/uploads     浼氳瘽绾э紝鍙
/mnt/user-data/outputs     浼氳瘽绾э紝鍙啓
/mnt/skills                褰撳墠浼氳瘽鍙 Skill锛屽彧璇?
```

`docker/sandbox_provisioner` 鏄嫭绔?FastAPI 鏈嶅姟锛岄粯璁ょ洃鍚涓绘満
`127.0.0.1:8002`銆傜鐞嗘帴鍙ｉ渶瑕?`X-Sandbox-Token`锛屽姩鎬佹矙鐩掔鍙ｄ篃鍙粦瀹氬洖鐜湴鍧€銆?

## 3. 鍓嶇鍦板浘

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
    |   |-- ModelProviderView.vue
    |   |-- ProviderIcon.vue
    |   `-- WorkspaceSidebar.vue
    `-- views/
        `-- HomeView.vue
```

## 4. 鍏抽敭鍚庣鑱岃矗

`api/routes/chat.py` 鍙繚鐣?HTTP 鍏ュ彛鑱岃矗锛?

```text
鎺ユ敹 ChatRequest
  -> 璋冪敤 AgentRuntime.run
  -> 鎶?ValueError 杞垚 HTTPException
```

`agents/buildin/chatbot/runtime.py` 璐熻矗涓€娆″畬鏁存櫤鑳藉姪鎵嬭繍琛岀紪鎺掋€備富鍥炵瓟鐩存帴娑堣垂鐖?LangGraph `astream(messages, values)` 鐨?`AIMessageChunk` 鎺ㄩ€?SSE锛岀粨鏉熷悗浠?checkpoint state 璇诲彇鏈€缁堢粨鏋滃苟淇濆瓨銆傚伐鍏疯繃绋嬮噰鐢?Yuxi 椋庢牸鐨勬秷鎭唴 `tool_calls`锛歋SE 鎸夌ǔ瀹氳皟鐢?ID 鏇存柊涓存椂璋冪敤锛屾渶缁堜互鍚屼竴缁撴瀯淇濆瓨鍒?assistant metadata锛涘瓙浠诲姟宸ュ叿鍜屾枃鏈寜鐖?`task` 璋冪敤宓屽灞曠ず銆?
```text
璋冪敤 ConversationService 鍑嗗浼氳瘽鍜屾秷鎭?
璋冪敤 SelectionService 璇诲彇鐢ㄦ埛鐭ヨ瘑搴撻€夋嫨
璋冪敤 ResourceService 瑙ｆ瀽宸插惎鐢ㄨ祫婧?鏋勫缓 AgentContext
璋冪敤 create_agent 鐢熸垚鐨?agent
濮旀墭 ConversationService 淇濆瓨 assistant 鍥炲骞舵瀯閫犲搷搴?
```

鍙充晶宸ヤ綔鍖洪€夋嫨鐭ヨ瘑搴撳悗锛岄€氳繃 selections API 灏?`knowledge_base_ids` 淇濆瓨鍒?
`user_selections`銆傝亰澶╄繍琛屾椂璇诲彇璇ュ瓧娈靛苟鍐欏叆 `AgentContext.knowledge_base_ids`锛?
鐭ヨ瘑搴撳伐鍏峰彧鍏佽鏌ヨ杩欎釜 ID 鍒楄〃鍐呬笖灞炰簬褰撳墠 `user_id` 鐨勭煡璇嗗簱銆?

`services/` 璐熻矗涓氬姟娴佺▼锛?

```text
ConversationService  浼氳瘽鍒涘缓銆佹秷鎭繚瀛樸€佸巻鍙叉秷鎭浆鎹€佽亰澶╁搷搴旀瀯閫?
SelectionService     鐢ㄦ埛鐭ヨ瘑搴撻€夋嫨璇诲彇鍜岄粯璁ゅ€煎鐞?
ResourceService      宸插惎鐢?MCP / Tool 涓庣嫭绔?Skill 璧勬簮瑙ｆ瀽
```

`agents/buildin/chatbot/graph.py` 鍙礋璐ｆ櫤鑳藉姪鎵?agent 鏋勫缓锛?

```text
閫夋嫨妯″瀷鐢ㄩ€?model_use
鍔犺浇瀵瑰簲 BaseChatModel
鎸傝浇 AgentMiddleware
graph 鍒涘缓鏃舵敞鍏ュ綋鍓嶇敤鎴峰凡鍚敤鐨勬櫘閫?Tool/MCP锛宮iddleware 鑷姩鎻愪緵鑷韩宸ュ叿
杩斿洖 compiled agent
```

`agents/toolkits/` 缁熶竴璐熻矗绯荤粺宸ュ叿锛?

```text
registry.py               YUXI 椋庢牸 @tool 瑁呴グ鍣ㄣ€乀ool 瀹炰緥鍜屽睍绀哄厓鏁版嵁
resolver.py               鏍规嵁 AgentContext.tools 閫夋嫨褰撳墠宸叉巿鏉?Tools
governance.py             宸ュ叿璋冪敤鐘舵€併€佺粨鏋滃拰浜嬩欢璁板綍
buildin/tools.py          ask_user_question / present_artifacts / tavily_search
buildin/install_skill.py  install_skill
external/exchange_rate/   exchange_rate 澶栭儴鍙傝€冩眹鐜?Tool銆乻chema 涓?HTTP client
buildin/subagent/tools.py middleware-owned task subagent delegation tool
kbs/tools.py              list_kbs / query_kb
```

搴旂敤鍚姩鏃?`seed_builtin_resources` 浼氫粠娉ㄥ唽琛ㄨ嚜鍔ㄥ悓姝?`category="buildin"` 鐨勫伐鍏疯祫婧愶紝
鍥犳鏂板鍐呯疆宸ュ叿涓嶉渶瑕佸啀鎵嬪伐缁存姢鍙︿竴浠借祫婧愭竻鍗曪紱棣栨娉ㄥ唽鎴栭粯璁ょ瓥鐣ョ増鏈縼绉绘椂寮€鍚紝
鍓嶇鏄剧ず鈥滃唴缃伐鍏封€濇爣绛撅紝鍚庣画绠＄悊鍛樺紑鍏充笉浼氳搴旂敤閲嶅惎瑕嗙洊銆?

`ask_user_question` 浣跨敤 LangGraph `interrupt` 璇箟锛涘唴缃伐鍏烽娆℃敞鍐屾椂缁熶竴榛樿寮€鍚€?
鍏朵腑浜や簰鎻愰棶浠嶉渶瑕佸墠绔棶棰樺崱鐗囧拰浼氳瘽鎭㈠鍗忚閰嶅悎锛岀鐞嗗憳鍙湪鎵╁睍绠＄悊椤垫寜瀹為檯鑳藉姏鍏抽棴銆?

`agents/middlewares/` 缁熶竴璐熻矗渚?Agent 妯″瀷璋冪敤浣跨敤鐨勪腑闂翠欢锛?

```text
ToolCallLimitMiddleware    缁熶竴闄愬埗鍗曟 Agent 杩愯鐨勫伐鍏疯皟鐢ㄦ€绘暟
KnowledgeBaseMiddleware    娉ㄥ唽 list_kbs / query_kb 鐭ヨ瘑搴撳伐鍏?
SkillsMiddleware          鐢熷懡鍛ㄦ湡鍐呯洿鎺ユ煡璇?Skill Repository锛屾敞鍏?prompt銆佸睍寮€渚濊禆骞跺鐞嗗姩鎬佹縺娲?
RuntimeConfigMiddleware   姣忔妯″瀷璋冪敤璇诲彇 context.system_prompt锛屽苟瑕嗙洊鏈妯″瀷璇锋眰
ToolOutputBudgetMiddleware controls oversized ToolMessage output by saving full content under `.minibot/tool_outputs` and keeping a compact preview in messages
SummaryMiddleware          controls long conversation history only; it generates rolling summaries and trims old messages, but does not offload tool output
RuntimePromptMiddleware    姣忔妯″瀷璋冪敤鍓嶅閲忚拷鍔犺祫婧愬拰宸ュ叿绛栫暐
```

Tool/MCP 瑁呴厤閲囩敤涓ゅ眰锛氬綋鍓嶇敤鎴峰凡鍚敤鐨勬櫘閫?Tool/MCP 鍦?graph 鍒涘缓鏃剁洿鎺ユ敞鍏ワ紱
middleware 鑷甫 Tool 鐢?LangChain 鑷姩鏀堕泦锛汼kill 浠呭湪璇诲彇 `/mnt/skills/<slug>/SKILL.md`
骞舵縺娲诲悗锛屾墠鐢?`SkillsMiddleware` 鍦ㄥ悗缁ā鍨嬭皟鐢ㄤ腑鍔ㄦ€佽拷鍔犲叾渚濊禆 Tool/MCP銆?
`llm/` 璐熻矗妯″瀷绠＄悊锛?

```text
chat_model             褰撳墠鑱婂ぉ妯″瀷
deep_research_model    棰勭暀娣卞害鐮旂┒妯″瀷
mock                   鏈湴寮€鍙戦粯璁ゆā鍨?
openai-compatible      鍏煎 OpenAI Chat Completions 鐨勬ā鍨嬫湇鍔?
```

OpenAI-compatible 妯″瀷璇诲彇瓒呮椂鐢?`MINIBOT_OPENAI_TIMEOUT_SECONDS` 鎺у埗锛?
榛樿 180 绉掞紱瓒呮椂浼氳浆鎹负鍙繚瀛樸€佸彲杩斿洖鐨?`model_timeout` 缁撴灉銆?

## 5. 鏁版嵁搴撳湴鍥?

妯″瀷瀹氫箟锛歚backend/app/db/models.py`

褰撳墠鏍稿績琛細

```text
plugin_resources
skills
model_providers
model_use_configs
user_selections
conversations
conversation_messages
agent_runs锛堢埗 Agent 涓庡瓙 Agent 杩愯璁板綍銆侀€昏緫 thread_id銆佺姸鎬佸拰缁撴灉锛?LangGraph checkpoint 琛紙鐢?AsyncPostgresSaver 鑷姩鍒涘缓涓庤縼绉伙級
knowledge_bases
knowledge_documents
user_selections.knowledge_base_ids
```

褰撳墠娌℃湁 Alembic 杩佺Щ绯荤粺锛屽簲鐢ㄥ惎鍔ㄦ椂閫氳繃 `Base.metadata.create_all` 鍒涘缓缂哄け琛ㄣ€?

## 6. API 鍦板浘

```text
GET    /api/health
GET    /api/resources?kind=mcp|tool
POST   /api/resources
POST   /api/resources/{name}/mcp/test
GET    /api/resources/{name}/mcp/tools
POST   /api/resources/{name}/mcp/refresh
PUT    /api/resources/{name}/mcp/tools/{tool_name}?enabled=true|false
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
POST   /api/chat/runs
GET    /api/chat/runs/{run_id}?user_id=default
GET    /api/chat/runs/{run_id}/events?user_id=default
GET    /api/chat/conversations/{conversation_id}/active-run?user_id=default
GET    /api/model-providers
POST   /api/model-providers
GET    /api/model-providers/{provider_id}
PUT    /api/model-providers/{provider_id}
DELETE /api/model-providers/{provider_id}
GET    /api/model-providers/{provider_id}/remote-models
POST   /api/model-providers/test-credentials
POST   /api/model-providers/{provider_id}/models/test
POST   /api/model-providers/models/cache/refresh
GET    /api/model-providers/models/v2?model_type=chat|embedding|rerank
GET    /api/model-providers/models/status?spec=provider_id:model_id
GET    /api/model-providers/model-uses
PUT    /api/model-providers/model-uses/{model_use}
GET    /api/knowledge-bases?user_id=default
POST   /api/knowledge-bases
GET    /api/knowledge-chunk-presets
GET    /api/knowledge-bases/{knowledge_base_id}/documents?user_id=default
GET    /api/knowledge-bases/{knowledge_base_id}/query-params?user_id=default
PUT    /api/knowledge-bases/{knowledge_base_id}/query-params
POST   /api/knowledge-bases/{knowledge_base_id}/query-test
POST   /api/knowledge-bases/{knowledge_base_id}/documents?user_id=default
POST   /api/knowledge-bases/{knowledge_base_id}/evaluation/datasets/generate
DELETE /api/knowledge-documents/{document_id}?user_id=default
```

## 7. 甯歌浠诲姟瀹氫綅

淇敼鑱婂ぉ杩愯娴佺▼锛?
- `backend/app/agents/buildin/chatbot/runtime.py`
- `backend/app/services/`
- `backend/app/api/routes/chat.py`

淇敼 agent 鏋勫缓鍜?middleware锛?
- `backend/app/agents/buildin/chatbot/graph.py`
- `backend/app/agents/middlewares/`
- `backend/app/agents/buildin/chatbot/context.py`

淇敼涓婁笅鏂囧帇缂╋細
- `backend/app/agents/middlewares/summary_middleware.py`
- `backend/app/agents/middlewares/tool_output_budget.py`
- `backend/app/agents/buildin/chatbot/context.py`
- `backend/app/core/config.py`

淇敼鎻愮ず璇嶏細
- `backend/app/agents/buildin/chatbot/prompt.py`
- `backend/app/core/config.py`

淇敼妯″瀷鎺ュ叆锛?
- `backend/app/llm/factory.py`
- `backend/app/llm/chat_model.py`
- `.env.example`

淇敼杩愯鏃跺伐鍏凤細
- `backend/app/agents/toolkits/`
- `backend/app/agents/middlewares/runtime_config.py`
- `backend/app/plugins/registry.py`
- `backend/app/agents/buildin/chatbot/prompt.py`

淇敼宸︿晶鍘嗗彶瀵硅瘽锛?
- `frontend/src/components/ConversationSidebar.vue`
- `frontend/src/stores/conversationStore.js`
- `backend/app/api/routes/conversations.py`

淇敼涓棿鑱婂ぉ UI锛?
- `frontend/src/components/ChatBox.vue`
- `frontend/src/components/MarkdownMessage.vue`
- `frontend/src/styles.css`

淇敼鍙充晶宸ヤ綔鍖猴細
- `frontend/src/components/WorkspaceSidebar.vue`
- `frontend/src/stores/selectionStore.js`

淇敼鎵╁睍绠＄悊锛?
- `frontend/src/components/ExtensionManagementView.vue`
- `frontend/src/components/ConversationSidebar.vue`
- `frontend/src/apis/resources.js`

淇敼鐭ヨ瘑搴撲笂浼犲拰瑙ｆ瀽锛?
- `backend/app/api/routes/knowledge.py`
- `backend/app/services/knowledge_service.py`
- `backend/app/knowledge/chunking/ragflow_like/dispatcher.py`
- `backend/app/knowledge/chunking/ragflow_like/parsers/`
- `backend/app/knowledge/parser/factory.py`
- `backend/app/storage/`
- `backend/app/db/models.py`

鐭ヨ瘑搴撴枃妗ｄ笂浼犻噰鐢ㄨ繘绋嬪唴鍚庡彴绱㈠紩锛?

```text
POST 涓婁紶
  -> MinIO 淇濆瓨鍘熸枃浠?
  -> PostgreSQL 鍒涘缓 status=uploaded 鐨勬枃妗?
  -> 鎺ュ彛绔嬪嵆杩斿洖
  -> FastAPI BackgroundTasks 浣跨敤鐙珛 AsyncSession
  -> 瑙ｆ瀽銆佸垎鍧椼€乪mbedding / LightRAG 寤哄浘
  -> status=indexed 鎴?failed
  -> 鍓嶇姣?3 绉掕疆璇㈠鐞嗕腑鐘舵€?
```

鍚庡彴浠诲姟涓嶅鐢ㄨ姹傛暟鎹簱浼氳瘽銆傛绱㈡湇鍔″彧鏌ヨ `status=indexed` 鐨勬枃妗ｏ紝閬垮厤绱㈠紩涓殑閮ㄥ垎鏁版嵁鍙備笌闂瓟銆?
褰撳墠瀹炵幇鏄崟杩涚▼鍐呬换鍔★紝鏈嶅姟閲嶅惎涓嶄細鑷姩鎭㈠鏈畬鎴愪换鍔★紱闇€瑕佹寔涔呭寲浠诲姟鎭㈠鏃跺啀鎺ュ叆 Redis/ARQ銆?

鐭ヨ瘑搴撲笌鏂囨。鍒犻櫎閾捐矾锛?

```text
鍓嶇浜屾纭
  -> 妫€鏌ユ枃妗ｆ槸鍚﹀浜庡鐞嗕腑锛屽鐞嗕腑杩斿洖 409
  -> backend 娓呯悊 Milvus collection 鎴?LightRAG 鏂囨。/鍥捐氨/鍚戦噺鏁版嵁
  -> MinIO 鍒犻櫎鏂囨。瀵硅薄鎴?knowledge-bases/{kb_id}/ 鍓嶇紑
  -> 鍒犻櫎 user_selections 涓殑鐭ヨ瘑搴撳紩鐢?
  -> PostgreSQL 绾ц仈鍒犻櫎 knowledge_bases / documents / chunks
```

瀵瑰簲鎺ュ彛涓?`DELETE /api/knowledge-bases/{knowledge_base_id}` 鍜?
`DELETE /api/knowledge-documents/{document_id}`銆?

## 8. 鐭ヨ瘑搴撳垎鍧楄ˉ鍏?

褰撳墠鐭ヨ瘑搴撲笂浼犻摼璺湪 Markdown 瑙ｆ瀽鍚庯紝浼氳鍙栫煡璇嗗簱 `metadata` 涓繚瀛樼殑
`chunk_preset_id` 鍜?`chunk_parser_config`锛屾墽琛屽搴斿垎鍧楃瓥鐣ワ細

```text
Markdown
  -> backend/app/knowledge/chunking/ragflow_like/dispatcher.py
  -> general / separator / book / laws / qa
  -> knowledge_chunks
  -> 鎸?kb_type 鍒嗘淳
     -> milvus: embedding + Milvus dense/BM25
     -> lightrag: LightRAG 鐙珛 Milvus collections + Neo4j
  -> knowledge_documents.status=indexed
```

`kb_type` 褰撳墠鏀寔 `milvus` 鍜?`lightrag`锛屼繚瀛樺湪 `knowledge_bases.metadata` 涓紱
鏃х煡璇嗗簱缂哄皯璇ュ瓧娈垫椂鎸?`milvus` 澶勭悊銆侺ightRAG backend 鎸夌煡璇嗗簱缂撳瓨瀹炰緥锛屽苟瀵瑰悓涓€鐭ヨ瘑搴撶殑
鍐欏叆浣跨敤杩涚▼鍐呬覆琛岄攣銆傚杩涚▼閮ㄧ讲鏃堕渶瑕佽繘涓€姝ユ浛鎹负 PostgreSQL advisory lock 鎴?Redis 閿併€?

鍒嗗潡瀹炵幇绉绘骞惰鍓嚜 Yuxi `ragflow_like`銆傚綋鍓嶆湭鎺ュ叆 Semantic 绛栫暐锛屽洜涓哄叾鍚屾 embedding銆?
NLTK 鍜?scikit-learn 渚濊禆涓?miniBOT 褰撳墠寮傛 embedding 閾捐矾涓嶇洿鎺ュ吋瀹广€傜涓夋柟璁稿彲淇濆瓨鍦?
`backend/app/knowledge/chunking/ragflow_like/YUXI_LICENSE`銆?

鏂板鏁版嵁琛細

```text
knowledge_chunks
```

`knowledge_chunks` 鍙繚瀛?chunk 鍏冩暟鎹€侀『搴忓拰瀛楃浣嶇疆锛沜hunk 姝ｆ枃鍜屽悜閲忕敱 Milvus collection 淇濆瓨銆?

Milvus collection 鐨?`content` 瀛楁鍚敤 Chinese analyzer锛屽苟閫氳繃鍐呯疆 BM25 Function 鑷姩鐢熸垚
`content_sparse`銆俙embedding` 鍜?`content_sparse` 鍒嗗埆浣跨敤 COSINE vector 绱㈠紩鍜?BM25 sparse 绱㈠紩銆?

鐭ヨ瘑搴撴煡璇㈤摼璺細

```text
鐭ヨ瘑搴?middleware 瑙ｆ瀽鏈疆鍚敤璧勬簮
  -> AgentContext.knowledge_base_ids
  -> middleware 娉ㄥ叆 list_kbs / query_kb
  -> Agent ToolRuntime 璋冪敤 query_kb
  -> backend/app/agents/toolkits/kbs/tools.py
  -> backend/app/services/knowledge_retrieval_service.py
  -> query embedding
  -> Milvus vector / keyword / hybrid search
  -> 杩斿洖 chunk銆佹枃妗ｅ悕銆乻core 鍜?citation_id
```

`query_kb` 榛樿璇诲彇 `knowledge_bases.metadata.query_params.options` 涓繚瀛樼殑鐭ヨ瘑搴撶骇妫€绱㈤厤缃紱
鏈繚瀛橀厤缃椂鍥為€€鍒?hybrid 绛夌郴缁熼粯璁ゅ€笺€傚簳灞傞€氳繃 `WeightedRanker` 铻嶅悎 vector 鍜?BM25 缁撴灉銆?Milvus 鏌ヨ灞傚弬鑰?Yuxi 瀹炵幇锛屾敮鎸?`search_mode`銆乣final_top_k`銆乣recall_top_k`銆?`similarity_threshold`銆乣bm25_top_k`銆乣vector_weight`銆乣bm25_weight`銆?`bm25_drop_ratio_search`銆乣include_distances` 鍜屾枃妗ｈ繃婊ゃ€?
褰?`MINIBOT_RERANK_ENABLED=true` 鏃讹紝妫€绱㈡湇鍔′細鍏堟寜 `recall_top_k` 澶氬彫鍥炲€欓€夛紝鍐嶈皟鐢?`backend/app/knowledge/rerank` 涓殑 reranker 瀵?chunk 鍐呭绮炬帓锛岀粨鏋滃啓鍏?`rerank_score`銆?Rerank 璋冪敤澶辫触鏃舵部鐢?Yuxi 鐨勯檷绾ф€濊矾锛屼繚鐣欏師濮嬫绱㈡帓搴忕户缁繑鍥炵粨鏋溿€?
缁熶竴妫€绱㈢粨鏋滈噰鐢?`content + metadata + score` 缁撴瀯锛宍metadata` 涓寘鍚潵婧愭枃妗ｃ€乧hunk銆佺煡璇嗗簱鍜?`citation_id`銆俙KnowledgeRetrievalService` 鏍规嵁鐭ヨ瘑搴?`kb_type` 璋冪敤瀵瑰簲 backend锛?涓嶆妸 LightRAG 閫昏緫鍐欏叆 `MilvusVectorStore`銆?

鐭ヨ瘑搴撳伐鍏峰彧鏍规嵁 `ToolRuntime.context` 涓殑 `user_id` 鍜?`knowledge_base_ids` 纭畾璁块棶鑼冨洿锛?
涓嶆帴鍙楁ā鍨嬩紶鍏ョ殑鐢ㄦ埛韬唤鎴?collection 鍚嶇О銆?

鍙敱 Agent middleware 鐩存帴娉ㄥ叆鐨勭煡璇嗗簱宸ュ叿浣嶄簬锛?

```text
backend/app/agents/toolkits/kbs/tools.py
```

褰撳墠鎻愪緵锛?

```text
list_kbs   鍒楀嚭褰撳墠浼氳瘽鍚敤涓旂敤鎴锋湁鏉冭闂殑鐭ヨ瘑搴?
query_kb   鎸?kb_id銆乹uery_text 鍜屽彲閫?file_name 鏌ヨ鐭ヨ瘑搴?
```

`query_kb` 浣跨敤 LangGraph `ToolRuntime` 浠?`AgentContext` 鑾峰彇 `user_id` 鍜?
`knowledge_base_ids`锛屼笉浼氭妸鐢ㄦ埛韬唤鏆撮湶涓烘ā鍨嬪伐鍏峰弬鏁般€俙KnowledgeBaseMiddleware`
閫氳繃 `get_kb_tools()` 灏嗗伐鍏锋敞鍐屽埌 agent锛岃闂寖鍥翠粛鐢?`AgentContext` 鎺у埗銆?

鏂板鎺ュ彛锛?

```text
GET /api/knowledge-documents/{document_id}/chunks?user_id=default
GET /api/knowledge-bases/{knowledge_base_id}/query-params?user_id=default
PUT /api/knowledge-bases/{knowledge_base_id}/query-params
POST /api/knowledge-bases/{knowledge_base_id}/query-test
```
- `backend/app/db/repositories.py`

## 异步聊天 Run 数据流

```text
ChatBox / conversationStore
  -> POST /api/chat/runs（保存 user 消息与 pending agent_run）
  -> ChatRunManager 在浏览器请求之外执行 AgentRuntime.run_prepared_stream
  -> Redis Stream 保存 token/tool/subagent/done/end 事件
  -> GET /api/chat/runs/{run_id}/events + Last-Event-ID 续传
  -> assistant 消息落 PostgreSQL 后将 agent_run 标记为终态
  -> 页面刷新后查询 conversation active-run 并恢复订阅
```

`/api/chat/stream` 继续保留为兼容入口；当前 Web UI 默认使用异步 Run。

## 8. 楠岃瘉鍛戒护

鍓嶇锛?

```powershell
cd frontend
npm run build
```

鍚庣锛?

```powershell
cd backend
.\.venv\Scripts\python.exe -m compileall app
.\.venv\Scripts\python.exe -c "from app.main import app; print(app.title)"
```
