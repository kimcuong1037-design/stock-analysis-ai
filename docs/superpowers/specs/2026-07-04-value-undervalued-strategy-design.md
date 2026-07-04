# 价值低估策略（确定性 DCF 估值）+ 画像 value 标签断点修复 — 设计 Spec

- 日期：2026-07-04
- 状态：已确认（用户已批准设计方向与关键参数）
- 关联模块：策略/Agent 链路（`strategies/`、`src/agent/`）、数据层（`data_provider/`）、投资画像（`src/agent/skills/profile_tags.py`、`apps/dsa-web/`）
- 前置 Spec：`2026-06-21-investor-profile-strategy-advisor-design.md`（投资画像 + 策略中心 + 多策略对比）
- 实现计划：见同目录 `2026-07-04-value-undervalued-strategy-plan.md`（待生成）

---

## 1. 背景与问题

投资画像功能上线后（见前置 Spec），复盘"画像 → 问股"链路发现两个问题：

1. **没有价值投资策略**。`strategies/` 下现有 15 个策略以技术面/情绪面为主，仅
   `growth_quality`（成长质量）涉及基本面。用户即使是"价值型中长线投资者"，
   系统也没有一个真正基于企业内在价值（长期自由现金流折现）的策略可推荐、可挂载。
2. **访谈 `value` 风格答案是空转的**。访谈第 3 题提供"价值成长"选项（值 `value`，
   见 `apps/dsa-web/src/components/profile/InterviewWizard.tsx`），且
   `src/agent/skills/profile_tags.py` 的 `STYLE_VALUES` 已包含 `value`；但：
   - 没有任何策略 YAML 声明显式 `profile_tags`；
   - 标签全靠 `category` 推导，而 4 个类目（trend/pattern/reversal/framework）
     的推导规则没有一个映射到 `value`。

   结果：选"价值成长"的用户在权重最高的 style 维度（3.0）对所有策略都是 0 分，
   推荐实际只由持仓周期和风险偏好驱动。

另一个实现层约束：现有基本面管线（`data_provider/fundamental_adapter.py` 的
`get_fundamental_bundle`）只提取**最新一期**财报（`_extract_latest_row`），
无法支撑"长期可折算现金流"的估值计算，需要新增多年现金流历史获取能力。

## 2. 目标 / 非目标

### 目标

- 新增 **价值低估** 策略：以巴菲特/芒格/段永平的企业价值观为方法论——
  企业价值 = 存续期内可拿出来的自由现金流的折现值，估算必须保守、必须留安全边际。
- 估值计算走**确定性代码路径**（新增 Agent 工具），而非 LLM 心算：
  数值可复现、可单测；LLM 只负责调用工具并解读结果。
- 修复画像 `value` 风格标签断点：访谈选"价值成长"能稳定推荐出价值策略，
  存入画像后在问股中默认挂载。
- 覆盖 A 股 / 美股 / 港股三个市场，数据不足时优雅降级，不拖垮问股主流程。

### 非目标（本期不做）

- 不做逐公司精细估值模型（分部估值、研发资本化调整、股权激励摊薄细算等）。
  这是一个**保守的、标准化的**内在价值估算器，不是投研级 DCF 工作台。
- 不新增 env 配置项。折现率、安全边际等常数集中在估值引擎模块顶部，
  遵守"不配置也可运行"；未来确有需求再提级为配置。
- 不给全部 15 个存量策略补显式 `profile_tags`（用户确认只修 value 断点；
  仅 `growth_quality` 顺带补标签）。
- 不把画像的 horizon/risk 答案注入问股 prompt（用户确认不做，画像仅决定策略集合）。
- 不改动推荐引擎打分逻辑、SkillAggregator、ReAct 引擎。

## 3. 已确认的关键决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 估值实现形态 | **确定性估值工具 + 策略**（用户选定） | "长期可折算现金流"要求数值可复现；纯 prompt 心算不可测、不可信 |
| 链路修复范围 | **只修 value 标签断点**（用户选定） | 链路其余部分（画像→预填→回落→prompt 注入）核对后是通的 |
| 折现率 | 固定 10%（常数） | 巴菲特式机会成本口径；同时输出保守/基准两档区间弱化单点敏感性 |
| 安全边际阈值 | 折价 ≥ 30% 判定 undervalued | 价值投资通行的保守下限 |
| 策略分类 | 新增 `category: value`（"价值"） | 语义独立于"框架"；Web 策略中心对未知分类本就回落"其他"，追加分类是兼容变更 |
| 常数不进 env | 是 | 避免配置膨胀；遵守仓库稳定性护栏 |

