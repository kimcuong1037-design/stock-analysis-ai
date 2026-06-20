# 代码地图（Code Map）

本文件面向开发者和贡献者，提供整个仓库的结构总览、各子系统职责，以及一次股票分析从触发到推送的端到端工作流。目标是让新人能在不通读全部代码的情况下，快速建立系统的心智模型。

> 关联文档：[文档中心](../INDEX.md) · [完整配置与部署指南](../full-guide.md) · [API 规格](api_spec.json) · 协作规则见仓库根目录 [AGENTS.md](../../AGENTS.md)。
>
> 本文是结构与流程说明，不是逐行 API 文档；当描述与实际代码、脚本、工作流不一致时，以可执行内容为准，并顺手修正本文。

## 1. 它是什么

一套覆盖 **A 股 / 港股 / 美股** 的智能股票分析系统。核心主链路是：

> **抓取数据 → 技术分析 + 新闻检索 → LLM 综合分析 → 生成报告 → 多渠道通知推送**

同一套 Python 分析内核对外暴露为四种形态：命令行（CLI）、FastAPI Web 服务 + React 单页应用、Electron 桌面端、聊天机器人（Bot/IM）接入。

## 2. 顶层目录结构

```text
stock-analysis-ai/
├── main.py                 CLI 主入口 —— 所有运行模式
├── server.py / webui.py    FastAPI / WebUI 启动器（薄封装）
│
├── src/                    ◄── Python 分析内核
│   ├── core/               主流程编排（pipeline.py、market_review.py）
│   ├── stock_analyzer.py   确定性技术分析（MA/MACD/RSI/信号打分）
│   ├── analyzer.py         LLM 综合分析 → AnalysisResult
│   ├── market_analyzer.py  大盘（指数/板块）复盘
│   ├── llm/ + agent/       LiteLLM 抽象 + agent 工具调用循环
│   ├── search_service.py   新闻/网络检索（Bocha/Tavily/Brave/SerpAPI/SearXNG）
│   ├── services/           业务服务层（task_queue、history、portfolio、alerts…）
│   ├── repositories/       数据访问层（按表 CRUD）
│   ├── storage.py          SQLAlchemy ORM + DatabaseManager（SQLite）
│   ├── schemas/            报告/数据结构契约
│   ├── reports/ report_renderer formatters md2img   报告渲染
│   ├── notification*.py + notification_sender/       多渠道推送
│   ├── auth.py             Cookie 会话鉴权（HMAC + PBKDF2）
│   ├── scheduler.py        每日定时 + 配置热重载
│   └── config.py           基于 .env 的配置单例
│
├── data_provider/          ◄── 多数据源 + fallback 降级链
│   ├── base.py             DataFetcherManager + BaseFetcher（编排）
│   └── *_fetcher.py        efinance/akshare/tushare/pytdx/baostock/yfinance/longbridge/…
│
├── api/                    ◄── FastAPI 应用
│   ├── app.py              应用工厂（CORS、lifespan、SPA 静态托管）
│   ├── v1/                 11 个路由分组（analysis、history、auth、portfolio…）
│   ├── middlewares/        鉴权守卫
│   └── deps.py             依赖注入（db session、config）
│
├── bot/                    ◄── 聊天机器人接入
│   ├── dispatcher / handler 命令路由 + webhook 处理
│   ├── commands/           /analyze、/ask、/chat、/market、/history…
│   └── platforms/          飞书、钉钉、Discord 适配器
│
├── apps/
│   ├── dsa-web/            React 19 + Vite + Zustand 单页应用（构建产物输出到 /static）
│   └── dsa-desktop/        Electron 壳（拉起后端、加载 localhost）
│
├── strategies/             可插拔分析策略/skill
├── tests/                  pytest 测试（标记：unit/integration/network）
├── scripts/                ci_gate.sh、test.sh、构建脚本
├── docker/                 多阶段 Dockerfile + compose
├── .github/workflows/      CI 门禁、自动 tag、发布、每日分析 cron
└── docs/                   中英双语文档 + CHANGELOG
```

## 3. 核心子系统职责

