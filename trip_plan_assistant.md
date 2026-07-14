# 旅游助手 Agent — 多 Agent 架构设计

## 第 1 章：项目定位与设计取舍

### ADR-001: 为什么需要 Agent（vs RAG + Prompt）

**对应面试问题**：核心 Q1

**上下文**：用户需求"帮我规划去京都 5 天，预算 1 万，带老人和孩子"需要：多轮信息检索（天气、签证、POI）、多约束推理（预算上限 + 老人出行限制 + 儿童适配）、多方案比较与动态决策。

**决策**：采用 Agent 架构而非单纯 RAG + Prompt。

**理由**：

| 维度 | RAG + Prompt | Agent |
|------|-------------|-------|
| 多步推理 | ❌ 单次生成，无法"先查天气→再排行程→再预算校验" | ✅ Planning 能力支持多步推理 |
| 条件逻辑 | ❌ 无法表达"如果预算超了，先砍住宿再砍活动" | ✅ 可编码条件分支 |
| 工具调用 | ⚠️ 单次调用，失败无法自愈 | ✅ 可重试、可降级、可换 Tool |
| 约束推理 | ❌ 大模型幻觉导致"推荐了 ¥20000 酒店但预算只有 1 万" | ✅ Budget Agent 主动拦截 |
| 状态记忆 | ❌ 每轮请求独立 | ✅ 多轮对话共享 Blackboard |
| 可解释性 | ❌ "黑盒"输出 | ✅ 每个 Agent 输出可追溯 |

**结论**：旅游规划本质上是**约束满足问题（CSP, Constraint Satisfaction Problem）**，Agent 的 Planning + Tool Calling + State 管理能力是 RAG + Prompt 无法替代的。

**后果**：架构复杂度上升，需维护 Agent 状态、Tool 编排、冲突仲裁。

---

### ADR-002: Planning 范式选择

**对应面试问题**：核心 Q2, 加分 B1

**候选方案**：

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **ReAct** | Reason → Act → Observe → 循环 | 简单、单 Agent 可运行 | 长链条推理易丢失目标、Token 消耗大、无法并行 |
| **Plan-and-Execute** | 先生成全局 Plan → 再执行 | 全局视图、可并行执行 | Plan 生成后无法动态调整、面对不确定信息（如酒店满房）失效 |
| **Hierarchical** | 顶层分解 → 子 Agent 各自 ReAct | 兼顾全局与灵活 | 架构最复杂 |
| **混合（本方案）** | Supervisor 做 Plan（分解任务）→ Specialist 做 ReAct（具体执行） | 全局可控 + 局部灵活 | Supervisor 负担重 |

**决策**：采用**混合范式**——Supervisor 负责顶层 Planning（任务分解 + 依赖排序），每个 Specialist Agent 内部采用 ReAct 模式（推理→调用 Tool→观察→再推理）。

**理由**：

1. **旅游规划有明确的子任务边界**：行程、住宿、交通、美食各自独立，适合 Plan-and-Execute 的"先分解"思路
2. **每个子任务需要动态决策**：比如 Dining Agent 要根据"当天在哪个 POI 附近、预算剩多少、用户不吃辣"实时推理，这需要 ReAct 的灵活性
3. **避免纯 ReAct 的 Token 爆炸**：单 Agent ReAct 要维护所有上下文，混合方案中每个 Specialist 只关注自己的上下文

**架构对比**：

```
纯 ReAct:
  User → [Single Agent: Think→Act→Observe×N] → Response
  问题：N 步推理后，Agent 可能"忘记"用户的原始约束

Plan-and-Execute:
  User → [Planner] → Plan → [Executor 1,2,3,...] → Response
  问题：Plan 生成时信息不完整（如不知道酒店是否满房），执行时无法调整

混合（本方案）:
  User → [Supervisor: 分解 + 排序] → [Specialist 1: ReAct] → [Specialist 2: ReAct] → ...
  每个 Specialist 只维护自己的上下文，Supervisor 维护全局视图
```

---

### ADR-003: 为什么选择 Multi-Agent（vs 单 Agent）

**对应面试问题**：加分 B2

**决策**：采用 Supervisor + Specialist 的 Multi-Agent 架构，而非单 Agent 维护所有逻辑。

**理由**：

| 维度 | 单 Agent | Multi-Agent |
|------|---------|-------------|
| 上下文窗口 | 所有逻辑塞进一个 Prompt，Token 爆炸 | 每个 Agent 只维护自己的上下文 |
| 能力演进 | 新增能力 = 改写整个 Prompt | 新增 Agent + 注册，不改动原有逻辑 |
| 冲突解决 | Prompt 内用"if-else"思维链，不可靠 | Budget Agent 主动拦截，确定性高 |
| 并行执行 | ❌ 串行 | ✅ 无依赖的 Agent 可并行 |
| 测试 | 只能端到端测试 | 每个 Agent 可独立单元测试 |
| 可解释性 | "为什么推荐这个酒店？" → 黑盒 | 追踪到 Accommodation Agent 的评分逻辑 |

**什么时候不用 Multi-Agent**：

- 任务简单（如 Q&A、翻译）→ 单 Agent 即可
- 任务强耦合、无法分解 → 单 Agent ReAct 更直接
- 团队规模小、维护成本高 → 单 Agent 启动更快

**什么时候用 Multi-Agent**：

- 任务有明确子领域边界（本项目的行程/住宿/交通/美食）
- 需要约束推理（预算 Agent 作为"守门人"）
- 需要并行加速（无依赖的 Agent 可并发）
- 需要独立演进（新增 Activity Agent 不改动其他代码）

---

### ADR-004: 设计原则

**对应面试问题**：核心 Q6

1. **单一职责** — 每个 Agent 只做一件事，且做到最好
2. **松耦合通信** — 通过 Shared Blackboard 交互，不直接耦合
3. **可扩展** — 新增能力 = 新增 Agent + 注册到编排层
4. **可解释** — 每个 Agent 的决策过程对用户可见
5. **容错** — 单个 Agent 失败不阻断整体流程

---

## 第 2 章：总体架构

### 2.1 架构图

```
                    ┌─────────────────────────────────┐
                    │          User (用户)             │
                    └──────────────┬──────────────────┘
                                   │
                    ┌──────────────▼──────────────────┐
                    │                                 │
                    │      Supervisor Agent           │
                    │   (编排 / 意图识别 / 冲突解决)    │
                    │                                 │
                    └────┬──────┬──────┬──────┬───────┘
                         │      │      │      │
              ┌──────────▼──┐ ┌─▼──────▼──────┐ ┌─▼──────────────┐
              │ Itinerary   │ │  Budget       │ │ Accommodation  │
              │  Agent      │ │  Agent        │ │  Agent         │
              │ (行程规划)   │ │ (预算管控)    │ │ (住宿预订)      │
              └─────────────┘ └───────────────┘ └────────────────┘
              ┌──────────┐ ┌─▼──────┐ ┌─▼──────────────┐ ┌─▼──────────┐
              │ Dining   │ │ Transit│ │  Research      │ │ Preference │
              │  Agent   │ │ Agent  │ │   Agent        │ │  Agent     │
              │ (美食)    │ │(交通)  │ │ (信息检索)     │ │ (偏好学习) │
              └──────────┘ └────────┘ └────────────────┘ └────────────┘
                         │
                    ┌────▼──────────────────────────────────┐
                    │           Shared Blackboard            │
                    │  (TripContext / 约束 / 中间结果共享)    │
                    └───────────────────────────────────────┘
                         │
                    ┌────▼──────────────────────────────────┐
                    │         Memory Layer (4层)             │
                    └───────────────────────────────────────┘
```

### 2.2 架构选型对比

**对应面试问题**：核心 Q6

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| **Supervisor + Specialist** | 可控、可解释、冲突好解决 | 编排逻辑集中在 Supervisor | ✅ 旅游助手 |
| 多 Agent 对等协商 | 去中心化、灵活 | 难以收敛、冲突难解决 | 创意头脑风暴 |
| 流水线 (Pipeline) | 简单直接 | 无法回溯、无法并行 | 固定流程 |
| 分层 (Hierarchical) | 适合超大规模 | 架构复杂 | 100+ Agent 的企业级 |

