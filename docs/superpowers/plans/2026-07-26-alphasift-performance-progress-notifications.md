# AlphaSift 选股性能、等待体验与系统通知优化 Implementation Plan

> 对应设计：`docs/superpowers/specs/2026-07-26-alphasift-performance-progress-notifications-design.md`

**Goal:** 按“性能优化 → 等待体验优化 → 系统通知”的顺序，使选股更快、过程可解释、终态可提醒，同时保持结果、降级、隐私和现有客户端兼容。

**Status:** Phase 1 进行中；已完成 timings、adapter callback 兼容和候选级有界并发，真实环境前后基线与双任务隔离验收待完成。

**Delivery rule:** Phase 1、2、3 顺序执行并分别验收，建议独立 PR。前一 Phase 的阻断项未关闭时，不进入下一 Phase。

## Global Constraints

- 未经明确确认不执行 `git commit`、`git tag`、`git push`、部署或远程通知。
- 保留工作区现有改动，不覆盖当前 AlphaSift 默认开启、导航和生产验收相关工作。
- 先测量后优化；不以增加线程数替代瓶颈分析。
- 不修改策略算法、因子权重、候选结论或交易逻辑。
- 不暴露思维链、prompt、密钥、私有 URL、headers 或供应商原始响应。
- 新配置同步 `.env.example`、专题文档和中英文用户文档。
- UI 改动准备前后截图，但截图不提交到仓库。
- 每个 Phase 都必须提供改动、验证、未验证、风险和回滚。

---

## Phase 0：Review 与基线准备

### Task 0.1：确认设计决策

- [ ] Review 并批准对应 Design Spec。
- [ ] 确认三个独立 Phase/PR 的边界。
- [ ] 确认候选级默认最大并发数。
- [ ] 确认心跳和停滞阈值。
- [ ] 确认三类通知的默认关闭策略。
- [ ] 确认远程通知是否包含候选代码；默认不包含。
- [ ] 明确本轮不做任务取消。

**Stop condition:** 任一会改变 API、通知隐私或并发风险的决策未确认时，不实现。

### Task 0.2：建立干净的性能比较方法

**Read first:**

- `AGENTS.md`
- Design Spec
- `docs/alphasift-integration.md`
- `api/v1/endpoints/alphasift.py`
- `src/services/alphasift_service.py`
- `src/services/task_queue.py`
- `apps/dsa-web/src/pages/StockScreeningPage.tsx`
- AlphaSift 当前锁定 adapter 的 progress/context contract

- [x] 检查并记录 `git status`，标明用户已有改动。
- [x] 确认 Python 入口；优先 `.venv/bin/python`，不假设 `python` 命令存在。
- [ ] 固定测试机器、运行拓扑、市场、策略和 `max_results=3`。
- [x] 设计确定性 fake provider benchmark，覆盖三个候选的行情、基本面和新闻延迟。
- [ ] 设计真实运行记录模板，不保存密钥、prompt 或完整原始响应。
- [x] 确认 adapter 是否原生支持 progress callback；当前锁定 adapter 不支持，已保留可选 callback 向后兼容 contract。

**Output:** 基线运行说明、benchmark 输入和待测指标。

---

## Phase 1：性能观测与优化

### Task 1.1：先补失败测试——阶段计时

**Files:**

- Modify: `tests/test_alphasift_api.py`
- Modify or add targeted service tests under `tests/`

- [x] 为单调时钟阶段计时写测试。
- [x] 覆盖 adapter 有 progress callback 和旧 adapter 无 callback。
- [x] 覆盖 `timings` 为可选字段，旧响应断言不被破坏。
- [ ] 覆盖异常、LLM 降级和 DSA 部分失败仍关闭当前 timing span。
- [ ] 覆盖敏感字段不进入公开 metrics。

### Task 1.2：实现内部 progress reporter 与 timings

**Files:**

- Modify: `src/services/alphasift_service.py`
- Modify: `api/v1/endpoints/alphasift.py`
- Modify: `src/services/task_queue.py`（只增加最小 reporter 接入；Phase 2 再扩展活动历史）

- [x] 定义内部 stage 映射；Phase 1 endpoint 不序列化 adapter metrics，避免未审计字段外泄。
- [x] 使用 `time.monotonic()` 记录阶段时间。
- [x] `AlphaSiftService.screen()` 接收可选 progress callback，默认保持同步调用兼容。
- [x] endpoint 将 callback 映射到现有任务 progress/message。
- [ ] 如果 adapter 支持 callback，透传 snapshot/filter/LLM 事件。
- [x] 如果不支持，公开整体 `alphasift_screen` 阶段，不解析日志。
- [x] 最终 response 追加可选 `timings`。
- [x] 记录 queue wait、runtime lock wait 和后置增强耗时。