| 子系统 | 入口/关键文件 | 职责 |
| --- | --- | --- |
| 主流程编排 | [src/core/pipeline.py](../../src/core/pipeline.py) | 协调单只股票的端到端分析；多股并发 fan-out；进度回调；落库与触发通知 |
| 技术分析（确定性） | [src/stock_analyzer.py](../../src/stock_analyzer.py) | 纯指标计算：均线排列、乖离率（vs MA5）、量能、MACD/RSI、支撑阻力、买点信号打分。**不调用 LLM** |
| LLM 综合分析 | [src/analyzer.py](../../src/analyzer.py) | 把技术面 + 基本面 + 新闻拼成 prompt，调用 LLM，解析为结构化决策仪表盘 `AnalysisResult` |
| 大盘复盘 | [src/market_analyzer.py](../../src/market_analyzer.py) · [src/core/market_review.py](../../src/core/market_review.py) | 聚合指数/板块/新闻，按市场（CN/HK/US）生成大盘复盘 |
| 数据层 | [data_provider/base.py](../../data_provider/base.py) | 多数据源按优先级 fallback、按市场路由、字段标准化、缓存/限流/重试 |
| LLM 抽象 | [src/llm/](../../src/llm/) · [src/agent/llm_adapter.py](../../src/agent/llm_adapter.py) | 基于 LiteLLM 的多渠道统一客户端、模型 fallback 链、参数自愈、思考模型处理 |
| 新闻检索 | [src/search_service.py](../../src/search_service.py) | 多搜索源（多 Key 轮询）抓取风险/利好/财报相关情报 |
| 报告渲染 | [src/services/report_renderer.py](../../src/services/report_renderer.py) · [src/formatters.py](../../src/formatters.py) · [src/md2img.py](../../src/md2img.py) | `AnalysisResult` → Markdown → HTML → PNG / 飞书文档 |
| 通知推送 | [src/notification.py](../../src/notification.py) · [src/notification_sender/](../../src/notification_sender/) | 多渠道路由、能力适配、噪声抑制、单渠道失败隔离 |
| Web 服务 | [api/app.py](../../api/app.py) · [api/v1/](../../api/v1/) | FastAPI 应用、SPA 托管、异步任务 + SSE |
| 持久化 | [src/storage.py](../../src/storage.py) · [src/repositories/](../../src/repositories/) | SQLite + SQLAlchemy ORM，服务编排、仓储只做 CRUD |
| 鉴权 | [src/auth.py](../../src/auth.py) · [api/middlewares/](../../api/middlewares/) | 可选开关、Cookie 会话（HMAC 签名）、PBKDF2 口令、登录限流 |
| 定时调度 | [src/scheduler.py](../../src/scheduler.py) | 每日定时执行，每次运行热重载 `.env` 配置 |
| 配置 | [src/config.py](../../src/config.py) · [src/core/config_registry.py](../../src/core/config_registry.py) | `.env` 驱动的配置单例与字段注册表 |

## 4. 端到端工作流

### 4.1 单只股票分析主链路

由 [src/core/pipeline.py](../../src/core/pipeline.py) 的 `analyze_stock()` 编排：

```text
实时行情 + 筹码分布           ← data_provider/
  → 技术趋势分析             ← src/stock_analyzer.py    （确定性指标）
  → 多维新闻检索             ← src/search_service.py    （可选）
  → 基本面上下文（财报/资金流）  ← data_provider/fundamental_adapter.py
  → 拼 prompt 调用 LLM        ← src/analyzer.py → src/llm / src/agent
  → 解析 JSON → AnalysisResult ← 后处理（决策稳定化、筹码结构补全）
  → 渲染报告（Markdown→HTML→PNG）← src/services/report_renderer + md2img
  → 推送到各通知渠道           ← src/notification* + notification_sender/
```

值得记住的职责切分：

- **`stock_analyzer.py`** = 纯确定性技术分析，无 LLM。
- **`analyzer.py`** = 用 LLM 把技术面 + 基本面 + 新闻综合成结构化决策。
- **`pipeline.py`** = 协调者（多股并发、进度回调、落库、触发通知）。

### 4.2 数据层 fallback 降级链

[data_provider/base.py](../../data_provider/base.py) 的 `DataFetcherManager` 按 **优先级** 依次尝试数据源、失败即降级，并按 **识别出的市场** 路由：

- 默认优先级：tushare（配置 token 时优先）→ **efinance(0)** → akshare(1) → pytdx(2) → baostock(3) → yfinance(4) → longbridge(5)；配置了对应 Key 时追加 Finnhub / AlphaVantage。
- 美股走专门链路（Finnhub → AlphaVantage → yfinance → Longbridge）；港股/A 股走按市场支持矩阵过滤后的通用优先级循环。
- 每个 fetcher 实现 `_fetch_raw_data` + `_normalize_data`，统一标准化为 8 列 `[date, open, high, low, close, volume, amount, pct_chg]`。全链路有 tenacity 重试 + 各源限流 + TTL 缓存。**单一数据源失败不会拖垮整个分析。**