**结论**：旅游规划有明确的子任务边界，适合集中编排、分工执行的模式。

### 2.3 架构演进路线

**对应面试问题**：核心 Q10（如果重新设计，你会怎么做）

```
Phase 1 (当前): 单体 Multi-Agent
  → 所有 Agent 在同一进程，Blackboard 为内存 dict
  → 适合原型验证，启动快、调试方便

Phase 2: 服务化
  → 每个 Agent 独立部署为 FastAPI 服务
  → Blackboard 迁移到 Redis，Agent 间通过 HTTP + pub/sub 通信
  → 独立伸缩：热门 Agent（如 Itinerary）多副本，冷门 Agent 单副本

Phase 3: 流式处理
  → Agent 间通信改为 Event Streaming（Kafka / NATS）
  → Blackboard → 有状态存储（DynamoDB / Postgres with pg_notify）
  → 支持百万级并发请求

如果重新设计，我会直接做 Phase 2 的架构，因为：
  1. 单体架构在调试阶段好用，但上线后 Agent 间依赖关系会复杂到无法维护
  2. 独立部署让每个 Agent 可以独立升级、独立回滚
  3. Redis 作为 Blackboard 天然支持 Pub/Sub，不需要额外改造
  4. 但会保留 Phase 1 的"逻辑架构"——Supervisor + Specialist 的分层不变
```

---

## 第 3 章：Agent 详解

### 0. Supervisor Agent（编排者）

```python
class SupervisorAgent:
    """
    唯一的用户接口 — 意图识别、任务拆解、冲突仲裁、结果汇总。
    不做具体决策，只做协调。
    """

    def __init__(self):
        self.specialists: dict[str, Agent] = {}
        self.blackboard: SharedBlackboard = None

    async def handle(self, user_message: str) -> Response:
        intent = self._classify_intent(user_message)   # 识别意图
        task = self._decompose(intent)                  # 拆解为子任务

        # 按依赖顺序执行子任务
        results = await self._execute(task)

        # 汇总结果，生成回复
        return self._synthesize(results)

    def _resolve_conflict(self, a: AgentResult, b: AgentResult) -> Resolution:
        """当两个 Agent 输出冲突时仲裁（如预算 vs 品质）"""
        ...
```

**核心职责**：

| 职责 | 说明 |
|------|------|
| 意图识别 | 用户说"想去海边" → 分类为 `DESTINATION_SEARCH` |
| 任务拆解 | "帮我去京都玩一周" → [行程] + [住宿] + [交通] + [美食] |
| 依赖排序 | 先查目的地 → 再排行程 → 最后预算评估 |
| 冲突仲裁 | 住宿 Agent 选豪华酒店 vs 预算 Agent 说不够钱 → 权衡 |
| 结果汇总 | 将多个 Agent 的输出合并为一份完整方案 |

---

### 1. Itinerary Agent（行程规划）

```python
class ItineraryAgent:
    """
    行程编排专家 — 根据目的地、天数、偏好，生成每日行程。
    考虑: 地理位置就近、时间合理、节奏适中。
    """

    async def plan(
        self,
        destination: str,
        dates: DateRange,
        constraints: TripConstraints,   # 从 Blackboard 读取
    ) -> list[DayPlan]:
        # 1. 从 Research Agent 获取候选 POI
        # 2. 按用户偏好过滤 (Preference Agent 提供权重)
        # 3. 地理聚类 + 时间窗约束求解
        # 4. 生成逐日行程
        ...
```

**输入**：目的地、天数、同行者、偏好权重  
**输出**：`list[DayPlan]`  
**工具**：地图 API、景点数据库、距离计算  
**依赖**：Research Agent（获取 POI 列表）、Preference Agent（偏好权重）

---

### 2. Budget Agent（预算管控）

```python
class BudgetAgent:
    """
    预算守门人 — 全程跟踪花费，否决超支方案，提出替代。
    """

    def __init__(self, total_budget: Money):
        self.total = total_budget
        self.spent = Money(0)
        self.allocated: dict[str, Money] = {
            "flight": 0, "hotel": 0, "food": 0, "activity": 0
        }

    def allocate(self, category: str, amount: Money) -> bool:
        """申请预算 — 超额则拒绝"""
        if self.allocated[category] + amount > self.total - self.spent:
            return False
        self.allocated[category] += amount
        return True

    def suggest_alternatives(self, item: Booking, max_price: Money) -> list[Booking]:
        """当前选项超预算 → 找更便宜的替代"""
        ...

    def generate_report(self) -> BudgetReport:
        """输出预算使用报告"""
        ...
```

**输入**：总预算、各项消费申请  
**输出**：批准/拒绝 + 替代方案  
**关键特性**：
- **主动否决**：不只是记账，会在其他 Agent 超支时拦截
- **弹性分配**：如果机票便宜了，可以把省下的钱分配给酒店
- **实时报告**：随时可输出"还剩多少钱"

---

### 3. Accommodation Agent（住宿预订）

```python
class AccommodationAgent:
    """
    住宿专家 — 搜索、对比、预订酒店/民宿。
    考虑: 位置(靠近行程)、评分、价格、用户偏好。
    """

    async def search(
        self,
        location: str,
        dates: DateRange,
        budget_per_night: Money,    # 从 Budget Agent 获取
        preferences: list[str],      # 从 Preference Agent 获取
        itinerary: list[DayPlan],    # 从 Itinerary Agent 获取，用于选位置
    ) -> list[HotelOption]:
        # 1. 搜索候选
        # 2. 按位置评分(靠近每日行程中心)
        # 3. 按偏好排序
        # 4. 通过 Budget Agent 验证价格
        ...
```

**输入**：目的地、日期、预算上限、行程位置  
**输出**：候选酒店列表（含评分、位置匹配度、价格）  
**关键特性**：根据 Itinerary Agent 的每日行程，优先选"在行程中心"的酒店

---

### 4. Dining Agent（美食推荐）

```python
class DiningAgent:
    """
    美食推荐 — 根据位置、时间、预算、饮食限制推荐餐厅。
    """

    async def recommend(
        self,
        location: str,
        time_slot: TimeRange,
        dietary_restrictions: list[str],   # 从 UserProfile 获取
        budget: Money,                       # 从 Budget Agent 获取
        nearby_poi: Place,                   # 当天在附近逛的地方
    ) -> list[RestaurantOption]:
        # 1. 过滤饮食限制
        # 2. 按距离排序
        # 3. 按评分/评价排序
        # 4. 预算校验
        ...
```

**输入**：位置、时段、饮食限制、预算  
**输出**：餐厅推荐列表  
**关键特性**：自动匹配饮食限制（素食/过敏），与行程中的 POI 联动

---

### 5. Transit Agent（交通规划）

```python
class TransitAgent:
    """
    交通专家 — 机票、高铁、市内交通、接送机。
    """

    async def plan(
        self,
        origin: str,
        destination: str,
        date: date,
        budget: Money,
        travelers: list[Traveler],
    ) -> list[TransitOption]:
        ...

    async def get_local_transport(
        self,
        from_place: Place,
        to_place: Place,
        date: date,
        time: time,
    ) -> list[TransitOption]:
        """市内两点间交通方式"""
        ...
```

**输入**：出发地、目的地、日期、预算  
**输出**：交通方案对比（时间/价格/舒适度）

---

### 6. Research Agent（信息检索）

```python
class ResearchAgent:
    """
    通用信息检索 — 所有 Agent 的后援。
    查询: 目的地百科、天气、汇率、签证、安全指数。
    """

    def search(self, query: str) -> SearchResult:
        """语义检索目的地知识"""
        ...

    def get_weather(self, location: str, date: date) -> Weather:
        ...

    def get_exchange_rate(self, currency_from: str, currency_to: str) -> float:
        ...

    def get_visa_requirements(self, passport_country: str, destination: str) -> VisaInfo:
        ...
```

**输入**：任意查询  
**输出**：结构化信息  
**定位**：**基础设施 Agent**，其他 Agent 需要信息时调用它

---

### 7. Preference Agent（偏好学习）

