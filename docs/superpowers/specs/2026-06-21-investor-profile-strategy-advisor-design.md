# 投资画像 + 策略中心 + 多策略对比 — 设计 Spec

- 日期：2026-06-21
- 状态：草案（待 review）
- 关联模块：问股 / Agent 链路（`src/agent/`、`api/v1/endpoints/agent.py`、`apps/dsa-web/`）
- 实现计划：见同目录 `2026-06-21-investor-profile-strategy-advisor-plan.md`（待生成）

---

## 1. 背景与问题

"问股"功能底层是一个 ReAct Agent，支持挂载可切换的**交易技能/策略**（skill），如牛市趋势、缠论、波浪理论、箱体震荡、情绪周期等。
策略定义存放在仓库根 `strategies/*.yaml`，由 `src/agent/skills/base.py` 加载，每个策略含 `display_name` / `description` / `category` / `instructions` 等字段。

当前痛点：

1. **选择门槛高**：普通投资者面对一堆专业策略名词，不知道该选哪个、组合哪几个。
2. **选择不持久化**：`apps/dsa-web/src/pages/ChatPage.tsx` 每次新会话都把策略重置为系统默认，用户的偏好留不住。
3. **看不到"分策略"的结果**：在多 Agent 模式下，多个策略其实是各自独立评估（每个策略一个 `SkillAgent`，产出独立 `Opinion`），但 `SkillAggregator` 把它们融合成一个"共识"后，个体结果没有透出到上层，用户无法分策略对比。

## 2. 目标 / 非目标

### 目标

- 提供一个**用户友好的访谈向导**，根据回答推荐一组策略，存为"我的投资画像"，可随时编辑。
- 访谈**可跳过**，提供"策略中心"直选入口，每个策略有人话简介与分类。
- 支持**多策略对同一只股票分别评估并对比**：一张对比表 + 综合共识，每条可展开看详情。
- 画像作为问股/分析的默认策略来源（预填 ChatPage 选择器）。

### 非目标（本期不做）

- 多用户 / 多租户隔离（系统当前为单租户，仅保留前向兼容的 `owner_key`）。
- Bot、桌面端的独立适配（桌面端 Electron 复用同一 Web 构建，自动继承；Bot 暂不做）。
- 多个命名画像/方案切换（本期只做单一可编辑画像）。
- 自定义策略上传 UI（沿用现有 `AGENT_SKILL_DIR` 机制，不在本期范围）。
- 重构 ReAct 引擎、聚合算法或新增并行执行框架。

## 3. 已确认的关键决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 对比结果形态 | **对比表 + 共识，可展开详情** | 最大化复用现有 `SkillAggregator`，成本可控 |
| 偏好模型 | **单一可编辑投资画像** | 贴合单租户架构，简单清晰 |
| 访谈映射方式 | **规则映射打底 + LLM 润色解释** | 推荐集合确定可测；LLM 只生成个性化解释，可降级 |
| 终端范围 | **仅 Web（桌面端自动复用）** | 范围最小，访谈是可视化向导，Web 最合适 |
| 访谈题量 | **4 题**（持仓周期 / 风险偏好 / 交易风格 / 盯盘投入） | 覆盖策略目录关键维度 |
| 画像容量 | 最多存 **5** 个策略 | 够用且不至于稀释对比 |
| 单次对比策略数 | 默认 **≤3**（配置 `AGENT_COMPARE_MAX`） | 与 orchestrator 现有 `selected[:3]` 及前端上限一致 |
| 入口形态 | 投资画像为**独立页面/区块** + ChatPage 默认预填画像 | 既有独立配置入口，又无缝接入问股 |

## 4. 设计原则与复用

核心洞察：**多策略对比所需的"各策略独立信号"，后端在多 Agent 模式下已经算出来了**——每个策略对应一个 `SkillAgent`（`src/agent/skills/skill_agent.py`），其 `post_process` 已产出含 `signal` / `confidence` / `score_adjustment` / `reasoning` 的 `AgentOpinion`；只是 `SkillAggregator`（`src/agent/skills/aggregator.py`）聚合成共识后，个体 Opinion 没有往结果对象上透出。

因此本设计的主体是 **"把已有数据透出来 + 好好渲染" + "在前面加一层策略配置"**，而不是重造分析。