### Task 1.3：采集优化前基线

- [x] 运行确定性串行 benchmark 5 次并与并发路径比较；中位数约 161ms → 56ms，降低 65.5%。
- [ ] `dual_low` 冷运行 1 次、暖运行 3 次。
- [ ] 第二个高候选策略冷运行 1 次、暖运行 3 次。
- [ ] 记录总耗时、阶段耗时、峰值内存、请求数、候选和降级。
- [ ] 同时提交两个任务，记录 queue/lock wait，不把串行锁等待误报为数据源耗时。
- [x] 真实 LLM 未在整体期限内完成；已保留 mock 基线并明确真实基线缺口。

2026-07-27 真实运行记录：

- sandbox 内运行因市场数据域名不可解析而失败；授权联网后全市场快照成功并进入 LLM 重排。
- LLM 单次 `timeout_sec=60` 会在 JSON-mode retry 和 fallback model 链上重复，整体运行超过约 3 分钟仍未终止，手动停止。
- 当前 adapter 没有整体 LLM deadline/progress callback，因此无法形成可靠的真实暖运行中位数；这是 Phase 1 gate 阻断项，不能用增加 worker 或前端假进度规避。

**Stop condition:** timings 无法区分 AlphaSift 主运行和 DSA 后置增强时，不开始并发修改。

### Task 1.4：先补失败测试——候选级有界并发

**Files:**

- Modify or add targeted AlphaSift service tests under `tests/`

- [x] 三个候选并发但输出 rank 顺序稳定。
- [x] 最大并发不超过批准值。
- [x] 一个候选 timeout/异常不取消其它候选。
- [x] warning 与 enriched count 聚合正确。
- [x] 同一 candidate 不被多个 worker 共享写入。
- [x] 确定性 benchmark 中每轮 3 个候选恰好 3 次增强调用，无并发重复。
- [x] 并发数 1 恢复原串行语义，作为回滚开关。

### Task 1.5：实现候选级受控并发

**Files:**

- Modify: `src/services/alphasift_service.py`
- Modify: `src/config.py` 和 `src/core/config_registry.py`（仅在 review 决定需要用户配置时）
- Modify: `.env.example`（仅新增配置时）

- [x] worker 输入使用 candidate 副本。
- [x] worker 返回 index、增强字段和 warning。
- [x] 主线程按 index 合并。
- [x] 使用短生命周期 executor。
- [ ] 对 provider 线程安全和限流逐项确认；不安全的调用保持串行。
- [x] 保留原 timeout、fallback、缓存与 partial-success 语义。
- [x] 加入并发数 1 的可恢复路径。

### Task 1.6：判断是否继续做候选内部并发或缓存

- [ ] 重新运行 benchmark。
- [ ] 若后置增强已达到目标，停止扩大改动面。
- [ ] 若单候选串行仍是主要瓶颈，验证行情/基本面/新闻线程安全后另补测试。
- [ ] 若重复请求是主要瓶颈，先证明缓存 key/TTL/负缓存语义再实现。
- [ ] 不默认缓存最终 LLM 选股结果。

### Task 1.7：Phase 1 验收

- [ ] 确定性后置增强墙钟时间降低至少 30%。
- [ ] 提供真实暖运行中位数前后数据与解释。
- [ ] 候选、顺序、LLM 降级、warning 和 source error 无契约回归。
- [x] 确定性 benchmark 峰值由约 0.034MB 增至 0.043MB，请求次数保持每轮 3 次，无不可解释放大。
- [x] 两任务回归测试覆盖环境、headers、candidate、timings 不串线。
- [ ] 后端针对性测试通过。
- [ ] 更新专题文档和 `[Unreleased]`。

**Phase gate:** 正确性、安全性、资源或 fallback 回归均阻断 Phase 2。

---

## Phase 2：等待体验与活动可见性

### Task 2.1：先补失败测试——任务活动契约

**Files:**

- Modify: `src/services/task_queue.py`
- Modify: `tests/test_task_queue.py`
- Modify: `tests/test_alphasift_api.py`

- [ ] TaskInfo 新字段默认值和 copy/to_dict 测试。
- [ ] stage、stage label、progress mode、elapsed、metrics 序列化测试。
- [ ] recent events 最多 20 条且高频事件合并。
- [ ] heartbeat 不污染活动历史。
- [ ] 终态与心跳竞争不会把 completed 恢复成 processing。
- [ ] SSE payload 和 polling response 具有同一活动字段。
- [ ] 旧任务和普通分析任务保持兼容。