### 4.3 LLM 层（多渠道）

[src/llm/](../../src/llm/) + [src/agent/llm_adapter.py](../../src/agent/llm_adapter.py) 基于 **LiteLLM** 统一封装，厂商无关：

- 通过环境变量或多渠道（`LLM_CHANNELS=<name>` + `LLM_<NAME>_PROTOCOL/BASE_URL/API_KEY/MODELS`）配置，支持任意 **OpenAI 兼容 / Anthropic 兼容** 端点。
- 支持模型 fallback 链、按模型的温度归一化（如 o 系列省略 temperature、kimi 固定温度）、参数报错时的单次请求级自愈重试、思考模型（DeepSeek-R1 等）的 `reasoning_content` 处理。
- 配置模板与说明见 [LLM 配置指南](../LLM_CONFIG_GUIDE.md) 与 [LLM 服务商配置指南](../llm-providers.md)。

### 4.4 Web 服务请求生命周期

`server.py` → [api/app.py](../../api/app.py) 的 `create_app()` 挂载 `/static` 下的 React SPA 与 `/api/v1/*` 路由。触发分析：

- **异步（默认）**：`POST /api/v1/analysis/analyze` → [src/services/task_queue.py](../../src/services/task_queue.py) 提交到线程池（带去重），返回 `202 + task_id`；客户端轮询 `GET /status/{task_id}` 或订阅 SSE 流 `/tasks/stream`。
- 结果经 **services → repositories → [src/storage.py](../../src/storage.py)** 落到 SQLite（服务负责编排，仓储只做纯 CRUD，不反向调用）。
- **鉴权**（[src/auth.py](../../src/auth.py)）：可选开关、Cookie 会话（`dsa_session`，HMAC 签名）、PBKDF2 口令哈希、登录限流；由中间件在请求时强制，配置变更即时生效。

### 4.5 前端

- **Web**（[apps/dsa-web/](../../apps/dsa-web/)）：React 19 + React Router 7 + Zustand + Tailwind + Vite，构建产物输出到仓库 `/static/`。Axios 客户端带 401→`/login` 拦截器；页面覆盖分析仪表盘、聊天、组合、选股、回测、告警、设置。
- **Desktop**（[apps/dsa-desktop/](../../apps/dsa-desktop/)）：Electron 的 `main.js` 找空闲端口拉起 Python 后端（`--serve-only`），轮询 `/api/health` 就绪后 `loadURL` 到 `localhost:port`，**复用后端托管的 Web 构建产物**，并通过 GitHub Releases 实现自动更新。

## 5. 入口 / 如何运行

```bash
# 分析（CLI）
python main.py                          # 完整运行一次（分析 + 大盘复盘 + 通知）
python main.py --stocks 600519,hk00700,AAPL
python main.py --market-review          # 仅大盘复盘（跳过个股）
python main.py --dry-run                # 仅抓数据，不调用 LLM
python main.py --schedule               # 每日定时，运行时热重载 .env
python main.py --serve                  # FastAPI + 后台分析
uvicorn server:app --reload --port 8000 # 仅 API

# 前端
cd apps/dsa-web && npm ci && npm run build      # → /static
cd apps/dsa-desktop && npm install && npm run build

# 验证（详见 AGENTS.md）
./scripts/ci_gate.sh                    # syntax → flake8 → deterministic → offline-tests
python -m pytest -m "not network"
```

部署：Docker（[docker/docker-compose.yml](../../docker/docker-compose.yml) 同时提供 `analyzer` 调度服务与 `server` FastAPI 服务），以及 GitHub Actions 的每日 cron（`.github/workflows/00-daily-analysis.yml`，工作日运行并推送报告）。版本发布以 commit 标题包含 `#patch`/`#minor`/`#major` 为触发条件（自动 tag → Docker/桌面端发布工作流）。

## 6. 一句话心智模型

> **`data_provider`（弹性多源数据）→ `stock_analyzer`（确定性信号）+ `search_service`（新闻）→ `analyzer`/`llm`/`agent`（LLM 判断）→ `schemas`/`reports`（结构化报告）→ `notification_sender`（多渠道推送）**，再由 `main.py`（CLI）、`api/`（Web + SPA + 桌面端）、`bot/`（聊天）三种形态对外暴露 —— 全部从 `.env` 读取配置，经 `services`/`repositories` 持久化到 SQLite。