```python
class PreferenceAgent:
    """
    偏好推理引擎 — 从显式声明 + 隐式行为中学习用户偏好。
    """

    def __init__(self, user_id: str):
        self.explicit = LongTermMemory.load_profile(user_id)
        self.inferred: dict[str, float] = {}  # (feature, confidence)

    def record_choice(self, selected: Item, rejected: list[Item]):
        """用户选了 A 拒绝了 B,C,D → 更新偏好"""
        # 对比选中和被拒的 feature，提取偏好信号
        selected_features = selected.features
        rejected_features = [i.features for i in rejected]
        for feat in selected_features:
            if all(feat not in r for r in rejected_features):
                self.inferred[feat] = self.inferred.get(feat, 0) + 0.1

    def get_weight(self, feature: str) -> float:
        """获取某个特征的偏好权重"""
        # 显式 > 隐式
        if feature in self.explicit.likes:
            return 1.0
        if feature in self.explicit.dislikes:
            return -1.0
        return self.inferred.get(feature, 0.0)

    def score(self, item: Item) -> float:
        """给一个选项打分"""
        return sum(self.get_weight(f) for f in item.features)
```

**输入**：用户选择行为、显式声明  
**输出**：偏好权重、选项打分  
**关键特性**：显式偏好优先级 > 隐式推断

---

## 第 4 章：Tool 系统设计

### 4.1 Tool Selection 机制

**对应面试问题**：核心 Q3

Tool Selection 由 Supervisor 和 Specialist 两层共同完成：

```
层级 1 — Supervisor 层（Agent 级路由）:
  用户意图 → AgentRegistry.find(capability) → 选择 Agent
  例: "想去京都" → find("plan_itinerary") → ItineraryAgent

层级 2 — Specialist 层（Tool 级选择）:
  Agent 内部通过 ReAct 循环选择 Tool:
    Thought → 选择 Tool → Action → Observation → Thought ...
```

**Tool Selection 决策树**：

```
用户说 "帮我订酒店"
  │
  ├─ Supervisor 识别 → 需要 AccommodationAgent
  │
  AccommodationAgent 内部:
    Thought 1: "需要先搜索候选" → 选择 search_hotels()
    Observation: 返回 20 个酒店
    Thought 2: "需要按位置评分" → 选择 rank_by_proximity()
    Observation: 排序结果
    Thought 3: "需要预算校验" → 选择 budget_check() (通过 Blackboard)
    Observation: 批准/拒绝
    Thought 4: "需要排序" → 选择 rank_by_score()
    Final: 输出 Top 3 推荐
```

**Tool Selection 的确定性保障**：

- **结构化 Prompt**：每个 Tool 的描述包含 `required_fields` 和 `return_type`，大模型按 JSON Schema 选择
- **Tool Router**：如果 Tool 数量 > 15，先用 Embedding + 最近邻做一层过滤，减少 Prompt 中同时出现的 Tool 数量
- **确定性路由**：部分规则（如"所有消费类请求先经过 Budget Agent 校验"）硬编码在 Supervisor 中，不走 LLM

---

### 4.2 Tool 调用策略（同步 vs 异步 vs 并行）

**对应面试问题**：加分 B3

```
同步调用:  A → wait → B → wait → C
异步调用:  A → fire-and-forget → (稍后获取结果)
并行调用:  A → fork → [B, C, D] → join
```

**策略选择**：

| 场景 | 策略 | 理由 |
|------|------|------|
| 有依赖（B 依赖 A 的结果） | 同步 | 必须串行 |
| 无依赖（搜索酒店 + 搜索餐厅可并行） | 并行 | 节省等待时间 |
| 结果不确定（等待酒店 API 响应，超时降级） | 异步 + 超时 | 不阻塞主流程 |

**实现**：

```python
# Supervisor 的 _execute 方法按 DAG 执行:
async def _execute(self, dag: TaskDAG):
    # 拓扑排序，同一层的任务并行执行
    for layer in dag.topological_layers():
        results = await asyncio.gather(
            *[self._run_task(task) for task in layer],
            return_exceptions=True
        )
        # 处理失败结果
        for task, result in zip(layer, results):
            if isinstance(result, Exception):
                await self._handle_failure(task, result)
```

**性能对比**：

```
场景: 京都 5 天规划

同步串行:
  Research(2s) → Itinerary(3s) → Accommodation(2s) → Transit(1s) → Dining(1s)
  = 9 秒

并行（无依赖部分）:
  Research(2s) → Itinerary(3s) → [Accommodation(2s) + Transit(1s) + Dining(1s)]
  = 6 秒（节省 33%）
```

---

### 4.3 Tool 可插拔架构

**对应面试问题**：加分 B7

**设计目标**：新增 Tool 不需要修改 Prompt、Workflow、Router 中任何一处核心代码。

```python
class ToolRegistry:
    """
    Tool 注册中心 — 按标签注册，按能力发现。
    新增 Tool 只需: 1) 定义函数 2) 注册 3) 完成
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._tags: dict[str, set[str]] = {}

    def register(self, tool: Tool, tags: list[str]):
        """注册一个 Tool"""
        self._tools[tool.name] = tool
        self._tags[tool.name] = set(tags)

    def find(self, tag: str) -> list[str]:
        """按标签查找 Tool"""
        return [name for name, tags in self._tags.items() if tag in tags]

    def get_schema(self) -> list[dict]:
        """获取所有 Tool 的 OpenAI-compatible schema（用于 Prompt）"""
        return [tool.to_openai_schema() for tool in self._tools.values()]

# 使用: 新增一个 "签证查询" Tool
from tools.base import Tool

class VisaChecker(Tool):
    name = "check_visa"
    description = "检查目的地签证要求"
    tags = ["travel_info", "visa"]

    async def execute(self, passport_country: str, destination: str) -> dict:
        return {"visa_required": True, "days_to_process": 15}

# 注册 — 仅此一行，无需修改任何 Prompt 或 Workflow
registry.register(VisaChecker(), ["travel_info", "visa"])
```

**新增 Tool 的影响面**：

```
新增一个 Tool:
  ✅ 注册到 ToolRegistry（1 行）
  ✅ Tool 描述自动注入 Prompt（get_schema() 生成）
  ✅ Agent 自动发现（ReAct 循环中 LLM 看到新 Tool）
  ❌ 不需要修改 Prompt Template
  ❌ 不需要修改 Workflow 编排
  ❌ 不需要修改 Router
```

---

### 4.4 Tool 失败处理

**对应面试问题**：核心 Q4

```
Tool 失败处理 = 重试 + 降级 + 超时 + 熔断 四层防御
```

**四层防御**：

```python
class ResilientToolExecutor:
    """
    带超时 + 重试 + 降级 的 Tool 调用包装。
    """

    def __init__(self, tool: Tool, max_retries: int = 3, timeout: float = 30):
        self.tool = tool
        self.max_retries = max_retries
        self.timeout = timeout
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=5,   # 连续失败 5 次 → 熔断
            recovery_timeout=30,   # 熔断后 30 秒试探
            half_open_max_calls=1  # 半开状态只允许 1 次试探
        )

    async def run(self, **kwargs) -> AgentResult:
        # 第 1 层: 熔断器 — 如果 Tool 不健康，直接短路
        if self.circuit_breaker.is_open:
            return AgentResult(
                success=False,
                error="Circuit breaker open — Tool unavailable",
                fallback=self._get_fallback(**kwargs)
            )

        # 第 2 层: 超时
        for attempt in range(1, self.max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    self.tool.execute(**kwargs),
                    timeout=self.timeout
                )
                self.circuit_breaker.record_success()
                return AgentResult(success=True, data=result)

            except TimeoutError:
                self.circuit_breaker.record_failure()
                if attempt == self.max_retries:
                    # 第 3 层: 降级 — 返回 Fallback
                    return AgentResult(
                        success=False,
                        error=f"Tool timed out after {attempt} attempts",
                        fallback=self._get_fallback(**kwargs)
                    )

            except Exception as e:
                self.circuit_breaker.record_failure()
                if attempt == self.max_retries:
                    # 第 4 层: 通知 Supervisor，让其仲裁
                    return AgentResult(
                        success=False,
                        error=str(e),
                        fallback=self._get_fallback(**kwargs)
                    )
```

**各层防御职责**：