## 4. 设计原则与复用

- **全部追加式**：新数据方法、新 service、新工具、新策略 YAML、新分类文案；
  不修改现有策略行为、问股 API 契约、聚合逻辑。
- **复用现有模式**：
  - 数据层沿用 `_call_df_candidates` 候选降级模式（akshare）与
    `yfinance_fundamental_adapter` 的字段拾取模式；
  - 工具注册沿用 `src/agent/tools/registry.py` + `TOOL_DISPLAY_NAMES`；
  - 策略 YAML 沿用现有 schema（`display_name` / `category` / `required_tools` /
    `instructions` / 评分调整建议格式），仅首次实际使用已有的可选字段 `profile_tags`。

## 5. 详细设计

### 5.1 数据层：多年现金流历史（`data_provider/`）

新增统一能力 `get_cashflow_history(stock_code) -> List[YearRecord]`，
标准化年度记录：

```python
{"year": 2025, "revenue": ..., "net_profit": ..., "ocf": ..., "capex": ...}
```

- 金额统一为浮点（原币种），并附 `currency` 与 `source` 元信息；
  按年份降序，目标 5–10 年，允许字段缺失（`None`）。
- **A 股**（`fundamental_adapter.py`）：按 `_call_df_candidates` 模式依次尝试
  akshare 年度现金流量表 / 财务摘要类接口（如 `stock_cash_flow_sheet_by_yearly_em`、
  `stock_financial_abstract`），用关键词拾取"经营活动产生的现金流量净额"、
  "购建固定资产无形资产和其他长期资产支付的现金"（capex 近似）、营业收入、归母净利润。
- **美股/港股**（`yfinance_fundamental_adapter.py`）：`ticker.cashflow`（年度，约 4 年）
  取 Operating Cash Flow 与 Capital Expenditure，`ticker.income_stmt` 取
  Total Revenue / Net Income；币种沿用现有 `financialCurrency` 处理逻辑。
- Manager 层按市场路由到对应 adapter；任一环节失败返回**空列表**并记录日志，
  不抛异常（单数据源失败不拖垮主流程）。

### 5.2 估值引擎：`src/services/valuation_service.py`

纯函数、零 LLM、零网络（数据由调用方传入）、确定性、可单测。

**输入**：年度序列（5.1 的输出）+ 当前总市值（+ 可选总股本）。

**计算步骤**：

1. **Owner earnings 基数**：`FCF_i = ocf_i - capex_i`；取近 N 年（N = 可用年数，
   上限 10）FCF **中位数**为基数 `B`，抗单年扰动。
   capex 缺失的年份用 `ocf × CAPEX_FALLBACK_RATIO`（保守折扣，如 0.8 倍 OCF 计 FCF）。
2. **增长假设**：`g1 = clamp(FCF 历史 CAGR, 0%, 15%) × GROWTH_HAIRCUT`
   （保守系数，如 0.7）；CAGR 不可算（负基数/年数不足）时 g1 = 0。
3. **两阶段 DCF**：阶段一 10 年，增长率从 g1 线性衰减至永续增长
   `g2 = 2.5%`；折现率 `r = 10%`。
4. **输出两档区间**：
   - 保守档：g1 减半（下限 0）；
   - 基准档：g1 原值。
5. **结论字段**：内在价值区间、每股价值（有股本时）、
   `discount = 1 - 市值 / 基准内在价值`、
   verdict ∈ {`undervalued`(折价 ≥ 30%), `fair`, `overvalued`(市值高于基准值),
   `unknown`(数据足够但缺市值，无法给折价判定)}。
6. **数据置信度**：`high`（≥5 年）/ `medium`（3–4 年）/ `insufficient`（<3 年）。
   `insufficient` 时仍返回计算结果但 verdict 固定为 `insufficient_data`，不下硬结论。