### Task 2.2：实现 bounded activity 与心跳

**Files:**

- Modify: `src/services/task_queue.py`
- Modify: `api/v1/endpoints/alphasift.py`
- Modify: `src/services/alphasift_service.py`

- [ ] 增加 `update_task_activity()`，统一进度、阶段和事件广播。
- [ ] metrics 严格白名单和长度限制。
- [ ] recent events 有界保存并带稳定 event ID。
- [ ] 由共享监控机制产生 15 秒心跳，不为每任务创建永久线程。
- [ ] 任务终态后停止心跳。
- [ ] 失败摘要脱敏。
- [ ] 保留 `progress/message` 兼容输出。

### Task 2.3：先补失败测试——Web 运行态

**Files:**

- Modify: `apps/dsa-web/src/api/alphasift.ts`
- Modify: `apps/dsa-web/src/pages/__tests__/StockScreeningPage.test.tsx`
- Add targeted component tests if activity timeline is extracted

- [ ] indeterminate 阶段不显示虚假总百分比。
- [ ] 已知 `current/total` 显示局部进度。
- [ ] elapsed 在本地递增，不每秒请求 API。
- [ ] 45 秒 stale hint、90 秒 warning。
- [ ] 业务活动与 heartbeat 文案不同。
- [ ] 页面恢复任务时恢复 stage 和 recent events。
- [ ] SSE 重连/轮询不会重复活动项。
- [ ] warning 与 running 状态可以同时显示。
- [ ] aria-live 不重复播报 heartbeat。

### Task 2.4：实现 Web 活动时间线

**Files:**

- Modify: `apps/dsa-web/src/api/alphasift.ts`
- Modify: `apps/dsa-web/src/pages/StockScreeningPage.tsx`
- Modify or add: `apps/dsa-web/src/components/tasks/`
- Modify: `apps/dsa-web/src/i18n/uiText.ts`
- Modify: `apps/dsa-web/src/index.css`（仅需要时）

- [ ] 当前阶段、elapsed、最近活动与 metrics 渐进展示。
- [ ] 默认展示最近 5～8 条，可展开到服务端保留上限。
- [ ] 使用 indeterminate activity indicator。
- [ ] 任务 ID、sessionStorage 恢复和错误处理保持不变。
- [ ] 复用现有 `useTaskStream`；SSE 不可用时保留当前轮询。
- [ ] 事件按稳定 ID 去重。
- [ ] 窄屏和深色主题检查。

### Task 2.5：Phase 2 验收

- [ ] 慢调用超过 60 秒时仍显示阶段、elapsed、最近心跳。
- [ ] 模拟无心跳分别触发 45/90 秒状态。
- [ ] 页面切换/刷新恢复。
- [ ] SSE 断线后轮询 fallback。
- [ ] 后端与 Web targeted tests。
- [ ] Web lint、build。
- [ ] 保存前后截图到 PR 描述。
- [ ] 同步中英文用户文档和 `[Unreleased]`。

**Phase gate:** 活动误报、敏感信息泄露、恢复失败或可访问性回归阻断 Phase 3。

---

## Phase 3：系统通知

### Task 3.1：确认通知产品边界

- [ ] Web、桌面、远程通知保持三个独立开关。
- [ ] 所有开关默认关闭。
- [ ] 本地通知默认仅页面不可见/窗口非前台时发送。
- [ ] 远程通知默认不含候选代码。
- [ ] 明确设置入口和权限拒绝后的说明。
- [ ] 确认远程 route type 名称和配置 key。

### Task 3.2：先补失败测试——Web 通知

**Files:**

- Add: `apps/dsa-web/src/services/` 下选股通知模块及测试
- Modify: `apps/dsa-web/src/pages/__tests__/StockScreeningPage.test.tsx`

- [ ] default/granted/denied/unsupported 权限。
- [ ] 权限只由显式用户点击请求。
- [ ] 页面后台完成/失败通知。
- [ ] 页面前台默认不通知。
- [ ] 同一 `task_id + terminal_status` 只通知一次。
- [ ] 刷新、SSE 重连、轮询重复终态不重复通知。
- [ ] 通知内容长度与敏感信息限制。
- [ ] 点击只聚焦/导航到选股页。

### Task 3.3：实现 Web 通知与偏好

**Files:**

- Add: `apps/dsa-web/src/services/stockScreenNotification.ts`
- Modify: `apps/dsa-web/src/pages/StockScreeningPage.tsx`
- Modify: `apps/dsa-web/src/i18n/uiText.ts`

