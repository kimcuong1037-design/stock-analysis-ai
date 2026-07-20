# akshare 港股日线超时熔断 — 设计文档

- 日期：2026-07-20
- 类型：feat / 稳定性改进
- 影响面：`data_provider/akshare_fetcher.py`（后端数据源，港股日线路径）
- 目标读者：后续实现该功能的开发者 / reviewer

## 1. 背景与问题

系统查询港股日线时，数据源优先级为 `AkshareFetcher`（东方财富，P1）→ `YfinanceFetcher`（P4）。当访问东方财富接口（`push2his.eastmoney.com`）不可达或缓慢时，`ak.stock_hk_hist()` 会在 requests 层读超时（默认约 15s），被 `_fetch_hk_data()` 包装成含 `TimeoutError` 字样的 `DataFetchError` 抛出，管理器再降级到 `YfinanceFetcher` 取到数据。

实测现象：单只港股查询要先白等约 19s（15s 读超时 + 限速休眠 + 开销）才降级成功。批量分析多只港股时，每只都会重复这段等待，累积显著拖慢主流程。

A 股主源是 `EfinanceFetcher`、美股直接走 `YfinanceFetcher`，都不经过这段港股超时路径，因此本问题仅存在于「akshare 港股日线」这一条路径。

参考现状代码：
- 港股取数入口：`data_provider/akshare_fetcher.py` 的 `_fetch_hk_data()`（当前实现约 807 行起）
- 路由分支：`_fetch_raw_data()` 内 `elif _is_hk_code(stock_code): return self._fetch_hk_data(...)`（约 474 行）
- 错误分类先例：`_classify_realtime_http_error()` 已能把异常归类为 `"timeout"` 等类别（约 245 行起）
- 冷却先例：`data_provider/longbridge_fetcher.py` 的连接冷却（`_cooldown_until` / `_mark_connection_cooldown()` / `LONGBRIDGE_CONNECTION_COOLDOWN_SECONDS`，约 43、429、444 行）

## 2. 目标与非目标

### 目标
- akshare 港股日线接口**连续超时**达到阈值后，在一段冷却期内对港股日线请求**快速失败**，让管理器毫秒级降级到 `YfinanceFetcher`，避免每只港股重复白等约 19s。
- 冷却状态、阈值、冷却时长均可通过配置调整，且**不配置也能运行**（默认即启用，符合仓库稳定性护栏）。

### 非目标
- 不改 A 股、ETF、美股取数路径。
- 不改 `DataFetcherManager`（`data_provider/base.py`）的过滤 / 降级逻辑与 fetcher 接口契约。
- 不做通用的跨数据源熔断框架。
- 不改实时行情（realtime quote）路径。
- 不改数据源默认优先级数值。

## 3. 方案选择

在 brainstorming 阶段对比了三种方案，最终选择**方案 A：Fetcher 内部冷却**。

- **方案 A（采纳）**：在 `AkshareFetcher` 实例内维护港股专用冷却状态。港股日线连续超时达到阈值后记录 `_hk_cooldown_until`，冷却期内的港股日线请求在进入限速休眠之前直接抛快速失败的 `DataFetchError`。与 Longbridge 冷却先例一致，不改管理器与接口契约，A 股/ETF 路径完全不受影响。
- 方案 B（否决）：在 `DataFetcherManager` 层做市场感知的通用可用性探测（如 `capability="daily_data:hk"`）。需要改 fetcher 接口契约和管理器过滤逻辑，影响面远超本次痛点。
- 方案 C（否决）：仅缩短港股请求超时时长。底层 15s 读超时在 akshare 库内部，外层不易直接改；且每只港股仍要各等一次超时，批量场景依旧累积。

## 4. 详细设计

### 4.1 状态

`AkshareFetcher` 实例新增两个字段（在 `__init__` 中初始化）：

- `_hk_timeout_streak: int = 0` — 港股日线连续超时次数。
- `_hk_cooldown_until: float = 0.0` — 冷却截止的单调/墙钟时间戳（用 `time.time()`，与 Longbridge 先例一致）。

状态是实例属性；`DataFetcherManager` 已通过 per-fetcher 调用锁（`_get_fetcher_call_lock` / `_call_fetcher_method`）串行化对同一 fetcher 实例的调用，因此港股日线取数天然线程安全，本设计不额外加锁。跨进程不共享冷却状态（CLI 单次运行 / 常驻服务进程内各自生效），可接受。

### 4.2 配置

新增环境变量 `AKSHARE_HK_COOLDOWN_SECONDS`：

- 默认 `180`（秒）。
- 取值 `0` 表示禁用熔断（等价回退到当前行为：每次都真实请求 akshare 港股）。
- 解析与容错沿用 Longbridge `_connection_cooldown_seconds()` 的写法：读取环境变量，空值或非法值回落默认 180，负值按 0（禁用）处理。
- 连续超时阈值固定为常量 `_HK_TIMEOUT_STREAK_THRESHOLD = 2`，不新增配置面，避免叠加开关。

### 4.3 触发与判定

在 `_fetch_hk_data()` 内实现，逻辑顺序如下：

1. **入口冷却检查**（在 `_set_random_user_agent()` / `_enforce_rate_limit()` **之前**，确保跳过限速休眠、真正省时）：
   - 若熔断启用（冷却秒数 > 0）且 `time.time() < _hk_cooldown_until`，直接 `raise DataFetchError("Akshare 港股数据源冷却中，跳过（连续超时熔断），剩余约 Ns")`，由管理器降级。
