# AlphaSift 选股生产就绪与后续能力闭环 Implementation Plan

> 对应设计：`docs/superpowers/specs/2026-07-26-alphasift-production-readiness-design.md`

**Goal:** 用真实本地运行证据完成 AlphaSift A 股选股的生产准入判断，并把画像联动、多市场扩展拆成后续独立阶段。

**Status:** 待 review；建议在新 session 执行。

**Execution rule:** P0-P2 顺序执行。任一阻断条件命中时停止部署准备，先记录证据和根因。P3-P4 不与生产准入混在同一 PR。

## Global Constraints

- 未经明确授权不修改目标生产环境、不部署、不提交、不推送。
- 本地启用只修改受控开发环境的 `ALPHASIFT_ENABLED`。
- 不输出或提交任何密钥、私有 base URL、headers 或完整敏感配置。
- smoke 固定 `market=cn`、`max_results=3` 起步。
- 不自动通知、不写入自选股、不触发交易。
- 不用 broad fallback 掩盖适配层、数据源或 LLM 错误。
- UI 截图放在 PR/验收记录，不提交到仓库。

---

## Task 0：新 session 基线与运行拓扑确认

**Read first:**

- `docs/superpowers/specs/2026-07-26-alphasift-production-readiness-design.md`
- `docs/superpowers/specs/2026-07-26-alphasift-default-enabled-navigation-design.md`
- `docs/alphasift-integration.md`
- `AGENTS.md`

- [ ] 检查 `git status`，保留用户已有变更。
- [ ] 确认前置默认开启/固定导航代码仍在工作区或目标分支。
- [ ] 检查 `.env` 中 `ALPHASIFT_ENABLED`，只报告值，不打印其它敏感项。
- [ ] 选择验收拓扑：
  - 推荐：Web build + 后端同源托管；
  - 备选：Vite + `VITE_API_URL` 指向独立后端。
- [ ] 记录 API host/port、Web URL 和 Python 环境。
- [ ] 确认 `.venv/bin/python` 可导入 `alphasift.dsa_adapter`。

**Stop condition:** 无法确认后端运行入口、配置来源或依赖来源时，不继续真实 smoke。

## Task 1：启动受控本地环境

- [ ] 备份当前 `.env` 或使用可恢复的本地配置方式。
- [ ] 设置 `ALPHASIFT_ENABLED=true`。
- [ ] 不修改 LLM/provider/密钥相关配置。
- [ ] 构建 Web：

```bash
cd apps/dsa-web
npm run build
```

- [ ] 按选定拓扑启动后端或 Vite。
- [ ] 记录启动命令和日志文件位置。
- [ ] 确认健康检查成功。
- [ ] 确认前端能访问普通 API，不只验证页面静态资源。

**Recommended same-origin command:**

```bash
.venv/bin/python main.py --serve-only --host 127.0.0.1 --port 8000
```

**Stop condition:** 前端仍出现“无法连接到本地服务”时，先修运行拓扑，不进入选股质量测试。

## Task 2：适配层与 API 状态验收

- [ ] 直接导入并记录适配层 `get_status()` 的非敏感字段。
- [ ] 请求 `/api/v1/alphasift/status`。
- [ ] 断言 `enabled=true`、`available=true`、`contract_version=1`。
- [ ] 请求 `/api/v1/alphasift/strategies`。
- [ ] 保存策略 ID 列表和数量。
- [ ] 打开选股页，确认策略卡正常加载。
- [ ] 确认进入页面没有自动创建后台任务。

**Evidence:** 状态响应摘要、策略 ID 列表、正常页面截图。

## Task 3：真实 3 条候选 smoke

### 3A：价值类

- [ ] 使用 `quality_value`；若适配层文档指定其它价值策略，先记录差异。
- [ ] `market=cn`、`max_results=3`。
- [ ] 提交后台任务并轮询到终态。
- [ ] 记录 task/run/snapshot/filter/candidate/LLM/DSA enrichment 字段。
- [ ] 检查每个候选的理由、风险和关键上下文。

### 3B：热点或动量类

- [ ] 使用 `capital_heat` 或 `momentum_quality`。
- [ ] 使用同样的 3 条候选约束。
- [ ] 记录同一组运行字段。
- [ ] 检查热点/行业判断是否有数据或新闻依据。

**Stop conditions:**

- 任务无法进入终态。
- 适配层异常被包装成空候选。
- LLM 失败却显示 `llm_ranked=true`。
- 日志或响应出现敏感配置。

## Task 4：降级与故障可见性

- [ ] 验证显式 `ALPHASIFT_ENABLED=false`：
  - 导航仍显示；
  - 页面显示关闭状态；
  - 运行按钮不可用或 API 拒绝；
  - 不创建任务。
- [ ] 模拟或通过测试验证 adapter unavailable：
  - `status.available=false`；
  - 页面显示修复指引；
  - 不自动安装。
- [ ] 验证 LLM 不可用/超时：
  - `llm_ranked=false`；
  - 本地因子候选可辨认；
  - warning/source error 显示。