7. 负 FCF 基数：不做折现（无意义），直接返回 `verdict: not_applicable` 并说明原因
   （价值策略对现金流为负的公司本就应回避）。

所有常数（`DISCOUNT_RATE`、`TERMINAL_GROWTH`、`MARGIN_OF_SAFETY`、
`GROWTH_CAP`、`GROWTH_HAIRCUT`、`CAPEX_FALLBACK_RATIO`、`STAGE1_YEARS`）
集中在模块顶部并写明依据，不进 env。

### 5.3 Agent 工具：`estimate_intrinsic_value`

新增 `src/agent/tools/valuation_tools.py`：

- 签名：`estimate_intrinsic_value(stock_code: str) -> dict`。
- 流程：拉现金流历史（5.1）→ 取实时市值/股本（复用现有行情通道）→
  调估值引擎（5.2）→ 返回结构化 JSON：

```json
{
  "status": "ok | insufficient_data | not_applicable | error",
  "assumptions": {"fcf_base": ..., "g1": ..., "g2": 0.025, "discount_rate": 0.10},
  "valuation": {"conservative": ..., "base": ..., "per_share": ..., "market_cap": ..., "discount": ...},
  "verdict": "undervalued | fair | overvalued | unknown | insufficient_data | not_applicable",
  "data_confidence": "high | medium | insufficient",
  "yearly_series": [{"year": ..., "revenue": ..., "net_profit": ..., "ocf": ..., "capex": ..., "fcf": ...}]
}
```

- 注册进 tool registry；`TOOL_DISPLAY_NAMES` 增加中文显示名"估值计算"
  （问股进度条可见）。
- 任何内部异常捕获后返回 `status: error` + 原因，不向上抛。

### 5.4 策略：`strategies/value_undervalued.yaml`

- `name: value_undervalued`，`display_name: 价值低估`，`category: value`。
- 显式声明（仓库首个使用 `profile_tags` 的策略）：

```yaml
profile_tags:
  style: [value]
  horizon: [long]
  risk: [conservative, balanced]
```

- `required_tools`: `get_stock_info`、`get_realtime_quote`、
  `estimate_intrinsic_value`、`search_stock_news`。
- `market_regimes`: 不限定行情状态（价值策略全周期适用），按 schema 缺省语义处理。
- `instructions` 四层框架（对齐巴菲特/芒格/段永平方法论）：
  1. **能力圈**：收入、利润、经营现金流是否长期一致可理解；看不懂的公司直接
     降低确定性，提示回避。
  2. **好生意**：ROE 水平与稳定性、毛利率、现金流质量（OCF 与净利润的匹配度）、
     分红记录。
  3. **内在价值**：**必须调用 `estimate_intrinsic_value` 工具，禁止自行心算估值**；
     引用工具返回的假设与区间进行解读。
  4. **安全边际**：折价 ≥ 30% 才可给 buy/strong_buy；折价不足给 hold 并给出
     "什么价格值得买"；市值高于基准内在价值给 sell/hold。
  - 明确声明：不依据短线技术形态操作；技术面仅用于确认长期趋势未与基本面背离。
  - 评分调整建议对齐现有策略格式（`sentiment_score ±N`），如：
    折价 ≥ 30% 且现金流质量高 `+15`；工具返回 `not_applicable`（负 FCF）`-12`；
    高折价但依赖单年异常现金流 `-6` 等。

### 5.5 画像 value 标签断点修复

| 改动点 | 文件 | 内容 |
|--------|------|------|
| 分类推导 | `src/agent/skills/profile_tags.py` | `_CATEGORY_DEFAULTS` 增加 `value: {style: [value], horizon: [long], risk: [conservative, balanced]}` |
| 存量策略补标签 | `strategies/growth_quality.yaml` | 补显式 `profile_tags: {style: [value, framework], horizon: [long, swing], risk: [balanced]}`，作为价值型用户第二候选 |
| Web 分类文案 | `apps/dsa-web/src/components/profile/StrategyCenter.tsx` + `src/i18n/uiText.ts` | 分类映射与 i18n 增加 `strategyCenter.category.value`（中："价值"；英文文案同步） |

- 推荐引擎（`profile_recommender.py`）**零改动**：`STYLE_VALUES` 已含 `value`，
  打分逻辑通用。