- [ ] 增加用户手势触发的通知开关。
- [ ] 本地存储偏好与去重 TTL。
- [ ] 终态统一调用通知模块。
- [ ] denied/unsupported 提示可恢复、不阻断选股。
- [ ] 页面可见性规则可测试。

### Task 3.4：先补失败测试——Electron 原生通知

**Files:**

- Modify: `apps/dsa-desktop/tests/preload.test.js`
- Modify: `apps/dsa-desktop/tests/main.test.js`

- [ ] preload 只暴露固定 shape 的通知方法和 capability。
- [ ] main process 验证 sender、字段类型、长度和 status。
- [ ] 不接受任意 URL、HTML 或本地图标路径。
- [ ] Notification unsupported/构造失败不崩溃。
- [ ] 点击聚焦现有窗口并导航到受控选股路由。
- [ ] 同一终态幂等。

### Task 3.5：实现 Electron 通知桥

**Files:**

- Modify: `apps/dsa-desktop/preload.js`
- Modify: `apps/dsa-desktop/main.js`
- Modify: Web desktop runtime types/helpers

- [ ] 在 main process 使用 Electron `Notification`。
- [ ] preload 通过最小 IPC contract 转发。
- [ ] renderer 检测桌面能力后优先使用原生通知。
- [ ] 不同时触发浏览器和 Electron 两条本地通知。
- [ ] 复用 Web 的用户偏好和终态去重。

### Task 3.6：先补失败测试——后端远程通知

**Files:**

- Modify: notification routing/service targeted tests
- Modify: `tests/test_alphasift_api.py`
- Modify: system config tests if adding configuration

- [ ] 新 route type/config 的解析和 diagnostics。
- [ ] 完成/失败摘要。
- [ ] 终态落定后发送。
- [ ] 发送失败不改变 completed/failed 原终态。
- [ ] 幂等键阻止重复发送。
- [ ] 未配置时静默跳过但诊断可见。
- [ ] 内容脱敏。

### Task 3.7：实现远程通知（独立 commit/PR 范围）

**Files:**

- Modify: `src/notification_routing.py`
- Modify: `src/notification.py` 或新增专用选股通知 builder/service
- Modify: `api/v1/endpoints/alphasift.py` 或任务终态 hook
- Modify: `src/config.py`
- Modify: `src/core/config_registry.py`
- Modify: `.env.example`
- Modify: settings API/Web settings UI if exposed

- [ ] 新增明确的选股事件通知配置，默认关闭。
- [ ] 使用已有 NotificationService，不创建平行 sender。
- [ ] 终态后 best-effort 发送摘要。
- [ ] notification failure 写诊断，不覆盖任务结果。
- [ ] 使用稳定幂等键。
- [ ] 配置热加载与 diagnostics 行为一致。

### Task 3.8：Phase 3 验收

- [ ] 浏览器后台完成和失败各一次。
- [ ] Electron 最小化完成和失败各一次。
- [ ] 确认本地只出现一条通知。
- [ ] 一个远程测试渠道成功。
- [ ] 一个远程发送失败且任务结果不变。
- [ ] Web tests、lint、build。
- [ ] Desktop tests、build。
- [ ] 后端 targeted tests 和 `./scripts/ci_gate.sh`。
- [ ] 同步 `.env.example`、专题文档、中英文用户文档和 `[Unreleased]`。
- [ ] PR 描述附通知截图和隐私说明。

---

## Final Verification Matrix

具体测试文件名以实现时现有结构为准，至少执行：

```bash
.venv/bin/python -m pytest \
  tests/test_alphasift_api.py \
  tests/test_task_queue.py \
  tests/test_notification.py \
  tests/test_system_config_service.py -q

./scripts/ci_gate.sh

cd apps/dsa-web
npm run test -- StockScreeningPage.test.tsx alphasift.test.ts --run
npm run lint
npm run build

cd ../dsa-desktop
npm test
npm run build
```

另外保留：

- 性能基线与前后对照。
- 慢任务阶段/心跳/恢复证据。
- Web 与 Electron 通知证据。
- 远程通知成功和失败隔离证据。
- 未验证平台、风险和回滚说明。

## Handoff Checklist

每个 Phase 交付必须包含：

- 改了什么及为什么。
- 与 Spec 的差异和批准记录。
- 测试与真实验证结果。
- 性能或 UX 证据。
- 未验证项。
- 风险点。
- 回滚开关或回滚文件范围。
- 是否满足进入下一 Phase 的 gate。
