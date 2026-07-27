# AlphaSift 选股生产就绪与后续能力闭环 — Follow-up Spec

- 日期：2026-07-26
- 状态：草案（待 review）
- 关联模块：AlphaSift 适配层、Web 选股页、投资画像、部署与验收
- 前置设计：`docs/superpowers/specs/2026-07-26-alphasift-default-enabled-navigation-design.md`
- 实现计划：`docs/superpowers/plans/2026-07-26-alphasift-production-readiness.md`

---

## 1. 背景与现状

前置改动已经完成以下产品行为：

- 左侧“选股”固定显示。
- 未声明 `ALPHASIFT_ENABLED` 的新安装默认开启。
- 显式 `ALPHASIFT_ENABLED=false` 继续生效。
- AlphaSift 关闭或适配层异常时，用户仍可进入页面查看状态与修复指引。

代码级能力也已存在：

- AlphaSift API、后台任务与任务轮询。
- Web 选股页面。
- 固定版本的 `alphasift.dsa_adapter` 依赖和 Docker/桌面打包校验。
- 8 个适配层策略：`balanced_alpha`、`capital_heat`、`dual_low`、`momentum_quality`、`oversold_reversal`、`quality_value`、`shrink_pullback`、`volume_breakout`。
- AlphaSift 初筛、LLM 重排以及 DSA 行情、基本面和新闻增强。

但当前功能仍标记为实验性质，尚未完成真实运行环境的端到端验收。当前本地实例还存在：

- `.env` 显式配置 `ALPHASIFT_ENABLED=false`。
- 前端开发服务与后端 API 没有形成可用连接。
- 尚未运行真实数据源与真实 LLM 的小规模选股 smoke。
- 尚未形成候选质量、超时、降级、资源消耗和部署回滚证据。

因此，“默认开启与固定入口”已经实现，但“可以默认面向生产用户启用”仍需要本 Spec 的验收闭环。

## 2. 目标 / 非目标

### 目标

1. 在本地受控环境完成真实 AlphaSift 端到端 smoke。
2. 验证 Web、后端、适配层、数据源、LLM 和后台任务的完整调用链。
3. 建立默认开启前的生产准入标准，包括可用性、降级、成本、资源和回滚。
4. 用可复现证据判断：
   - 保持默认开启并部署；
   - 固定入口保留，但服务暂时恢复默认关闭；
   - 或阻断发布并修复具体问题。
5. 将投资画像驱动选股和多市场扩展登记为独立后续阶段，避免与生产准入混为一个不可控大改动。

### 非目标

- 不在没有 smoke 证据时直接部署生产。
- 不为了让 smoke “通过”而吞掉数据源、LLM 或适配层错误。
- 不在运行时自动安装不受信任依赖。
- 不自动发通知、不自动加入自选股、不自动交易。
- 不把 AlphaSift 候选描述成投资建议。
- 第一阶段不修改 AlphaSift 策略算法。
- 第一阶段仍只验证 A 股 `cn`；HK/US 需要适配层声明支持后再开发。

## 3. 分阶段边界

| 阶段 | 内容 | 是否阻断首次部署 |
| --- | --- | --- |
| P0 | 本地端到端连通、真实 3 条候选 smoke、状态与截图 | 是 |
| P1 | 超时、降级、资源、任务生命周期和安全回归 | 是 |
| P2 | 候选质量评估与默认开启 Go/No-Go | 是 |
| P3 | 投资画像自动选择 AlphaSift 策略并重排候选 | 否，独立功能 |
| P4 | 港股/美股市场扩展 | 否，依赖 AlphaSift contract |

P0-P2 完成前，不执行生产部署。P3-P4 不应阻塞已经通过 P0-P2 的 A 股基础选股能力。

## 4. P0：本地端到端集成验收

### 4.1 运行拓扑

必须明确选择一种受支持拓扑，不能只启动 Vite 前端后让同源 `/api` 请求落到错误端口：

**方案 A：后端统一托管（推荐验收方式）**

- 先构建 Web 静态资源。
- 启动 DSA 后端 `--serve-only`。
- 浏览器直接访问后端 Web 地址。
- Web 与 API 同源，不需要额外 `VITE_API_URL`。

**方案 B：Vite + 独立 API**