- 修复后的端到端链路：访谈选"价值成长 + 中长线" → `value_undervalued`
  在 style（3.0）+ horizon（2.0）双维度命中，稳定进 Top-N → 存为画像 →
  问股未显式传策略时回落画像 → Agent system prompt 注入价值策略指令 →
  Agent 调用 `estimate_intrinsic_value` → 结论围绕内在价值与安全边际展开。

## 6. 兼容性与稳定性

- 全部新增追加式改动；不修改任何现有 API 字段、策略行为、聚合逻辑。
- 降级路径（均不阻断问股主流程）：
  - 现金流历史拉取失败/为空 → 工具返回 `insufficient_data`，策略指示降信心、
    输出观察结论；
  - 单市场数据源缺失（如港股 capex 拿不到）→ 逐字段容忍 + capex 回退近似；
  - 负 FCF → `not_applicable`，明确"价值策略回避"而非硬给估值；
  - 工具内部异常 → `status: error`，Agent 按普通工具失败处理。
- 新 `category: value` 对老前端是未知分类 → 现有代码回落"其他"分组，兼容。
- `profile_tags` 是已存在的可选 schema 字段，YAML 声明它不影响旧逻辑。

## 7. 测试策略

- 估值引擎（pytest，纯离线）：
  - 固定年度序列 → 期望区间/verdict 的确定性断言；
  - 边界：capex 缺失、负 FCF、<3 年数据、零增长、超高增长被 clamp、
    市值缺失。
- 数据解析（mock DataFrame，不走网络）：
  - A 股列名关键词拾取 → 标准化序列；
  - yfinance 行名拾取 → 标准化序列；
  - 空返回/异常 → 空列表。
- 工具层：注册存在性、JSON 契约字段完整性、内部异常 → `status: error`。
- 推荐回归：`{style: value, horizon: long}` 答案 → `value_undervalued` 进 Top-N；
  原有推荐测试不回归。
- 前端：`npm run lint && npm run build`；StrategyCenter 新分类分组渲染测试。
- 网络实调（akshare/yfinance 真实请求）只进 `-m network` 观测项，不阻断 CI。

## 8. 回滚方式

- 删除 `strategies/value_undervalued.yaml` + 工具注册两处即可完全下线能力；
  `valuation_service`、数据层方法保留不被调用，无副作用。
- `growth_quality` 的 `profile_tags`、`_CATEGORY_DEFAULTS` 的 `value` 条目、
  Web 分类文案均为独立小改动，可单独回退。
- 无 DB / API schema / env 变更，无迁移成本。

## 9. 分阶段实施（详见 plan 文档）

- **Phase 1**：数据层 `get_cashflow_history`（A 股 akshare + 美/港股 yfinance +
  manager 路由）+ 解析单测。
- **Phase 2**：`valuation_service` 估值引擎 + 确定性单测。
- **Phase 3**：`estimate_intrinsic_value` 工具 + 注册 + 显示名 + 契约测试。
- **Phase 4**：`value_undervalued.yaml` 策略 + value 标签断点修复
  （`_CATEGORY_DEFAULTS` / `growth_quality` / Web 分类文案）+ 推荐回归测试。
- **Phase 5**：文档（`strategies/README.md`、docs 专题）+ `docs/CHANGELOG.md`
  扁平条目 + 全量验证（`./scripts/ci_gate.sh`、web lint/build）。

## 10. 风险点

- **akshare 年度现金流接口的列名/可用性漂移**：用关键词拾取 + 多候选接口降级
  缓解；解析层有 mock 单测锁契约，线上问题只影响单工具降级。
- **yfinance 仅 ~4 年年度数据**：美/港股多数落在 `medium` 置信度；输出中如实
  标注，策略指令要求按置信度调整语气，不掩盖数据面窄的事实。
- **标准化 DCF 对金融股/强周期股失真**（银行 OCF 语义不同、周期股中位数失真）：
  属于已知方法论边界，策略 instructions 中明确提示这两类公司估值参考性有限；
  本期不做行业分支模型（见非目标）。
- **固定 10% 折现率的争议**：以保守/基准双档区间 + 假设透明化（assumptions
  全量返回并由 LLM 向用户复述）缓解单点参数敏感性。
