# 投资画像与多策略对比

本文档说明「投资画像」功能：Web 端 `/profile` 页面的访谈推荐与策略中心直选、画像的存储语义，以及问股（Agent Chat）在多策略场景下的对比与共识输出。内容以代码实现为准（`apps/dsa-web/src/pages/ProfilePage.tsx`、`api/v1/endpoints/agent.py`、`src/agent/orchestrator.py` 等）。

## 入口

Web 路由 `/profile`（`apps/dsa-web/src/pages/ProfilePage.tsx`，导航项 `layout.nav.profile`）提供两个入口，通过页内 Tab 切换：

- **做个访谈**（`InterviewWizard`）：回答 4 道问题，由后端规则推荐 1-3 个策略。
- **直接选策略**（`StrategyCenter`）：按分类浏览全部可用策略，手动勾选并保存。

两个入口最终都调用 `PUT /api/v1/agent/profile` 保存画像；保存后统一展示成功/失败提示。画像页首次加载会调用 `GET /api/v1/agent/profile` 回填已保存的选择。

## 访谈推荐（InterviewWizard）

`apps/dsa-web/src/components/profile/InterviewWizard.tsx` 定义 4 道题目，全部回答后自动提交至 `POST /api/v1/agent/profile/interview`（后端 `src/agent/skills/profile_recommender.py::recommend_skills`），该接口**只返回推荐结果，不写入画像**——需要用户点击「采用」后前端才会调用 `PUT /api/v1/agent/profile`（`source=interview`）落库。

| 题目 key | 问题 | 选项 value |
| --- | --- | --- |
| `horizon` | 你的典型持仓周期是多久？ | `ultra_short`（超短线 1-3 天）/ `swing`（波段 1-4 周）/ `long`（中长线 1 个月以上） |
| `risk` | 你的风险偏好是？ | `conservative`（保守）/ `balanced`（平衡）/ `aggressive`（激进） |
| `style` | 你倾向于哪种交易风格？ | `trend`（趋势跟踪）/ `reversal`（反转博弈）/ `theme`（热门主题）/ `value`（价值低估）/ `framework`（综合框架） |
| `watch` | 你日常盯盘的投入程度？ | `high`（高度投入）/ `medium`（中度投入）/ `low`（低投入） |

推荐算法（`profile_recommender.py`）为规则打分，不调用 LLM：

- 每个 `user_invocable` 策略都会解析出 `profile_tags`（见下节）；`style`/`risk`/`horizon` 三个维度命中权重分别为 `3.0`/`2.0`/`2.0`，累加得分。
- 策略的 `horizon` 标签含 `ultra_short` 时，按 `watch` 答案追加调整分：`high +1.0`、`medium +0`、`low -1.5`（盯盘投入低时降低超短线策略优先级）。
- 按得分降序取前 `min(max_count, 5)` 个（接口固定传 `max_count=3`，即最多推荐 3 个），并列时按 `default_priority` 升序、再按策略名排序，保证结果确定性。

推荐结果附带一段解释文案：若 `config.is_agent_available()` 为真，会调用 `LLMToolAdapter.call_text` 生成 2-3 句中文解释；LLM 不可用或调用失败时回退到静态拼接文案（`根据你的偏好，推荐：...`），不会阻塞返回。

## 策略中心（直选）

`apps/dsa-web/src/components/profile/StrategyCenter.tsx` 调用 `GET /api/v1/agent/skills`，按 `category` 分组展示（仅返回 `user_invocable=true` 的策略），固定分组顺序为：

`trend`（趋势）→ `pattern`（形态）→ `reversal`（反转）→ `framework`（框架）→ 其余未知分类归入 `other`（其他）。

`category` 及 `profile_tags` 的解析逻辑见 `src/agent/skills/profile_tags.py::resolve_profile_tags`：策略若显式声明 `profile_tags` 则直接使用；否则按 `category` 派生默认标签（`trend`→style=trend, `pattern`→style=framework, `reversal`→style=reversal/risk=aggressive, `framework`→style=framework/horizon=[swing,long]），并在 `market_regimes` 命中热点题材类关键词（`sector_hot`/`theme`/`hot_theme`/`emotion`/`event`）时追加 `style=theme`、`risk=aggressive`、`horizon=ultra_short`。

用户最多勾选 **5 个**策略（`ProfilePage.tsx` 的 `MAX_SELECTED_SKILLS=5`），达到上限后未选中的卡片禁用；点击「保存画像」调用 `PUT /api/v1/agent/profile`（`source=manual`）。

## 画像存储