- Vite 运行在前端开发端口。
- 后端运行在明确 API 端口。
- 启动 Vite 前显式设置 `VITE_API_URL=http://127.0.0.1:<api-port>`。
- 验证 CORS 和认证 Cookie 语义。

验收记录必须写明采用哪种拓扑和实际端口，不能把前端可打开等同于后端已连接。

### 4.2 本地配置

- 对受控本地实例显式设置 `ALPHASIFT_ENABLED=true`。
- 不修改或输出 LLM 密钥、provider 私有地址、额外 headers。
- 使用现有 DSA LLM 配置；若没有可用 LLM，允许验证本地因子降级，但不能把它记录为“LLM 重排成功”。
- 启动前确认 `.venv` 或打包后端能导入 `alphasift.dsa_adapter`。

### 4.3 必须通过的状态检查

1. `/api/health` 或当前实际健康检查接口返回成功。
2. `/api/v1/alphasift/status`：
   - `enabled=true`
   - `available=true`
   - `contract_version=1`
   - `strategy_count > 0`
3. `/api/v1/alphasift/strategies` 返回稳定策略列表。
4. 选股页不再出现“无法连接到本地服务”。
5. 页面加载本身不创建选股任务。

### 4.4 真实选股 smoke

首轮只运行：

- `market=cn`
- `max_results=3`
- 至少两个不同类型策略：
  - 价值类：`quality_value` 或适配层确认的价值策略；
  - 热度/动量类：`capital_heat` 或 `momentum_quality`。

每次记录：

- `task_id`、`run_id`
- 总耗时和各阶段可见进度
- `snapshot_source`、`snapshot_count`、`after_filter_count`
- `candidate_count`
- `llm_ranked`、`llm_coverage`、`llm_parse_errors`
- `warnings`、`source_errors`
- DSA 增强成功数量与失败原因
- 是否包含候选理由、风险、催化剂与观察项

任何空结果都必须有明确原因。不能只用“任务完成”作为成功判定。

## 5. P1：稳定性、降级与安全验收

### 5.1 超时和失败边界

验证以下场景：

- 快照源超时或不可用。
- DSA 行情/基本面/新闻单项失败。
- LLM 超时、限流、无合法 JSON 或不可用。
- AlphaSift 适配层异常。
- 后台任务失败、任务过期或后端重启后任务丢失。

要求：

- 单一增强源失败不拖垮整个候选流程。
- LLM 失败可降级为本地因子候选，并明确显示 `llm_ranked=false`。
- 适配层本身不可用时 fail closed，不能伪造候选。
- 错误信息不得暴露密钥、完整安装来源或私有请求头。
- 页面必须区分“无候选”“已降级”“调用失败”和“任务不可恢复”。

### 5.2 资源与并发

至少记录：

- 单次任务峰值内存。
- 单次任务总耗时。
- 外部请求数量或可观察近似值。
- LLM 请求次数与 token 使用。
- 两个并发选股任务是否争用全局环境、任务队列或数据源。
- Docker 当前 512MB memory limit 下是否稳定。

如 512MB 不足，必须先决定：

- 优化内存；
- 降低并发；
- 或更新 Docker 资源建议。

不能在没有证据时直接提高资源限制。

### 5.3 安全边界

- `/install` 继续遵守桌面模式或管理员认证边界。
- 普通 `status`、`strategies`、`screen` 不触发运行时安装。
- `ALPHASIFT_INSTALL_SPEC` 继续脱敏。
- 自定义策略字符串继续由适配层最终校验，不执行命令或导入任意路径。
- 选股结果不自动触发通知、自选股写入或交易动作。

## 6. P2：候选质量与默认开启决策

### 6.1 最小质量样本

至少选择两个不同交易日或数据快照，对以下策略各运行一次：

- 价值类
- 热点/资金类
- 趋势类
- 反转类

人工检查每组 Top 3：

- 股票代码和名称有效。
- 关键行情字段不自相矛盾。
- 推荐理由能对应因子或 LLM 判断。
- 热点标签能被新闻或行业上下文支持。
- 价值类候选不会仅凭低 PE/PB 给出“显著低估”的强结论。
- 风险和失效条件不是空泛模板。
- 没有 ST/停牌/流动性严重不足等明显反例未被提示。

### 6.2 Go/No-Go 门槛

**Go：保持默认开启并允许部署**