2. **真实取数**：调用 `ak.stock_hk_hist(...)`。
3. **成功路径**：正常返回前将 `_hk_timeout_streak` 清零（`_hk_cooldown_until` 不必显式重置，过期后自然失效；清零 streak 即可）。
4. **失败路径**：捕获异常后，用现有 `_classify_realtime_http_error(e)` 判断类别：
   - 类别为 `"timeout"`：`_hk_timeout_streak += 1`；若达到阈值且熔断启用，则设 `_hk_cooldown_until = time.time() + cooldown_seconds` 并打一条 WARNING（含连续超时次数与冷却截止时间），随后按现有逻辑抛 `DataFetchError`。
   - 其他类别（空数据、`rate_limit_or_anti_bot`、`remote_disconnect`、`request_error` 等）：**不计入** streak，维持现有错误语义与既有的 `RateLimitError` / `DataFetchError` 分支不变。

> 说明：现有 `_fetch_hk_data()` 的 except 分支已把 banned/blocked/频率/rate/限制 归为 `RateLimitError`，其余归 `DataFetchError`。本设计在该分支基础上，仅**新增** streak/cooldown 记账，不改变对外抛出的异常类型与既有语义。

### 4.4 恢复

冷却到期后，下一次港股日线请求自然放行做真实调用；若再次超时则重新累计 streak 并可能再次进入冷却。无需后台定时器。

### 4.5 可观测性

- 熔断开启（进入冷却）：一条 `WARNING`，包含连续超时次数、冷却秒数、冷却截止时间。
- 冷却期内跳过：`DEBUG` 级别（批量港股场景避免刷屏）。
- 成功清零：不额外打日志（保持现有日志密度）。

## 5. 测试策略

新增测试文件（与现有 `tests/test_akshare_history_timeout.py` 的 mock 风格一致，标记 `not network`）。用 monkeypatch 替换 `ak.stock_hk_hist` 和时间源，覆盖：

1. **连续超时触发熔断**：注入连续 2 次 timeout 异常后，第 3 次港股日线调用快速失败（`DataFetchError`，原因含"冷却"）且**不再触网**（stub 不被调用）。
2. **成功重置计数**：1 次超时后一次成功，streak 归零；再来 1 次超时不应立即触发熔断（需再累计到阈值）。
3. **冷却过期恢复**：进入冷却后，把时间推进到 `_hk_cooldown_until` 之后，下一次调用会真实调用 stub。
4. **禁用开关**：`AKSHARE_HK_COOLDOWN_SECONDS=0` 时，连续超时也不进入冷却，每次都真实调用 stub。
5. **非超时错误不计数**：注入 `RateLimitError` / 空数据 / 一般 `request_error`，streak 不增加、不进入冷却，异常类型与现状一致。
6. **A 股路径不受影响**：A 股日线调用不读写港股冷却状态（回归保护，确认边界隔离）。
7. **管理器集成**：`DataFetcherManager` 在 akshare 港股冷却期内，`YfinanceFetcher` 正常兜底返回港股日线（复用现有 manager 测试脚手架）。

## 6. 文档与配置同步

- `.env.example`：在数据源相关段落新增 `AKSHARE_HK_COOLDOWN_SECONDS` 说明（默认 180、0 禁用、语义与触发条件）。
- `docs/CHANGELOG.md` 的 `[Unreleased]`：追加一行扁平格式 `- [改进] akshare 港股日线连续超时后自动熔断降级，避免批量港股查询重复等待`。
- `docs/FAQ.md`：当前**没有**"港股查询慢"条目（Q1 讲的是美股价格识别），本次在"数据相关"段落**新增一条** FAQ，说明港股经东方财富超时会自动熔断降级到 Yahoo Finance，以及 `AKSHARE_HK_COOLDOWN_SECONDS` 的作用；同步评估 `docs/FAQ_EN.md` 是否需要新增对应英文条目（若未同步需在交付说明写明原因）。

## 7. 验证矩阵（Python 后端改动）

- `./scripts/ci_gate.sh`
- `python -m pytest -m "not network" tests/test_akshare_history_timeout.py <新增测试文件>`
- `python -m py_compile data_provider/akshare_fetcher.py`
- 交付说明需覆盖：数据源 fallback 路径是否受影响（结论：仅港股日线路径新增快速失败分支，A 股/ETF/美股/实时行情不变）。

## 8. 风险与回滚

### 风险
- 冷却期内若 yfinance 也不可用，港股日线会更快地整体失败（而非等 akshare 超时后再失败）。属可接受权衡：yfinance 是港股既有兜底源，其自身失败与本改动无关；且熔断只影响时序，不减少可用数据源数量。
- 阈值 2 / 默认 180s 为经验值；若东方财富只是偶发抖动，可能在恢复后仍处冷却期而短暂多走一次 yfinance。影响仅为数据源选择，不影响数据正确性。

### 回滚
- 配置层：`AKSHARE_HK_COOLDOWN_SECONDS=0` 即时禁用熔断，恢复当前行为。
- 代码层：revert 对应单个 PR。

## 9. 交付说明骨架（实现完成后填写）

- 改了什么 / 为什么这么改 / 验证情况 / 未验证项 / 风险点 / 回滚方式（按 `AGENTS.md` 第 9 节）。