| 层级 | 机制 | 作用 | 对应面试问题 |
|------|------|------|-------------|
| 1 | 熔断器 | 快速失败，不浪费资源 | 个人 P2 |
| 2 | 超时 | 防止长时阻塞 | 加分 B3 |
| 3 | 重试 | 网络抖动自愈 | 核心 Q4 |
| 4 | 降级 (Fallback) | 保证流程继续 | 个人 P3 |

---

## 第 5 章：上下文与状态管理

### 5.1 Context 管理策略

**对应面试问题**：核心 Q5

Agent 的 Context 管理分三层：

```
Layer 1: 对话上下文（用户 ↔ Agent）
  → 维护对话历史，支持多轮交互
  → 策略: 滚动窗口 + 摘要压缩

Layer 2: 任务上下文（Agent ↔ Agent）
  → 通过 Blackboard 共享，不经过 LLM 的 Context
  → 策略: Key-Value 存储 + 事件通知

Layer 3: 系统上下文（Agent 内部）
  → 每个 Agent 的 System Prompt + Tool Schema
  → 策略: Prompt 模板 + 版本管理
```

**对话上下文压缩策略**：

```python
class ContextManager:
    """
    对话上下文管理器 — 当 Context 超过窗口时，自动压缩。
    """

    def __init__(self, max_tokens: int = 120_000):
        self.max_tokens = max_tokens
        self.messages: list[Message] = []
        self.summary: str = ""

    def add(self, message: Message):
        """添加消息，如果超出窗口则压缩"""
        self.messages.append(message)
        if self._count_tokens() > self.max_tokens:
            self._compress()

    def _compress(self):
        """
        压缩策略: 保留最近 20% 消息 + 摘要前面 80%
        摘要由小模型（Haiku）生成，成本低。
        """
        # 1. 取前 80% 的消息 → 让小模型生成摘要
        cutoff = int(len(self.messages) * 0.8)
        old_messages = self.messages[:cutoff]
        recent_messages = self.messages[cutoff:]

        # 2. 生成摘要
        self.summary = await self._summarize(old_messages)

        # 3. 用摘要替换旧消息
        self.messages = [
            SystemMessage(f"Previous conversation summary: {self.summary}"),
            *recent_messages
        ]

    async def _summarize(self, messages: list[Message]) -> str:
        """用小模型生成摘要 — 成本低，速度快"""
        # 使用 Haiku 4.5，成本比 Opus 低 10 倍
        summary = await llm.generate(
            model="claude-haiku-4-5",
            prompt=f"Summarize this conversation: {' '.join(m.content for m in messages)}",
        )
        return summary

    def _count_tokens(self) -> int:
        return sum(len(m.content) // 4 for m in self.messages)
```

**Compression 策略对比**：

| 策略 | 适用场景 | 代价 |
|------|---------|------|
| 滚动窗口（丢弃旧消息） | 上下文不重要 | 可能丢失关键约束 |
| 摘要压缩（小模型生成摘要） | 上下文重要但可概括 | 小模型成本，摘要可能丢失细节 |
| RAG（向量检索） | 超长对话（100+ 轮） | 索引开销 |
| Map-Reduce 压缩 | 多段对话合并 | 多轮 LLM 调用 |

---

### 5.2 Memory 架构（4 层模型）

**对应面试问题**：核心 Q5, 加分 B4

```
Memory 层级:

  ┌─────────────────────────────────┐
  │ L4: Episodic Memory (事件记忆)   │  ← 用户的历史旅行记录
  │    持久化: Postgres              │
  │    TTL: 永久                     │
  ├─────────────────────────────────┤
  │ L3: Semantic Memory (语义记忆)   │  ← 用户偏好、知识图谱
  │    持久化: Postgres + 向量索引   │
  │    TTL: 永久                     │
  ├─────────────────────────────────┤
  │ L2: Working Memory (工作记忆)    │  ← 当前 Trip 的 Blackboard
  │    持久化: Redis                  │
  │    TTL: Trip 结束即过期           │
  ├─────────────────────────────────┤
  │ L1: Context Memory (上下文)      │  ← LLM 的输入窗口
  │    持久化: 内存 (Agent 运行时)    │
  │    TTL: 单次推理                  │
  └─────────────────────────────────┘
```

**每层的具体职责**：

| 层级 | 存储内容 | 读取时机 | 写入时机 |
|------|---------|---------|---------|
| L1 Context | LLM 输入输出 | 每次推理 | 每次推理 |
| L2 Working | 当前 Trip 的约束、结果、中间态 | Agent 间通信 | Agent 写入 Blackboard |
| L3 Semantic | 用户偏好权重、目的地知识 | Agent 初始化时 | 偏好更新时 |
| L4 Episodic | 历史旅行记录、评价 | 推荐时（"上次你选了万豪"） | Trip 结束时 |

**Agent State 持久化设计**：

```python
class StateStore:
    """
    Agent 状态持久化 — Redis 为主，Postgres 为持久备份。
    """

    def __init__(self, redis: Redis, db: AsyncSession):
        self.redis = redis
        self.db = db

    async def save_trip_state(self, trip_id: str, state: dict):
        """保存 Trip 状态到 Redis（热数据）"""
        key = f"trip:{trip_id}:state"
        await self.redis.set(key, json.dumps(state, default=str), ex=86400 * 30)
        # 异步写 Postgres（冷备份）
        await self._async_backup(trip_id, state)

    async def load_trip_state(self, trip_id: str) -> dict:
        """加载 Trip 状态 — 优先 Redis，miss 则查 Postgres"""
        key = f"trip:{trip_id}:state"
        state = await self.redis.get(key)
        if state:
            return json.loads(state)
        # 冷启动：从 Postgres 恢复
        return await self._restore_from_db(trip_id)

    async def _async_backup(self, trip_id: str, state: dict):
        """异步备份到 Postgres — 不阻塞主流程"""
        await asyncio.create_task(
            self.db.execute(TripState.insert().values(trip_id=trip_id, state=state))
        )
```

---

### 5.3 Agent State 持久化

**对应面试问题**：加分 B4

```
State 分类:

  Session State (用户会话):
    → 存储: Redis (热) + Postgres (冷备份)
    → 生命周期: 用户会话期间 + 30 天过期
    → 内容: 对话历史、当前 Trip 进度、Blackboard 快照

  User State (用户画像):
    → 存储: Postgres
    → 生命周期: 永久
    → 内容: 偏好权重、历史行程、评价

  System State (系统配置):
    → 存储: 配置文件 + 环境变量
    → 生命周期: 永久，热更新
    → 内容: Prompt 模板、Tool 配置、熔断阈值
```

**LangGraph State 模式**：

```python
# 如果用 LangGraph，State 用 TypedDict 定义，框架自动管理：
class TripState(TypedDict):
    user_input: Annotated[str, operator.add]           # 累积追加
    blackboard: Annotated[dict, blackboard_reducer]     # 自定义 reducer
    itinerary: Annotated[list, operator.add]            # 累积追加
    budget: Budget                                       # 最后写入覆盖
    preferences: dict                                    # 最后写入覆盖
```

---

### 5.4 Token 成本控制

**对应面试问题**：加分 B6

```
Token 消耗分析:
  1 次完整 Trip 规划的 Token 消耗:
    Supervisor:  ~8,000 tokens / trip
    Itinerary:   ~12,000 tokens / trip
    Accommodation: ~6,000 tokens / trip
    Dining:      ~4,000 tokens / trip
    Transit:     ~3,000 tokens / trip
    Research:    ~2,000 tokens / trip
  =================================
  总计: ~35,000 tokens / trip
  按 100 万用户 / 天: 35 亿 tokens / 天
```

**控制策略**：

| 策略 | 说明 | 节省比例 |
|------|------|---------|
| **Prompt Compression** | 压缩旧对话，只保留摘要 | 30-50% |
| **小模型兜底** | Research Agent 用 Haiku，Supervisor 用 Opus | 60% (单 Agent) |
| **Tool First** | 先用结构化规则/数据库查询，再调用 LLM | 40% |
| **结果缓存** | 相同 query 的 Research Agent 结果缓存 | 50% (命中时) |
| **Context Summary** | 跨轮对话用摘要替代完整历史 | 30% |
| **Parallel Tool Calling** | 一次请求调用多个 Tool，减少 LLM 轮次 | 25% |

