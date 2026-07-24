# Voyager：面向个性化旅游规划的 Multi-Agent 智能决策系统

> 基于 **LangGraph** 构建的多智能体旅游规划系统：你用一句话描述出行需求，多个领域专家分工协作，自动完成天气、景点、酒店、交通的一站式规划，最终输出结构化、可落地的个性化旅行方案。

---

## 📖 项目简介

Voyager 是一套面向个性化旅游规划场景的多智能体（Multi-Agent）智能决策系统。它以自然语言为唯一入口，将一次复杂的旅行规划自动拆解为多个子任务，交由一组专精智能体协同求解，端到端地生成结构化、可落地的个性化行程方案。

区别于单体大模型的“一步到位式”生成，Voyager 以多智能体协作为核心，融合真实工具调用与跨会话长期记忆，系统性地应对旅游规划中数据失真、行程冲突与偏好遗忘等痛点，在真实性、可解释性与个性化之间取得平衡。

---

## ✨ 核心亮点

| 亮点 | 说明 |
| --- | --- |
| 🧠 **多智能体协同架构** | 基于“黑板”协作模式，多个专精智能体围绕共享上下文分工协作，职责清晰、可解释、易扩展。 |
| 🎬 **动态编排与自愈调度** | 智能主持人依据任务进度动态编排执行路径，并在异常时自动降级兜底，保障流程稳定收敛。 |
| 🌍 **真实数据驱动** | 全流程对接高德地图与实时天气服务，从源头杜绝景点、酒店与路线的模型幻觉。 |
| 🗂️ **分层记忆体系** | 短期会话记忆与长期偏好记忆双层设计，持续沉淀用户画像，让系统越用越懂你。 |
| 📈 **经验自学习闭环** | 自动从工具调用中提炼可复用经验并长期留存，驱动系统持续自我进化。 |
| 🔭 **工程化与可观测** | 内置模型多活容灾、工具重试与全链路审计追踪，具备工程级的健壮性与可维护性。 |


---

## 🧰 技术栈

| 分类 | 技术 |
| --- | --- |
| 编排框架 | **LangGraph** 1.2.x（StateGraph / 条件路由 / 检查点） |
| LLM 框架 | **LangChain** 1.3.x |
| 模型接入 | `langchain-openai`（OpenAI 兼容接口，主 + 备双模型回退） |
| 工具协议 | **MCP**（`langchain-mcp-adapters`）+ **高德地图 MCP Server** |
| 长期记忆 | **mem0**（用户偏好 + 工具经验） |
| 持久化 | **PostgreSQL**（检查点 / 审计 / 会话摘要），可选 SQLite / InMemory |
| 可观测性 | **LangSmith** |
| 交互界面 | **LangGraph Agent Chat UI** |
| 运行环境 | Python ≥ 3.11 |

---

## 📁 项目结构

```
trip_plan_assistant/
├── backend/
│   ├── app/
│   │   ├── agents/
│   │   │   └── trip_plan_agent.py      # 主持人 + 四专家 + 汇总 + 记忆节点
│   │   ├── base/
│   │   │   ├── agent.py                # BaseAgent：ReAct 工具循环
│   │   │   └── base.py                 # 状态与数据模型（RoundRobinState / TripPlan …）
│   │   ├── config/
│   │   │   ├── mcpServers.json         # MCP 服务器（高德地图）
│   │   │   ├── tool_registry.yaml      # 工具注册表
│   │   │   └── agent_permissions.yaml  # 各专家的工具权限
│   │   ├── models/
│   │   │   ├── llm_factory.py          # 主/备模型工厂 + 自动回退
│   │   │   ├── schemas.py              # Pydantic 结构化输出模型
│   │   │   └── prompt.py
│   │   ├── services/
│   │   │   ├── mcp_client_manager.py   # MCP 客户端连接管理
│   │   │   ├── tool_manager.py         # Agent 级工具权限管理
│   │   │   ├── tool_executor.py        # 工具并发执行 + 重试 + 审计
│   │   │   └── memory_service.py       # mem0 + PostgreSQL 双层记忆
│   │   ├── graph.py                    # LangGraph 入口（langgraph.json 引用）
│   │   └── graph_builder.py            # 构建并编译 StateGraph
│   ├── langgraph.json                  # LangGraph 部署配置
│   ├── init.sql                        # 数据库表结构
│   └── .env                            # 环境变量（需自行创建，已 gitignore）
├── requirements.txt
└── README.md
```

---

## 🚀 快速开始

Voyager 的推荐运行方式是：用 `langgraph dev` 启动后端图服务，再用 **LangGraph Agent Chat UI** 作为对话前端。

### 1. 环境要求

- **Python** ≥ 3.11
- **PostgreSQL** ≥ 12（用于检查点 / 工具审计 / 会话摘要）
- **高德地图 API Key**（需开通 Web 服务 & MCP）→ https://console.amap.com/
- **OpenAI 兼容的 LLM API**（主 + 备各一套）
- **mem0 API Key**（云端长期记忆）→ https://app.mem0.ai/
- **Node.js** ≥ 18（仅当选择本地运行 Agent Chat UI 时需要）
- **LangSmith API Key**（可选，用于链路追踪）