| 需求 | 复用 | 新增 |
|------|------|------|
| 策略简介 | 策略 YAML 的 `display_name` / `description` / `category` | `GET /agent/skills` 补充字段 |
| 多策略分别评估 | 多 Agent 模式下各 `SkillAgent` 独立 `Opinion` | 把独立 Opinion 透出到结果对象 |
| 共识 | `SkillAggregator` 加权聚合 | 无 |
| 偏好持久化 | `storage.py` 的 ORM + CRUD 模式（参考 `AlertRuleRecord`） | 单行 `investor_profile` 表 |

## 5. 详细设计

### 5.1 数据模型

在 `src/storage.py` 新增 `InvestorProfileRecord`（仿 `AlertRuleRecord` 的 ORM 模型 + CRUD 函数写法）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int PK | |
| `owner_key` | str, unique, 默认 `"default"` | 单租户下恒为 `default`；预留多用户场景 |
| `skill_ids_json` | text | 选中策略 id 列表（JSON 数组） |
| `interview_answers_json` | text, nullable | 访谈原始答案，便于"重新编辑访谈"回填 |
| `source` | str | `"interview"` / `"manual"` |
| `created_at` / `updated_at` | datetime | |

- "单一可编辑画像" = 对 `owner_key='default'` 做 **upsert**。
- 保留 `owner_key` 唯一约束，既保证单画像，又不堵死未来多用户；当前不向 UI 暴露该字段。
- CRUD 函数：`get_investor_profile(owner_key="default")`、`upsert_investor_profile(...)`、`clear_investor_profile(...)`。

### 5.2 访谈向导（规则映射 + LLM 润色）

**问题集（4 题，纯前端渲染）**

1. 持仓周期：超短(日内~数日) / 波段(数天~数周) / 中长线(数月+)
2. 风险偏好：保守 / 均衡 / 激进
3. 交易风格：趋势跟随 / 低吸反转 / 题材情绪 / 价值成长 / 技术框架(缠论·波浪)
4. 盯盘投入：随时盯盘 / 每天看几次 / 没空盯盘

**策略侧元数据**

- 给 Skill schema 增加**可选**字段 `profile_tags`（`horizon` / `risk` / `style` 三组标签），从 YAML 读取。
- **缺省回退**：策略未声明 `profile_tags` 时，从已有 `category` / `market_regimes` 推导默认标签 → 存量策略不改也能参与推荐（符合"不配置也可运行"）。

**推荐引擎**

- 新建 `src/agent/skills/profile_recommender.py`：
  - 输入：访谈答案 + 可用策略列表（含 `profile_tags`）。
  - 逻辑：对每个策略按"答案命中标签"加权打分，按分数降序取 Top-N（默认 3，上限 5）。
  - 纯函数、零 LLM、确定性、单测覆盖。
- **LLM 仅负责**：用"推荐结果 + 各策略 description"生成一段"为什么这些适合你"的解释文案。
  - 失败/超时降级：用各策略 `description` 拼接的静态文案，不阻断推荐。

### 5.3 策略中心（直选入口）

- 增强 `GET /api/v1/agent/skills`：`SkillInfo` 补充 `category`、（可选）`profile_tags`、`is_default`。
- Web 新增"策略中心"视图：按 `category`（趋势/形态/反转/框架）分组，卡片展示 `display_name` + `description` + 适合标签，可勾选；勾选结果可"存为我的画像"。

### 5.4 多策略对比

- 后端：在 `OrchestratorResult` 增加字段
  `skill_breakdown: List[{skill_id, display_name, signal, confidence, score_adjustment, reasoning, key_levels}]`，
  由已存在的各 `SkillAgent` Opinion 填充；共识仍由 `SkillAggregator` 给。
- API：`/agent/chat` 与 `/agent/chat/stream` 在响应（`dashboard` 旁）附带 `skill_breakdown`。**追加字段，向后兼容**，老客户端忽略即可。
- 数量：画像最多 5 个策略；单次对比默认跑 `≤AGENT_COMPARE_MAX`（默认 3，与现有 `selected[:3]` 及前端上限一致）。
- Web 对比视图：共识结论卡 + 各策略信号对比表，每行可展开看该策略的理由 / 买卖点。