**成本优化后的估算**：

```
优化后: ~35,000 → ~15,000 tokens / trip（节省 57%）
  - Prompt Compression: -30%
  - 小模型兜底: -15%
  - 结果缓存: -12%
```

---

## 第 6 章：Shared Blackboard

### 6.1 设计原理

所有 Agent 通过 Blackboard 通信，而非直接互相调用：

```python
class SharedBlackboard:
    """
    共享状态中心 — Agent 之间不直接调用，通过读写 Blackboard 协作。
    支持事件通知：写入触发 → 依赖该数据的 Agent 被唤醒。
    """

    def __init__(self):
        self.data: dict[str, Any] = {}
        self._subscribers: dict[str, list[callable]] = {}

    def write(self, key: str, value: Any):
        self.data[key] = value
        self._notify(key, value)

    def read(self, key: str) -> Any:
        return self.data.get(key)

    def wait_for(self, key: str, timeout: float = 60) -> Any:
        """等待某个 key 被写入"""
        ...

    def subscribe(self, key: str, callback: callable):
        """订阅某个 key 的变更"""
        ...

    def lock(self, key: str) -> ContextManager:
        """写锁 — 防止两个 Agent 同时修改同一块数据"""
        ...
```

### 6.2 数据模型（Key-Value 表）

**Blackboard 上的关键 Key**：

| Key | 写入者 | 读取者 |
|-----|--------|--------|
| `trip.destination` | Supervisor | 所有 Agent |
| `trip.dates` | Supervisor | 所有 Agent |
| `trip.budget` | Supervisor | Budget, 所有消费型 Agent |
| `itinerary.days` | Itinerary | Accommodation, Dining, Transit |
| `accommodation.selected` | Accommodation | Itinerary(调整行程), Budget |
| `budget.remaining` | Budget | 所有 Agent |
| `preference.weights` | Preference | Itinerary, Dining, Accommodation |
| `constraints.dietary` | Supervisor | Dining |

### 6.3 事件机制（Pub/Sub、Lock）

```python
# 事件通知流程:
# Itinerary Agent 写入 itinerary.days
blackboard.write("itinerary.days", day_plans)
  → 触发 subscribers["itinerary.days"]
  → Accommodation Agent 收到通知，开始搜索
  → Dining Agent 收到通知，开始推荐

# 写锁:
# 两个 Agent 不能同时修改同一个 Key
async with blackboard.lock("itinerary.days"):
    day_plans = blackboard.read("itinerary.days")
    day_plans[2].add_poi(new_poi)
    blackboard.write("itinerary.days", day_plans)
```

---

## 第 7 章：协作流程与 Workflow

### 7.1 典型流程

**对应面试问题**：核心 Q2

**场景**：用户说 "帮我规划去京都 5 天，预算 1 万，带老人和孩子"

```
Step 1: Supervisor 识别意图 → TRIP_PLANNING
         写 Blackboard: destination=京都, days=5, budget=¥10000
                        travelers=[成人, 老人(70岁), 儿童(8岁)]

Step 2: Supervisor 拆解任务，按依赖排序:
         [1] Research    → 获取京都信息
         [2] Itinerary   → 规划行程
         [3] Accommodation → 搜索住宿
         [4] Transit     → 交通方案
         [5] Dining      → 餐厅推荐
         [6] Budget      → 汇总评估

Step 3: 各 Agent 按顺序执行:

    Research Agent:
      - 查天气: 5月底 20-28°C
      - 查签证: 中国护照 → 需提前办理
      - 写 Blackboard: research.weather, research.visa

    Itinerary Agent:
      - 读取: 天气、目的地信息
      - 调用 PreferenceAgent.score() 给 POI 打分
      - 考虑: 老人不宜爬山 → 排除高山路线
      - 生成: 5日行程，每天 2-3 个轻松景点
      - 写 Blackboard: itinerary.days

    Accommodation Agent:
      - 读取: 行程位置 → 选行程中心的酒店
      - 筛选: 无障碍设施(老人) + 家庭房(孩子)
      - 请求: BudgetAgent.allocate("hotel", ¥3000)
      - 写 Blackboard: accommodation.selected

    Budget Agent:
      - 收到: hotel ¥3000 ✓ (剩余 ¥7000)
      - 持续跟踪后续消费

Step 4: Supervisor 汇总
         "为您规划了京都5日亲子游:
          酒店: 京都站前万豪 ¥3000
          行程: Day1 京都站→锦市场→清水寺 ...
          总预算: ¥9200 (余 ¥800)"
```

### 7.2 冲突解决

**对应面试问题**：核心 Q6

```
Scenario: Accommodation 选了五星酒店 ¥6000/晚

Budget Agent → "仅酒店就 ¥30000，超预算 3 倍"
  ↓ 触发冲突
Supervisor → 仲裁
  选项 A: 换 3 星酒店 ¥1500/晚 (省 ¥7500)
  选项 B: 增加预算 (需用户确认)
  ↓
Supervisor 问用户 → 用户选 A
  ↓
Accommodation Agent 重新搜索 → 输出新方案
```

### 7.3 用户修改需求（增量重规划）

**对应面试问题**：核心 Q8

```
用户说: "把京都改成大阪，预算增加到 2 万"

处理策略: 增量重规划（Incremental Replanning），而非从头开始

  1. Supervisor 读取 Blackboard 当前状态
  2. 标记变更 Key: trip.destination, trip.budget
  3. 计算影响面:
     destination 变更 → 影响: Research, Itinerary, Accommodation, Transit, Dining (全部)
     budget 变更 → 影响: Budget, 所有消费型 Agent
  4. 只重新执行受影响的 Agent:
     - 跳过 Preference Agent（偏好未变）
     - 重新执行 Research, Itinerary, Accommodation, Transit, Dining
  5. 通知用户: "已为您重新规划大阪行程..."

与从头开始对比:
  从头: ~35,000 tokens
  增量: ~25,000 tokens（偏好 Agent 等跳过）

极端场景 — 用户不断修改需求:
  "改大阪" → "改成东京" → "不还是京都吧"
  → 计数器超过 3 次 → Supervisor 触发全量重规划，并提醒用户:
    "您已修改 3 次需求，建议您先确定目的地，我再为您详细规划"
```

### 7.4 防死循环机制

**对应面试问题**：加分 B5

```
Agent 死循环的常见原因:
  1. ReAct 循环中 Thought 不收敛
  2. 两个 Agent 互相修改 Blackboard 上的同一个 Key
  3. 冲突仲裁没有终止条件

防护措施:

  措施 1: 最大步数限制
    每个 Agent 的 ReAct 循环限制 max_steps=15
    超过 → 强制输出当前最佳结果

  措施 2: 最大 Token 限制
    单次 Agent 调用限制 max_tokens=10,000
    超过 → 截断输出

  措施 3: Blackboard 写锁超时
    两个 Agent 竞争同一 Key 的锁 → 超过 5 秒 → 后者放弃，重试或降级

  措施 4: 冲突仲裁终止条件
    冲突仲裁限制 max_iterations=3
    超过 → 输出两个方案，让用户选择

  措施 5: 全局超时
    整个 Trip 规划限制 120 秒
    超时 → 输出已完成的 Agent 结果，跳过未完成部分
```

---

## 第 8 章：容错与韧性

### 8.1 超时 + 重试 + 降级

**对应面试问题**：核心 Q4

```python
class AgentResult:
    """每个 Agent 的返回值 — 携带成功/失败状态。"""
    success: bool
    data: Any = None
    error: str = None
    fallback: Any = None       # 失败时的降级方案

class ResilientExecutor:
    """带超时 + 重试 + 降级的 Agent 调用包装。"""

    async def run(self, agent: Agent, task: Task) -> AgentResult:
        try:
            return await asyncio.wait_for(
                agent.execute(task),
                timeout=task.timeout or 30
            )
        except TimeoutError:
            return AgentResult(success=False, fallback=task.fallback)
        except Exception as e:
            return AgentResult(success=False, error=str(e))
```

---

### 8.2 Rollback 机制

**对应面试问题**：个人 P1

**设计模式**：Saga（补偿事务）