### 2. 安装依赖

```bash
# 克隆项目
git clone <your-repo-url>
cd trip_plan_assistant

# 建议使用虚拟环境
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
# 或 .venv\Scripts\activate      # Windows CMD/PowerShell
# 或 source .venv/bin/activate    # macOS / Linux

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置环境变量

在 **`backend/`** 目录下创建 `.env` 文件（可参考根目录 `.env.example`）：

```dotenv
# ===== 主 LLM（OpenAI 兼容接口）=====
MODEL=your_primary_model
OPENAI_API_KEY=your_openai_api_key
BASE_URL=your_openai_base_url

# ===== 备用 LLM（主模型故障时自动回退）=====
MODEL_BACKUP=your_backup_model
OPENAI_API_KEY_BACKUP=your_backup_api_key
BASE_URL_BACKUP=your_backup_base_url

# ===== mem0 云端长期记忆 =====
MEMORY_API_KEY=your_mem0_api_key

# ===== 高德地图 MCP =====
AMAP_API_KEY=your_amap_api_key

# ===== PostgreSQL（检查点 / 审计 / 会话摘要）=====
POSTGRES_URL=postgresql://postgres:postgre@localhost:5432/agent

# ===== 记忆 / 检查点类型：memory | sqlite | postgres =====
MEMORY_TYPE=postgres

# ===== 配置文件路径（相对 backend 目录）=====
TOOL_REGISTRY_PATH=./app/config/tool_registry.yaml
AGENT_PERMISSIONS_PATH=./app/config/agent_permissions.yaml
MCP_SERVERS_PATH=./app/config/mcpServers.json

# ===== LangSmith 链路追踪（可选）=====
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=your_langsmith_api_key
LANGSMITH_PROJECT=trip_plan_agent
```


### 4. 启动后端图服务

在 **`backend/`** 目录下（`langgraph.json` 所在目录）运行：

```bash
cd backend
langgraph dev
```

启动成功后会看到：

- 🚀 **API 地址**：`http://127.0.0.1:2024`
- 📚 **API 文档**：`http://127.0.0.1:2024/docs`
- 🎨 **LangGraph Studio**：会自动在浏览器打开

其中已注册的 Graph（Assistant）ID 为 **`trip_agent`**（见 `langgraph.json`）。

### 5. 连接 Agent Chat UI

启动后端后，用 LangGraph 官方的 **Agent Chat UI** 作为对话前端。二选一：

#### 方式 A：使用官方托管版（最快）

1. 打开 https://agentchat.vercel.app/
2. 填写连接信息：
   - **Deployment URL**：`http://127.0.0.1:2024`
   - **Assistant / Graph ID**：`trip_agent`
   - **LangSmith API Key**：本地开发可留空
3. 点击进入，开始对话。

#### 方式 B：本地运行 Agent Chat UI

```bash
# 克隆官方仓库
git clone https://github.com/langchain-ai/agent-chat-ui.git
cd agent-chat-ui

# 安装并启动
pnpm install
pnpm dev
```

打开 `http://localhost:3000`，填入与上面相同的连接信息（Deployment URL = `http://127.0.0.1:2024`，Graph ID = `trip_agent`）即可。

### 6. 开始规划 🎉

在对话框中输入你的需求，例如：

> 我下周想去重庆玩 3 天，喜欢吃辣、预算不高，帮我规划一下。

Voyager 会依次调度天气 → 景点 → 酒店 → 交通专家采集真实数据，最终由汇总专家产出一份结构化的多日行程方案，并记住你的偏好用于后续规划。

---

## 💡 运行提示

- **务必在 `backend/` 目录下执行 `langgraph dev`**：`.env` 中的配置文件路径为相对路径（`./app/config/...`），需要以 `backend` 作为工作目录。
- **PostgreSQL 与 mem0 为硬依赖**：`app.graph` 在导入时即会初始化数据库连接、mem0 客户端与高德 MCP 连接，请确保三者均可用后再启动。
- **首次连接高德 MCP** 需要网络可访问 `https://mcp.amap.com`，并确保 `AMAP_API_KEY` 已开通对应权限。
- 如需更轻量的本地调试，可将 `MEMORY_TYPE` 改为 `sqlite` 或 `memory`（注意：mem0 记忆与 PostgreSQL 审计/摘要仍需相应配置）。

---

## 🔧 可扩展性

得益于配置化的工具与权限体系，Voyager 很容易扩展：

- **新增工具**：在 `app/config/tool_registry.yaml` 注册工具，在 `mcpServers.json` 中接入新的 MCP Server。
- **新增专家**：在 `agent_permissions.yaml` 为新专家分配工具权限，在 `trip_plan_agent.py` 中实现节点并在 `graph_builder.py` 中接入图与路由。
- **切换模型**：修改 `.env` 中的 `MODEL` / `MODEL_BACKUP` 即可，系统会自动处理主备回退。

---

## 📜 License

本项目仅用于学习与研究目的。
