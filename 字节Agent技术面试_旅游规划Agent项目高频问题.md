# 字节 Agent 技术面试 —— 旅游规划 Agent 项目高频问题（20 问）

> 面试官视角：字节跳动 Agent 方向技术面试（Seed / 豆包 / 扣子 / AI Infra 等）

（内容同上，已整理为 Markdown。）

## 第一部分：核心问题（Top 10）

1. 为什么你的项目需要 Agent，而不是普通的 RAG + Prompt？
2. Agent 的 Planning 是如何设计的？
3. Tool Selection 是如何完成的？
4. 如果 Tool 调用失败怎么办？
5. Context 是如何管理的？
6. 为什么选择这种 Workflow？
7. Agent 如何评估效果？
8. 用户不断修改需求怎么办？
9. 你的 Agent 最大的瓶颈是什么？
10. 如果重新设计，你会怎么做？

## 第二部分：加分问题（Top 10）

1. 为什么选择 ReAct，而不是 Plan-and-Execute？

   各自优缺点、哪种更适合旅游规划

2. 为什么不用 Multi-Agent？

   什么时候需要：Travel Planner、Hotel Agent、Food Agent、Traffic Agent

3. Tool 是同步还是异步调用？为什么？

   Parallel Tool Calling、Async IO、Latency、用户体验

4. Agent 的 State 如何保存？

   LangGraph State、Redis、Database、Session、Memory

5. 如何避免 Agent 死循环？

   最大步数、最大 Token、Retry 次数、Reflection

6. 如何控制 Token 成本？

   Prompt Compression、Context Summary、Cache、RAG、Tool First

7. 如何实现 Tool 的可插拔？

   新增 Tool 是否需要修改：Prompt、Workflow、Router

8. Prompt 如何做版本管理？

   Prompt Template、Prompt Registry、Prompt A/B Test、Prompt Evaluation

9. Agent 如何做 Observability？

   Logging、Trace、Replay、Metrics、Dashboard

10. 如果每天有100万用户，这个 Agent 最大瓶颈是什么？

    Token、QPS、Tool、数据库、Cache、并发、成本

## 第三部分：能力排序

| 排名 | 能力 | 面试关注点 |
|------|------|------------|
| ① | Agent 架构设计 | 为什么需要 Agent、状态流转、任务拆解 |
| ② | Tool 调用设计 | Tool Selection、异常处理、并发 |
| ③ | Workflow 能力 | Graph、State Machine、DAG |
| ④ | Prompt 与 Planning | Planner、Router、ReAct |
| ⑤ | Context / Memory 管理 | Session、Memory、Summary |
| ⑥ | 工程能力 | 模块化、日志、监控、测试 |
| ⑦ | Evaluation | Benchmark、自动评测 |
| ⑧ | 性能优化 | Token、缓存、延迟 |
| ⑨ | 可扩展性 | Tool、模型、插件化 |
| ⑩ | 框架使用 | LangGraph、AutoGen、OpenAI Agents SDK |

> 建议：结合自己的旅游规划 Agent，为每个问题准备 3~5 分钟的回答，并重点说明设计取舍（Why）和工程实践。

## 第四部分：个人考虑的一些问题

1.如果其中一个流程报错了如何Rollback？

2.流程如何触发熔断？

3.怎么设计兜底？