```
Saga 模式 vs 2PC (Two-Phase Commit):
  - 2PC: 需要同步锁，不适合分布式 Agent 场景
  - Saga: 异步补偿，每个 Agent 负责自己的回滚，适合本架构

流程:
  [Research] → [Itinerary] → [Accommodation] → [Budget]

如果 Accommodation 失败:
  1. 触发 Accommodation 的补偿动作: 取消搜索锁
  2. 触发 Itinerary 的补偿动作: 撤销行程锁定的 POI
  3. 触发 Research 的补偿动作: 释放缓存配额
  4. Supervisor 决定: 重试 / 降级 / 告知用户

回滚粒度: 以 Blackboard Key 为单位
  每个 Agent 负责自己的 Key 回滚，不跨 Agent 操作
```

**实现**：

```python
class SagaOrchestrator:
    """
    Saga 编排器 — 维护补偿动作链，失败时逆向执行。
    """

    def __init__(self):
        self._compensations: list[Callable] = []

    async def execute(self, steps: list[SagaStep]):
        for i, step in enumerate(steps):
            result = await step.execute()
            if result.success:
                self._compensations.append(step.compensate)
            else:
                # 逆向执行补偿
                await self._compensate()
                raise SagaError(f"Step {step.name} failed at index {i}")

    async def _compensate(self):
        """逆向执行补偿动作"""
        for compensate in reversed(self._compensations):
            try:
                await compensate()
            except Exception as e:
                log.warning(f"Compensation failed: {e}")
        self._compensations.clear()

class SagaStep:
    def __init__(self, name: str, execute: Callable, compensate: Callable):
        self.name = name
        self.execute = execute
        self.compensate = compensate

# 使用:
saga = SagaOrchestrator()
saga.execute([
    SagaStep("research", research.execute, lambda: blackboard.clear("research.*")),
    SagaStep("itinerary", itinerary.execute, lambda: blackboard.clear("itinerary.days")),
    SagaStep("accommodation", accommodation.execute, lambda: blackboard.clear("accommodation.selected")),
    SagaStep("budget", budget.execute, lambda: blackboard.clear("budget.allocated")),
])
```

**回滚策略矩阵**：

| 失败阶段 | 回滚动作 | 对用户的影响 |
|---------|---------|-------------|
| Research 失败 | 无（无状态操作） | 告知用户"部分信息检索失败"，继续执行 |
| Itinerary 失败 | 清除 itinerary.days | 告知用户"行程规划失败"，提供手动输入选项 |
| Accommodation 失败 | 清除 accommodation.selected | 告知用户"住宿搜索失败"，提供备选方案 |
| Budget 失败 | 清除 budget.allocated，重新计算 | 告知用户"预算校验失败"，请求确认 |

---

### 8.3 熔断器设计

**对应面试问题**：个人 P2

```
每个 Tool 调用 = 一个熔断器实例

状态机:
  [Closed] ──连续成功5次──→ 保持 Closed
  [Closed] ──连续失败3次──→ [Open]（熔断，拒绝请求）
  [Open]   ──等待30秒─────→ [Half-Open]
  [Half-Open] ──请求成功──→ [Closed]（恢复正常）
  [Half-Open] ──请求失败──→ [Open]（继续熔断）

阈值配置:
  - failure_threshold: 3 （连续失败 3 次 → 熔断）
  - recovery_timeout: 30s（熔断后等待 30 秒进入半开）
  - half_open_max_calls: 1（半开状态只允许 1 次试探）
```

**实现**：

```python
class CircuitBreaker:
    """
    熔断器 — 保护系统免受持续失败的 Tool 影响。
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, failure_threshold=3, recovery_timeout=30, half_open_max_calls=1):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self.state = self.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        self.half_open_calls = 0

    def can_execute(self) -> bool:
        if self.state == self.CLOSED:
            return True
        if self.state == self.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = self.HALF_OPEN
                self.half_open_calls = 0
                return True
            return False
        # HALF_OPEN
        return self.half_open_calls < self.half_open_max_calls

    def record_success(self):
        self.failure_count = 0
        self.state = self.CLOSED
        self.half_open_calls += 1

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = self.OPEN
```

**熔断器监控**：

```
Dashboard 展示:
  [Hotel API]     Circuit: 🟢 CLOSED  (failures: 0/3)
  [Map API]       Circuit: 🔴 OPEN    (failures: 3/3, recovery in 12s)
  [Weather API]   Circuit: 🟡 HALF-OPEN (testing...)
  [Budget Service] Circuit: 🟢 CLOSED  (failures: 0/3)
```

---

### 8.4 兜底方案（每个 Agent 的 Fallback）

**对应面试问题**：个人 P3

```
兜底层级:

  Level 1: Agent 级 Fallback
    → 每个 Agent 实现 _fallback() 方法
    → 当 execute() 失败时，返回 _fallback() 的结果

  Level 2: Supervisor 级 Fallback
    → 某个 Agent 不可用时，Supervisor 跳过该步骤
    → 用已知的默认值填充

  Level 3: 用户级 Fallback
    → 告知用户部分功能不可用
    → 请求用户手动输入

  Level 4: 系统级 Fallback
    → 整体降级为"简单版"响应
    → 只返回核心信息，跳过高级功能
```

**各 Agent 的 Fallback 设计**：

| Agent | 正常输出 | Fallback 输出 |
|-------|---------|--------------|
| Research | 目的地百科、天气、签证 | "暂时无法获取实时信息，以下是通用建议" |
| Itinerary | 5 日详细行程 | "以下是该目的地的经典路线建议"（通用模板） |
| Accommodation | 精准推荐的 3 家酒店 | "建议在该目的地的市中心区域搜索酒店" |
| Transit | 具体航班/车次 | "建议通过携程/飞猪搜索该路线的实时票价" |
| Dining | 精准推荐的餐厅 | "建议在该目的地的 XX 区域搜索美食" |
| Budget | 精确预算报告 | "基于通用标准，预计费用如下" |

---

### 8.5 异常流转图

```
Agent 执行失败时的异常流转:

  [Agent 执行]
      │
      ├─ 成功 ──→ 写入 Blackboard ──→ 通知 Supervisor
      │
      ├─ 失败 → 检查: 可重试?
      │          ├─ Yes → 重试 (max 3 次)
      │          │          ├─ 成功 → 写入 Blackboard
      │          │          └─ 失败 → Fallback
      │          │
      │          └─ No  → Fallback
      │                     │
      │                     ├─ Fallback 有值 → 写入 Blackboard (标记降级)
      │                     └─ Fallback 无值 → 上报 Supervisor
      │                                           │
      │                                           ├─ 用户可接受 → 跳过
      │                                           ├─ 用户需确认 → 弹窗
      │                                           └─ 不可跳过  → 终止并告知用户
```

---

## 第 9 章：可观测性与测试

### 9.1 Logging 策略

**对应面试问题**：加分 B9

```python
class AgentLogger:
    """
    Agent 日志记录器 — 结构化日志，支持 Trace 关联。
    """

    def __init__(self, trip_id: str, trace_id: str):
        self.trip_id = trip_id
        self.trace_id = trace_id

    def log_agent_start(self, agent_name: str, input_summary: str):
        """Agent 开始执行"""
        self._emit({
            "level": "INFO",
            "event": "agent.start",
            "agent": agent_name,
            "input": input_summary,
            "trip_id": self.trip_id,
            "trace_id": self.trace_id,
        })

    def log_agent_end(self, agent_name: str, output_summary: str, duration_ms: int, success: bool):
        """Agent 执行结束"""
        self._emit({
            "level": "INFO" if success else "WARN",
            "event": "agent.end",
            "agent": agent_name,
            "output": output_summary,
            "duration_ms": duration_ms,
            "success": success,
            "trip_id": self.trip_id,
            "trace_id": self.trace_id,
        })

    def log_tool_call(self, tool_name: str, args: dict, result: Any, duration_ms: int):
        """Tool 调用记录"""
        self._emit({
            "level": "DEBUG",
            "event": "tool.call",
            "tool": tool_name,
            "args": args,
            "result_summary": str(result)[:500],
            "duration_ms": duration_ms,
            "trip_id": self.trip_id,
            "trace_id": self.trace_id,
        })
```

### 9.2 Trace & Replay