后端接口（`api/v1/endpoints/agent.py`）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/v1/agent/profile` | 返回当前画像 `{skill_ids, source, updated_at}`；未保存过时返回空列表、`source=null` |
| `PUT` | `/api/v1/agent/profile` | 请求体 `{skill_ids, source="manual", interview_answers?}`；服务端去重（保留首次出现顺序）并截断至 **5 个**再落库 |
| `POST` | `/api/v1/agent/profile/interview` | 请求体 `{answers: {horizon, risk, style, watch}}`；返回推荐结果，不落库 |

存储为**单画像**语义：`src/storage.py` 的 `InvestorProfileRecord.owner_key` 唯一索引，默认 `owner_key="default"`（当前为单租户设计，暂无多用户画像隔离）。`get_investor_profile` / `upsert_investor_profile` / `clear_investor_profile` 均以 `owner_key` 为键。

`source` 取值为 `manual`（策略中心保存）或 `interview`（访谈采用）。

## 问股中的多策略对比

`POST /api/v1/agent/chat` 与 `POST /api/v1/agent/chat/stream` 支持在同一次问股中并行评估多个策略并返回对比结果。

### 策略解析（`_resolve_effective_skills`）

- 请求体字段名为 `skills`（同时兼容旧字段名 `strategies`，通过 `AliasChoices` 兼容）。
- 请求显式传 `skills`（含空数组 `[]`）时，原样使用，**不会**被画像覆盖；空数组表示「不指定策略」，走默认路由。
- 请求**未传** `skills` 字段（`None`）时，服务端读取已保存投资画像的 `skill_ids` 作为回退；画像不存在或为空时保持默认行为。
- 解析出的非空技能列表最终按 `max(1, config.agent_compare_max)` 截断。

Web 端 `ChatPage.tsx` 首次加载会用 `GET /api/v1/agent/profile` 预填策略选择框（过滤掉已下线的技能 id，并截断至前端自身的 `MAX_SELECTED_SKILLS=3`，与后端 `AGENT_COMPARE_MAX` 是两个独立常量，见「已知限制」）；发送消息时只有选中列表非空才会附带 `skills` 字段，否则省略该字段（此时会被服务端画像回退接管）。

### 配置：`AGENT_COMPARE_MAX`

`.env.example` / `src/config.py`：

```bash
# 多策略对比单次最多评估的策略数（1-5，默认 3）
# AGENT_COMPARE_MAX=3
```

- 环境变量未设置时默认 `3`（`AGENT_COMPARE_MAX_DEFAULT`）；配置值会被强制夹在 `[1, 5]` 区间内（`src/config.py`）。
- 该值只影响 API 层解析出的候选技能列表长度，不需要重启即可通过修改 `.env` + 重启进程生效（无 Web 侧配置项）。

### 前置条件：需要 `AGENT_ARCH=multi` + `AGENT_ORCHESTRATOR_MODE=specialist`

多策略「分别评估 + 对比」依赖 `AgentOrchestrator` 的 specialist 编排模式，**不是默认配置**：

- `AGENT_ARCH` 默认 `single`（沿用旧版单 Agent `AgentExecutor`）；只有设为 `multi` 才会构建 `AgentOrchestrator`。
- `AGENT_ORCHESTRATOR_MODE` 默认 `standard`（技术→情报→决策）；只有设为 `specialist` 时，编排器才会在决策阶段前插入按策略拆分的 `SkillAgent`，并在决策阶段前执行 `SkillAggregator` 聚合出共识意见。

在默认配置（`AGENT_ARCH=single`）下，即使画像/请求选择了多个策略，问股仍只是把多个策略说明合并进同一个单 Agent 系统提示词，产出单一综合结论；`skill_breakdown`/`skill_consensus` 字段会保持为空列表 / `null`，Web 端不会渲染对比表和共识卡片。要启用对比能力，需要在部署侧同时设置：

```bash
AGENT_ARCH=multi
AGENT_ORCHESTRATOR_MODE=specialist
```

### 响应契约：`skill_breakdown` / `skill_consensus`

`ChatResponse`（同步 `POST /chat`）与 SSE `done` 事件（`POST /chat/stream`）均携带以下**追加字段**（旧客户端可忽略，不影响原有 `success`/`content`/`session_id`/`error` 语义）：

`skill_breakdown`（`List[Dict]`，逐策略意见，默认 `[]`）：

| 字段 | 说明 |
| --- | --- |
| `skill_id` | 策略 id |
| `display_name` | 策略中文展示名（由 API 层用 skill manager 补全，orchestrator 层原始值等于 `skill_id`） |
| `signal` | `strong_buy` / `buy` / `hold` / `sell` / `strong_sell` |
| `confidence` | 0-1 置信度，保留 4 位小数 |
| `score_adjustment` | 该策略对综合评分的调整量 |
| `reasoning` | 该策略的推理说明 |
| `key_levels` | 关键价位等结构化数据（可能为空对象） |

`skill_consensus`（`Optional[Dict]`，聚合共识，默认 `null`）：

| 字段 | 说明 |
| --- | --- |
| `signal` | 聚合后的信号 |
| `confidence` | 聚合置信度 |
| `score_adjustment` | 聚合调整量（`raw_data.total_adjustment`） |
| `reasoning` | 聚合理由 |
| `skill_count` | 参与聚合的策略数量 |

`skill_consensus` 仅在 `skill_breakdown` 非空（即至少一个策略 Agent 成功产出意见）时才会非空，两者同源于 `src/agent/orchestrator.py` 的 `build_skill_breakdown` / `build_skill_consensus`。

### Web 渲染

`ChatPage.tsx` 在助手消息下依次渲染：

1. `SkillConsensusCard`（`apps/dsa-web/src/components/chat/SkillConsensusCard.tsx`）：`consensus` 为空时返回 `null`，不渲染卡片。
2. `SkillBreakdownTable`（`apps/dsa-web/src/components/chat/SkillBreakdownTable.tsx`）：`items` 为空时返回 `null`；非空时按策略渲染表格行（策略名/信号/置信度/评分调整），点击行可展开查看 `reasoning` 与 `key_levels`。

两者互不依赖，任一字段缺失都不影响另一个的渲染，也不影响消息正文（Markdown 内容）的展示。

## 降级与兼容性

- **单策略 Agent 失败不阻断整体**：`AgentOrchestrator._execute_pipeline` 中，技能 Agent（`_skill_agent_names` 集合内）失败时归类为非关键阶段，记录 warning 后继续流程，不会使整次问股失败；`SkillAggregator` 聚合失败时同样只记录 warning，`skill_breakdown`/`skill_consensus` 退化为空。
- **空画像不影响现状**：未保存过画像、或画像 `skill_ids` 为空时，问股维持原有默认路由行为（`SkillRouter` 按市场状态或 `AGENT_SKILLS` 手动配置选择单一/少量默认策略）。
- **旧客户端兼容**：`skill_breakdown`/`skill_consensus` 为追加字段，旧版 Web/Bot 客户端忽略这两个字段即可保持原有行为；请求体不传 `skills`/`strategies` 时行为与升级前一致（走服务端默认路由，现在会先尝试画像回退）。

## 已知限制

- **`AGENT_COMPARE_MAX` 与 specialist 编排的并发上限不完全一致**：`api/v1/endpoints/agent.py::_resolve_effective_skills` 会按 `AGENT_COMPARE_MAX`（1-5）截断候选技能列表并写入编排上下文；但 `AgentOrchestrator._build_specialist_agents` 内部通过 `SkillRouter.select_skills(ctx)`（默认 `max_count=3`）与随后的 `selected[:3]` 又做了一次硬编码截断。因此即使把 `AGENT_COMPARE_MAX` 调到 4 或 5，实际参与评估、体现在 `skill_breakdown` 中的策略数量目前仍不超过 **3**；`AGENT_COMPARE_MAX>3` 时只改变了传入编排上下文的候选列表长度，不改变最终对比数量。
- **Web 问股策略选择框的上限是前端独立常量**：`ChatPage.tsx` 的 `MAX_SELECTED_SKILLS=3` 是硬编码的前端限制，与后端 `AGENT_COMPARE_MAX` 配置无关联；调高 `AGENT_COMPARE_MAX` 不会让问股页允许勾选超过 3 个策略（画像页 `StrategyCenter` 的上限 5 与此无关，二者是不同页面的独立限制）。
- **「通用分析」与未选择策略在请求层面等价**：`ChatPage.tsx` 只有选中策略非空时才在请求体中附带 `skills` 字段；显式勾选「通用分析」（清空选择）与从未选择过策略一样都不发送该字段，因此都会被服务端的画像回退接管——如果用户已保存投资画像，即使在问股页显式选择「通用分析」，实际请求仍可能带上画像中的策略。

## 相关文件

- Web：`apps/dsa-web/src/pages/ProfilePage.tsx`、`apps/dsa-web/src/components/profile/InterviewWizard.tsx`、`apps/dsa-web/src/components/profile/StrategyCenter.tsx`、`apps/dsa-web/src/pages/ChatPage.tsx`、`apps/dsa-web/src/components/chat/SkillConsensusCard.tsx`、`apps/dsa-web/src/components/chat/SkillBreakdownTable.tsx`、`apps/dsa-web/src/api/agent.ts`
- API：`api/v1/endpoints/agent.py`
- Agent：`src/agent/skills/profile_recommender.py`、`src/agent/skills/profile_tags.py`、`src/agent/skills/router.py`、`src/agent/orchestrator.py`、`src/agent/factory.py`
- 存储：`src/storage.py`（`InvestorProfileRecord`）
- 配置：`src/config.py`（`agent_arch`、`agent_orchestrator_mode`、`agent_compare_max`）、`.env.example`