### 5.5 API 汇总

| 方法 | 路径 | 用途 | 改动类型 |
|------|------|------|---------|
| GET | `/api/v1/agent/profile` | 读当前画像 | 新增 |
| PUT | `/api/v1/agent/profile` | upsert 画像（手动选或访谈结果） | 新增 |
| POST | `/api/v1/agent/profile/interview` | 提交访谈答案 → 返回推荐策略 + 解释（**不自动保存**） | 新增 |
| GET | `/api/v1/agent/skills` | 增补 `category` / `profile_tags` / `is_default` | 增强（兼容） |
| POST | `/api/v1/agent/chat[/stream]` | 结果附 `skill_breakdown`；默认策略取自画像 | 增强（兼容） |

### 5.6 Web UI（仅 Web，桌面端自动继承）

1. 新页面/区块"投资画像"：两条入口——「做个访谈」(向导) 或「直接选策略」(策略中心)，结果存为画像。
2. `ChatPage.tsx` 策略选择器：默认**预填画像里的策略**（替代当前每次重置为单一默认）。
3. 对比视图：作为多策略分析结果的渲染增强。
4. 文案走 `apps/dsa-web/src/i18n/uiText.ts` / `apps/dsa-web/src/utils/systemConfigI18n.ts`。

### 5.7 配置

- 新增 `AGENT_COMPARE_MAX`（默认 3）：单次对比最大策略数。
- 同步更新 `.env.example` 与相关 `docs/`（遵守仓库硬规则）。
- 不新增互斥开关；画像为空时行为 = 现状（使用系统默认策略）。

## 6. 兼容性与稳定性

- **全部新字段追加式**，不删改 `dashboard` 既有结构 → 老 Web/桌面端不受影响。
- 降级路径（均不阻断主流程）：
  - 画像为空 / 访谈跳过 → 用系统默认策略（现状行为）。
  - LLM 解释失败 → 退化为静态文案。
  - 策略缺 `profile_tags` → 从 `category` / `market_regimes` 推导。
  - 单策略 `SkillAgent` 失败 → 沿用现有 Agent 失败处理，不拖垮其余策略与共识。

## 7. 测试策略

- 后端（pytest，`-m "not network"`）：
  - 推荐引擎：给定访谈答案 → 期望 Top-N 策略集合（确定性断言）。
  - 画像 CRUD：upsert / get / 单行约束 / 空画像默认行为。
  - 多策略对比：传 N 个策略 → 返回 N 条 `skill_breakdown` + 共识；含单策略失败的降级用例。
  - 兼容性：不传策略 / 老 payload → 行为同现状。
- 前端（`npm run lint && npm run build` + 组件测试）：策略中心分组、访谈向导、对比视图渲染、ChatPage 预填。
- 网络层不引入新的强依赖；LLM 解释走可降级路径。

## 8. 回滚方式

- 新表与新端点相互独立。移除"画像预填"即回到现状；保留 DB 表不影响旧逻辑。
- `skill_breakdown` 为追加字段，前端不消费即与现状一致。
- `AGENT_COMPARE_MAX` 不配置时取默认值，等价现有行为。

## 9. 分阶段实施（详见 plan 文档）

- **Phase 1**：后端画像表 + CRUD + 推荐引擎 + `GET/PUT /agent/profile`、`POST /agent/profile/interview`。
- **Phase 2**：多策略对比后端透出（`skill_breakdown`）+ `AGENT_COMPARE_MAX`。
- **Phase 3**：Web 策略中心 + 访谈向导 + 画像保存/编辑。
- **Phase 4**：Web 对比视图 + ChatPage 画像预填。
- **Phase 5**：文档与收尾（`docs/` 专题、`docs/CHANGELOG.md` `[Unreleased]`、`.env.example` 核对）。

## 10. 待确认 / 风险点

- `profile_tags` 是否需要逐个补到现有 `strategies/*.yaml`，还是仅靠 `category`/`market_regimes` 推导即可——本期默认"先推导，按需补标签"。
- 对比视图放在 ChatPage 内联渲染，还是独立"对比"页面——倾向内联增强，Phase 4 实现时再定。
- 访谈推荐的解释文案默认走问股使用的 Agent LLM，需确认 token 成本可接受（一次性、低频）。