```
Trace 链路:
  User → Supervisor → [Agent 1 → Tool 1 → Tool 2] → [Agent 2 → Tool 3] → Response

每个 Trace 包含:
  - trace_id: 全局唯一，贯穿整个 Trip 规划
  - span_id: 每个 Agent/Tool 的独立 span
  - parent_span_id: 父子关系
  - duration: 耗时
  - tokens: Token 消耗
  - cost: 成本

Replay 场景:
  1. 用户投诉 → 查 trace_id → 重现完整的 Agent 执行链路
  2. 性能优化 → 对比多个 trace → 找到瓶颈 Agent
  3. Bug 复现 → 用原始输入 replay → 复现问题
```

### 9.3 Metrics & Dashboard

```
关键指标:

  业务指标:
    - 规划成功率 (Agent 全部成功 / 总请求)
    - 平均规划耗时
    - 用户修改需求次数 / trip
    - 预算超支率

  技术指标:
    - Token 消耗 / trip
    - Tool 调用成功率
    - 熔断触发次数
    - P50 / P95 / P99 延迟

  Dashboard:
    +--------------------+  +-------------------+
    | 规划成功率: 92.3%   |  | Token / trip:     |
    |                    |  | 平均: 15,200      |
    |  [📈 趋势图]       |  | P95: 28,000       |
    +--------------------+  +-------------------+
    +--------------------+  +-------------------+
    | 平均耗时: 4.2s     |  | 熔断触发: 0 次/天  |
    | P95: 8.1s          |  | Tool 成功率: 99.2% |
    | P99: 15.3s         |  +-------------------+
    +--------------------+
```

### 9.4 Agent 效果评估（Evaluation）

**对应面试问题**：核心 Q7

```
Evaluation 分层:

  Level 1: 单 Agent 评估
    → Itinerary Agent: 行程合理性评分（时间冲突、节奏适中）
    → Accommodation Agent: 位置匹配度、价格合理性
    → Budget Agent: 预算精度（实际 vs 预测）

  Level 2: 端到端评估
    → 完整 Trip 方案评分
    → 指标: 预算合规率、约束满足率、用户满意度

  Level 3: 用户反馈评估
    → 用户是否接受了方案
    → 用户修改了哪些部分
    → 用户评分
```

**自动化评估 Pipeline**：

```python
class TripEvaluator:
    """
    Trip 规划方案自动化评估器。
    """

    def evaluate(self, trip_plan: TripPlan, constraints: TripConstraints) -> EvalReport:
        scores = {}

        # 1. 预算合规性
        budget_score = 1.0 if trip_plan.total_cost <= constraints.budget else 0.0

        # 2. 约束满足率
        constraint_score = self._check_constraints(trip_plan, constraints)

        # 3. 行程合理性（用 LLM 评估）
        itinerary_score = self._llm_evaluate_itinerary(trip_plan.itinerary)

        # 4. 综合评分
        scores = {
            "budget_compliance": budget_score,
            "constraint_satisfaction": constraint_score,
            "itinerary_quality": itinerary_score,
            "overall": 0.3 * budget_score + 0.3 * constraint_score + 0.4 * itinerary_score,
        }

        return EvalReport(scores=scores)

    def _check_constraints(self, plan: TripPlan, constraints: TripConstraints) -> float:
        """检查约束满足率"""
        total = 0
        met = 0
        if constraints.budget and plan.total_cost <= constraints.budget:
            met += 1
        total += 1
        if constraints.dietary_restrictions:
            for poi in plan.all_restaurants:
                total += 1
                if poi.matches_dietary(constraints.dietary_restrictions):
                    met += 1
        return met / total if total > 0 else 1.0
```

### 9.5 测试策略

```
测试分层:

  单元测试:
    - 每个 Agent 的纯逻辑函数
    - BudgetAgent.allocate() — 验证预算计算
    - PreferenceAgent.score() — 验证偏好打分
    - CircuitBreaker — 验证状态转换

  集成测试:
    - Agent + Tool 组合
    - 模拟 Tool 返回 → 验证 Agent 输出
    - Blackboard 读写 — 验证 Agent 间通信

  E2E 测试:
    - 完整 Trip 规划流程
    - 使用 Mock LLM（确定性输出）
    - 验证: 约束满足、预算合规、行程合理

  混沌测试:
    - 随机让某个 Agent 失败 → 验证 Rollback / Fallback
    - Tool 超时 → 验证超时降级
    - Tool 连续失败 → 验证熔断器
```

---

## 第 10 章：Prompt 与配置管理

### 10.1 Prompt Template 管理

**对应面试问题**：加分 B8

```python
class PromptManager:
    """
    Prompt 模板管理器 — 版本化、参数化、可替换。
    """

    def __init__(self, template_dir: str):
        self.templates: dict[str, dict[str, str]] = {}
        self._load(templates_dir)

    def render(self, template_name: str, variables: dict, version: str = "latest") -> str:
        """渲染 Prompt 模板"""
        versions = self.templates.get(template_name, {})
        template = versions.get(version, versions.get("latest"))
        return template.format(**variables)

    def _load(self, directory: str):
        """从文件加载模板"""
        for file in Path(directory).glob("*.j2"):
            name = file.stem
            version = file.suffix.replace(".", "") or "latest"
            if name not in self.templates:
                self.templates[name] = {}
            self.templates[name][version] = file.read_text()

# 模板文件: prompts/itinerary.j2
#
# You are an expert travel itinerary planner.
#
# Destination: {destination}
# Dates: {dates}
# Travelers: {travelers}
# Budget: {budget}
# Preferences: {preferences}
#
# Constraints:
#   - Senior travelers present: {has_senior}
#   - Children present: {has_children}
#   - Dietary restrictions: {dietary}
#
# Generate a {days} day itinerary with the following principles:
#   1. Group nearby attractions together
#   2. Allow rest time for seniors
#   3. Include child-friendly activities
#   4. Don't exceed {max_attractions_per_day} per day
```

### 10.2 版本控制

```
Prompt 版本管理:

  prompts/
    itinerary.v1.j2        ← v1 版本（基线）
    itinerary.v2.j2        ← v2 版本（改进约束表达）
    itinerary.j2           ← latest（符号链接 → v2）
    supervisor.j2
    budget.j2

  版本变更记录:
    v1 → v2:
      - 增加 has_senior / has_children 显式字段
      - 修改约束表达从自然语言为结构化列表
      - 增加 max_attractions_per_day 参数

  灰度发布:
    - 10% 流量用 v2 → 观察评估分数
    - 如果 v2 overall_score > v1 → 全量切到 v2
    - 如果 v2 overall_score < v1 → 回滚到 v1
```

### 10.3 A/B Test 与评估

```python
class PromptABTest:
    """
    Prompt A/B 测试 — 用评估分数决定哪个版本更好。
    """

    def __init__(self, name: str, variants: dict[str, float]):
        """
        variants: {"v1": 0.5, "v2": 0.5} → 流量分配
        """
        self.name = name
        self.variants = variants
        self.results: dict[str, list[float]] = defaultdict(list)

    def select_variant(self) -> str:
        """按流量分配选择版本"""
        r = random()
        cumulative = 0
        for variant, weight in self.variants.items():
            cumulative += weight
            if r < cumulative:
                return variant
        return list(self.variants.keys())[-1]

    def record_score(self, variant: str, score: float):
        self.results[variant].append(score)

    def get_winner(self, min_samples: int = 100) -> str | None:
        """统计显著性检验（简化版：均值比较）"""
        for variant, scores in self.results.items():
            if len(scores) < min_samples:
                return None
        means = {v: sum(s)/len(s) for v, s in self.results.items()}
        return max(means, key=means.get)
```

---

## 第 11 章：可扩展性与大规模

### 11.1 Agent 注册与发现

**对应面试问题**：加分 B7