- [ ] 验证一个 DSA 增强源失败不拖垮其它候选。
- [ ] 验证不存在或过期任务显示“不可恢复”，而非无限轮询。

**Tests first:** 优先复用 `tests/test_alphasift_api.py` 与 `StockScreeningPage.test.tsx`；只有发现真实契约缺口才补代码。

## Task 5：资源、并发与任务生命周期

- [ ] 测量两次真实任务总耗时。
- [ ] 记录 Python 进程峰值内存或 Docker 内存。
- [ ] 记录 LLM 调用/token 使用摘要。
- [ ] 并发提交两个 `max_results=3` 任务。
- [ ] 验证临时 LLM 环境/header 不串请求。
- [ ] 验证任务队列状态与错误相互隔离。
- [ ] 明确后端重启后内存任务丢失的当前行为和 UI 提示。
- [ ] 在 Docker 512MB 限制下执行至少一次任务，或明确记录未验证及风险。

**Stop condition:** OOM、任务互相污染、密钥/header 串线或后台任务不可终止。

## Task 6：候选质量人工评估

- [ ] 建立不入库的验收记录，覆盖：
  - 价值类；
  - 热点/资金类；
  - 趋势类；
  - 反转类。
- [ ] 每类检查 Top 3 代码、名称、行情、理由、风险和失效条件。
- [ ] 核对价值类是否把“低指标”误写成确定性内在价值低估。
- [ ] 核对热点类是否有行业/新闻/量价证据。
- [ ] 核对 ST、停牌、流动性或异常数据风险。
- [ ] 至少覆盖两个交易日或两个明确不同的数据快照。

**Output:** 只提交结论摘要和脱敏证据，不提交一次性候选快照文件。

## Task 7：Go/No-Go 决策

- [ ] 汇总 P0-P2 证据。
- [ ] 按 Spec 第 6.2 节选择：
  - Go；
  - Conditional Go；
  - No-Go。
- [ ] 若 Go：生成部署清单。
- [ ] 若 Conditional Go：保留固定导航，将默认值恢复为关闭并说明原因。
- [ ] 若 No-Go：列根因、最小修复范围和重新验收条件。
- [ ] 更新 `docs/alphasift-integration.md` 的验证记录和已知限制。
- [ ] 如有代码修复，同步 `docs/CHANGELOG.md`。

## Task 8：部署准备（只有 Go 后执行）

- [ ] 后端针对性测试。
- [ ] Web 全量测试、lint、build。
- [ ] `./scripts/ci_gate.sh`；若有顺序相关失败，提供隔离复现与完整证据，不只声称“单测通过”。
- [ ] Docker build 与 `import alphasift.dsa_adapter`。
- [ ] 准备 UI 前后/状态/候选/降级截图。
- [ ] 目标环境配置变更单独列出。
- [ ] 回滚步骤验证。
- [ ] 请求用户明确部署授权。

## Task 9：投资画像联动（独立后续 Spec/PR）

- [ ] 先设计 DSA skill ID → AlphaSift strategy ID 映射表。
- [ ] 确认多策略运行数量、权重、候选去重和 profile-fit 算法。
- [ ] 确认保守画像风险约束。
- [ ] 设计“自动推荐 + 用户可覆盖”UI。
- [ ] 明确 screen score / LLM score / profile-fit score 展示。
- [ ] 新建独立 Spec，经 review 后开发。

本 Task 不得与 P0-P2 稳定性修复塞进同一个 PR。

## Task 10：HK/US 市场扩展（等待 adapter contract）

- [ ] 检查 adapter `supported_markets` 是否正式包含 `hk` / `us`。
- [ ] 若不支持：停止，不在 Web 添加选项。
- [ ] 若支持：另写市场扩展 Spec，覆盖代码格式、币种、快照、行情、基本面、新闻和交易时段。
- [ ] 分市场建立真实 smoke 和质量样本。

## Verification Matrix

```bash
.venv/bin/python -m pytest \
  tests/test_alphasift_api.py \
  tests/test_config_env_compat.py \
  tests/test_system_config_service.py \
  tests/test_docker_entrypoint.py \
  tests/test_packaging_build_scripts.py -q

cd apps/dsa-web
npm run test -- SidebarNav.test.tsx StockScreeningPage.test.tsx SettingsPage.test.tsx alphasift.test.ts --run
npm run lint
npm run build
```

真实验收另外记录：

- 健康检查。
- AlphaSift status/strategies。
- 两种策略各 3 条候选。
- 一次降级。
- 一次显式关闭。
- 一次 Docker 资源验证。
- Go/No-Go 结论。

## Handoff Output for the Next Session

新 session 最终必须交付：

- 采用的运行拓扑。
- 当前配置与依赖状态（脱敏）。
- 两次真实 smoke 结果摘要。
- 降级、资源和安全验证。
- 候选质量结论。
- Go/Conditional Go/No-Go。
- 已修改文件、测试、未验证项、风险与回滚。
- 是否建议请求部署授权。