- P0 全部通过。
- P1 没有安全、崩溃或不可控资源问题。
- 真实 smoke 至少两种策略成功。
- 降级状态在 API 和 UI 上可辨认。
- 候选质量没有明显系统性误导。
- 回滚已演练或至少通过配置路径验证。

**Conditional Go：入口固定，但恢复默认关闭**

- 页面和适配层可用，但真实数据源/LLM 稳定性或成本暂不满足默认开启。
- 保留 `ALPHASIFT_ENABLED=false`，用户主动开启后使用。
- 文档明确实验状态和已知限制。

**No-Go：阻断部署**

- 适配层不可稳定导入。
- 任务经常崩溃或无法终止。
- 错误或日志泄露敏感配置。
- 降级结果被误标为正常 LLM 推荐。
- 候选存在明显系统性错误且没有风险提示。

## 7. P3：投资画像驱动选股

此阶段是独立功能，不属于 P0-P2 的生产准入修补。

### 7.1 当前断点

投资画像保存的是 DSA Agent skill IDs，例如：

- `value_undervalued`
- `hot_theme`
- `growth_quality`
- 趋势/反转等其它分析 skill

AlphaSift 选股接收的是另一套 strategy IDs，例如：

- `quality_value`
- `capital_heat`
- `momentum_quality`
- `oversold_reversal`

两者目前没有正式映射契约。不能直接把画像 skill ID 透传给 AlphaSift。

### 7.2 建议设计

新增 DSA 侧确定性映射层：

```text
investor profile skill IDs
    -> one or more AlphaSift strategy IDs + weights
    -> run selected screeners
    -> merge/dedupe candidates
    -> profile-fit rerank
```

要求：

- 映射由代码或配置化元数据确定，不能只让 LLM 临时猜策略。
- 用户可看到“为何画像选择了这些选股策略”。
- 用户可手动覆盖自动策略。
- 多策略候选按股票代码去重。
- 输出区分 screen score、LLM score 和 profile-fit score。
- 保守画像不能因热点策略高分覆盖风险限制。
- 未保存画像时保持当前手动选策略流程。

正式开发前需另写详细 Spec，确认映射表、权重、合并算法和 UI。

## 8. P4：港股与美股扩展

当前 Web 只开放 `cn`，后端也会依据 AlphaSift `supported_markets` 校验。

扩展前置条件：

- AlphaSift adapter 明确返回并支持 `hk` / `us`。
- 快照、日线、实时行情、基本面和新闻字段完成市场标准化。
- 代码格式与交易所身份不会在候选去重时被错误合并。
- 币种、市值、涨跌幅和交易时段正确。
- 港股/美股策略列表明确 market scope。

在适配层没有正式支持前，不应只在 Web 下拉框增加 HK/US 选项。

## 9. 可视证据

P0-P2 至少保留以下证据到 PR 描述或验收记录：

- 固定显示“选股”的侧边栏。
- `enabled=true, available=true` 的正常页面。
- 至少一组成功候选结果。
- 一组 LLM 或数据源降级状态。
- 一组服务关闭或适配层不可用状态。

截图不得作为一次性验收文件提交到仓库。

## 10. 部署与回滚

### 部署

完成 P0-P2 并获得 Go 后：

1. 目标环境显式设置 `ALPHASIFT_ENABLED=true`。
2. 重建镜像/桌面后端与 Web。
3. 验证 `import alphasift.dsa_adapter`。
4. 部署保存后的完整产物。
5. 重复状态、策略列表和 3 条候选 smoke。
6. 验证首页、问股、报告、设置和持仓基本路径。

### 回滚

第一层回滚：

```env
ALPHASIFT_ENABLED=false
```

重启后禁止策略读取和选股执行，但保留固定导航与状态说明。

第二层回滚：

- 回退上一镜像/桌面产物。
- 恢复旧前端静态资源。

本能力不新增数据库 schema，回滚不需要数据迁移。

## 11. Review 待确认事项

1. P0 验收采用后端同源托管，还是 Vite + 显式 `VITE_API_URL`？
2. 是否接受“真实 LLM 不可用时仅验证降级，但不允许 Go”？
3. Docker 512MB 是否作为硬性准入环境？
4. 候选质量样本是否要求两个交易日，还是一个交易日 + 两个快照即可？
5. P3 投资画像联动是否在首次部署之后单独推进？
6. P4 HK/US 是否保持未来项，等 AlphaSift contract 明确支持再设计？