```python
class AgentRegistry:
    """
    Agent 注册中心 — 按能力标签注册，Supervisor 按标签发现。
    """

    def __init__(self):
        self._agents: dict[str, Agent] = {}
        self._capabilities: dict[str, set[str]] = {}  # agent → {tags}

    def register(self, agent: Agent, capabilities: list[str]):
        self._agents[agent.name] = agent
        self._capabilities[agent.name] = set(capabilities)

    def find(self, required_capability: str) -> list[str]:
        """查找能处理某类任务的 Agent"""
        return [
            name for name, caps in self._capabilities.items()
            if required_capability in caps
        ]

# 使用示例
registry = AgentRegistry()
registry.register(ItineraryAgent(), ["plan_itinerary", "route_optimization"])
registry.register(BudgetAgent(), ["budget_check", "cost_estimation"])
registry.register(AccommodationAgent(), ["hotel_search", "booking"])

# Supervisor 发现能规划行程的 Agent
available = registry.find("plan_itinerary")  # → ["ItineraryAgent"]
```

### 11.2 新增 Agent 的扩展路径

```
新增一个 Agent 的完整流程:

  1. 定义 Agent 类（继承 BaseAgent）
     class ActivityAgent(BaseAgent): ...

  2. 定义 Tool（可选）
     class ActivitySearch(Tool): ...

  3. 注册到 AgentRegistry
     registry.register(ActivityAgent(), ["activity_search", "experience"])

  4. 注册 Tool 到 ToolRegistry
     tool_registry.register(ActivitySearch(), ["activity"])

  5. 定义 Blackboard Key（可选）
     activity.recommendations

  6. Supervisor 按 capability 自动发现
     registry.find("activity_search") → ["ActivityAgent"]

影响面:
  ✅ 1-2 小时完成新增
  ❌ 不需要修改 Prompt Template（Tool Schema 自动生成）
  ❌ 不需要修改 Supervisor 编排逻辑（自动发现）
  ❌ 不需要修改其他 Agent
```

### 11.3 百万用户场景下的瓶颈分析

**对应面试问题**：核心 Q9, 加分 B10

```
瓶颈排序:

  1. LLM Token（成本最高，不可规避）
     - 100 万用户 × 15,000 tokens = 15 亿 tokens / 天
     - 缓解: Prompt Compression + 小模型兜底 + 结果缓存

  2. Tool 调用延迟（外部 API）
     - 酒店搜索 API: ~800ms / 调用
     - 缓解: 结果缓存（同一目的地缓存 1 小时）+ 异步预取

  3. Agent 间协调开销
     - Blackboard 锁竞争（高并发时）
     - 缓解: 无锁设计 + 乐观并发 + 事件驱动

  4. 数据库连接池
     - 100 万请求 × 8 个 Agent = 800 万 DB 操作
     - 缓解: Connection Pool + Redis 缓存热点 Key + 批量写入

  5. 内存占用
     - 每个 Trip 的 Blackboard ~ 50KB
     - 100 万并发 → 50GB 内存
     - 缓解: 冷热分层（Redis 存热数据，Postgres 存冷数据）
```

### 11.4 水平扩展策略

```
扩展架构:

  Phase 1 (单体):
    [App Server × 1] → [LLM API] + [Tool APIs]
    → 单进程，Agent 为内存对象

  Phase 2 (服务化):
    [API Gateway]
       ├─ [Itinerary Service × 3]    ← 热门，多副本
       ├─ [Accommodation Service × 2]
       ├─ [Budget Service × 1]
       ├─ [Dining Service × 1]
       ├─ [Transit Service × 1]
       ├─ [Research Service × 2]
       └─ [Supervisor Service × 2]
    → Agent 间通过 HTTP + Redis Pub/Sub 通信

  Phase 3 (流式):
    [API Gateway] → [Event Bus (Kafka)]
       ├─ [Itinerary Consumer × N]
       ├─ [Accommodation Consumer × N]
       └─ ...
    → Agent 间通过 Event Streaming 通信
    → 无限水平扩展
```

**Sharding 策略**：

```
按 trip_id hash 分片:
  trip_id 哈希到分片 1 → 该 Trip 的所有 Agent 调用路由到分片 1
  → 保证同一 Trip 的所有 Agent 调用在同一节点
  → 避免跨节点通信
```

---

## 第 12 章：技术选型

### 12.1 框架选型理由

**对应面试问题**：加分 B7

```
Agent 框架选型对比:

  LangGraph:
    ✅ 图模型原生支持 DAG 编排
    ✅ State 管理成熟（TypedDict + reducer）
    ✅ 社区大，生态完善
    ⚠️ 学习曲线较陡
    → 推荐，与本项目 DAG 式编排天然契合

  AutoGen:
    ✅ 多 Agent 对话模式成熟
    ⚠️ 编排控制力弱（对等协商，难收敛）
    ⚠️ 冲突解决能力弱
    → 不适合本项目（需要 Supervisor 集中控制）

  CrewAI:
    ✅ 角色定义清晰
    ⚠️ 灵活性不足
    ⚠️ 生态较小
    → 不适合本项目（需要自定义 Tool 编排）

  自研:
    ✅ 完全可控
    ⚠️ 开发成本高
    ⚠️ 需要自行实现 State、Retriever、Memory
    → 不建议，除非有明确需求超出框架限制
```

### 12.2 部署架构

```
Agent 框架:   LangGraph
编排模式:     Supervisor + Specialist (推荐，可控性强)
通信方式:     Shared Blackboard (dict + pub/sub)
持久化:       Redis (热) + Postgres (冷)
API 网关:     FastAPI (统一入口)
部署:         Docker Compose (各 Agent 独立服务，也可单进程)

技术栈:
  - Python 3.12
  - LangGraph (Agent 编排)
  - FastAPI (API 网关)
  - Redis (Blackboard + 缓存)
  - Postgres (持久化)
  - Docker Compose (本地开发)
  - OpenTelemetry (可观测性)
```

---

## 附录：面试速查表

> 每个面试问题对应文档中的章节，面试时可按章节快速定位。

### 核心问题 Top 10

| # | 面试问题 | 章节 | 关键词 |
|---|---------|------|--------|
| 1 | 为什么需要 Agent？ | §1.1 ADR-001 | RAG vs Agent, 约束满足 |
| 2 | Planning 如何设计？ | §1.2 ADR-002, §7.1 | 混合范式, Supervisor+ReAct |
| 3 | Tool Selection？ | §4.1 | 双层路由, 确定性保障 |
| 4 | Tool 失败怎么办？ | §4.4, §8.1 | 四层防御, 重试+降级 |
| 5 | Context 如何管理？ | §5.1 | 三层压缩, 小模型摘要 |
| 6 | 为什么选这种 Workflow？ | §2.2 | 架构对比, 明确子任务 |
| 7 | 如何评估效果？ | §9.4 | 三层评估, LLM Judge |
| 8 | 用户修改需求怎么办？ | §7.3 | 增量重规划, 影响面计算 |
| 9 | 最大瓶颈是什么？ | §11.3 | Token, 外部 API, 锁竞争 |
| 10 | 如果重新设计？ | §2.3 | Phase 2 服务化, 分层不变 |

### 加分问题 Top 10

| # | 面试问题 | 章节 | 关键词 |
|---|---------|------|--------|
| B1 | ReAct vs Plan-and-Execute？ | §1.2 ADR-002 | 混合范式, 各有优劣 |
| B2 | 为什么不用单 Agent？ | §1.3 ADR-003 | 上下文爆炸, 无法并行 |
| B3 | 同步 vs 异步？ | §4.2 | DAG 编排, 并行节省 33% |
| B4 | State 如何保存？ | §5.3 | Redis+Postgres, 热冷分层 |
| B5 | 如何避免死循环？ | §7.4 | 五层防护, 最大步数 |
| B6 | 如何控制 Token 成本？ | §5.4 | 六层压缩, 节省 57% |
| B7 | Tool 可插拔？ | §4.3 | 注册+发现, 一行注册 |
| B8 | Prompt 版本管理？ | §10.2 | 版本化+灰度+回滚 |
| B9 | Observability？ | §9.1-9.3 | Trace+Metrics+Dashboard |
| B10 | 百万用户瓶颈？ | §11.3-11.4 | Token+API, 三阶段扩展 |

### 个人问题 3 问

| # | 面试问题 | 章节 | 关键词 |
|---|---------|------|--------|
| P1 | 流程报错如何 Rollback？ | §8.2 | Saga 模式, 补偿事务 |
| P2 | 流程如何触发熔断？ | §8.3 | 三态状态机, 半开试探 |
| P3 | 怎么设计兜底？ | §8.4 | 四级 Fallback, 逐层降级 |
