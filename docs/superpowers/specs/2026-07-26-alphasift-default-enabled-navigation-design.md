# AlphaSift 选股默认开启与固定导航入口 — 设计 Spec

- 日期：2026-07-26
- 状态：已实现（待部署）
- 关联模块：配置（`src/config.py`、`src/core/config_registry.py`）、Web 导航与选股页（`apps/dsa-web/`）、部署与文档
- 前置文档：`docs/alphasift-integration.md`
- 实现计划：`docs/superpowers/plans/2026-07-26-alphasift-default-enabled-navigation.md`
- 生产就绪 Follow-up：`docs/superpowers/specs/2026-07-26-alphasift-production-readiness-design.md`

---

## 1. 背景与问题

DSA 已集成 AlphaSift 选股能力，并提供 `/api/v1/alphasift/*` API、Web 选股页、设置页开关以及 Docker/桌面端依赖打包。但当前产品行为有两个可发现性问题：

1. `ALPHASIFT_ENABLED` 缺省为 `false`，新安装默认关闭选股。
2. Web 侧边栏根据 `/api/v1/alphasift/status` 返回的 `enabled` 动态隐藏“选股”菜单。用户在不知道功能存在的情况下，无法从导航进入选股页，也难以发现开启入口或故障诊断。

当前实现把“功能是否可发现”和“后端是否允许执行选股”绑定为同一个状态。结果是关闭服务时入口也消失，用户看到的是“项目没有选股功能”，而不是“选股功能当前未开启”。

另外，仅修改代码中的缺省值不能改变已有部署。已有 `.env`、Docker `env_file`、进程环境变量或设置页持久化的 `ALPHASIFT_ENABLED=false` 都会继续覆盖代码缺省值。因此需要明确区分：

- **新安装缺省行为**：环境变量未设置时默认开启。
- **已有安装兼容行为**：继续尊重用户显式配置，不在启动或升级时改写 `.env`。
- **本次目标部署**：由部署操作显式把该实例的 `ALPHASIFT_ENABLED` 调整为 `true`。

## 2. 目标 / 非目标

### 目标

- “选股”作为稳定产品入口，始终显示在 Web/桌面端侧边栏中。
- 新安装或未声明 `ALPHASIFT_ENABLED` 的环境默认启用 AlphaSift。
- 显式设置 `ALPHASIFT_ENABLED=false` 时仍禁止策略读取和选股执行，保持管理员控制权。
- 关闭、依赖缺失或适配层异常时，用户仍可进入选股页查看明确状态、诊断和修复指引。
- 默认启用不触发启动时全市场扫描，不增加闲置状态下的数据源请求或 LLM 调用。
- 本次目标部署显式开启选股，并完成依赖、状态、策略列表和小规模选股验收。

### 非目标

- 不把投资画像接入 AlphaSift 策略选择或候选重排。
- 不新增选股策略，不修改 AlphaSift 的筛选、因子评分或 LLM 重排逻辑。
- 不扩大市场范围；Web 本期仍只开放 A 股 `cn`。
- 不在页面加载、服务启动或定时任务中自动运行选股。
- 不在普通业务请求中自动执行 `pip install`。
- 不删除 `ALPHASIFT_ENABLED` 开关，也不强制覆盖用户显式关闭选择。
- 不迁移历史 `.env`，不修改现有 LLM/provider/base URL/fallback 配置语义。

## 3. 已确认的关键决策

| 决策点 | 选择 | 理由 |
| --- | --- | --- |
| 导航入口 | **始终显示“选股”** | 功能可发现性不应依赖服务开关；关闭或故障应展示状态，而不是隐藏产品能力 |
| 新安装缺省值 | **`ALPHASIFT_ENABLED=true`** | AlphaSift 已是锁定版本的后端依赖，Docker和桌面构建也已校验适配层，可以作为默认能力提供 |
| 显式 `false` | **继续尊重** | 保留管理员关闭第三方选股能力、控制资源与合规边界的能力 |
| 旧安装迁移 | **不自动改写** | 避免升级过程静默改变用户明确保存的运行策略 |
| 本次部署 | **显式把目标环境改为 `true`** | 代码缺省值无法覆盖目标实例已有的 `false` |
| 运行成本 | **仍由用户点击触发** | 默认启用只允许调用，不代表自动扫描；避免启动或空闲状态产生网络、LLM 和算力成本 |
| 依赖缺失 | **页面可见并显式报错** | 保留现有 `available=false + diagnostics` 和 `424` 错误边界，便于修复镜像或桌面后端 |

## 4. 目标行为与状态模型

导航可见性、服务开关和适配层可用性分成三个独立概念：

| `enabled` | `available` | 导航 | 选股页行为 | 是否允许运行 |
| --- | --- | --- | --- | --- |
| `true` | `true` | 显示 | 正常加载策略和运行选股 | 是 |
| `true` | `false` | 显示 | 展示适配层不可用与诊断/修复指引 | 否 |
| `false` | `true` 或 `false` | 显示 | 展示服务已关闭和开启入口 | 否 |
| 状态接口失败 | 未知 | 显示 | 页面自行请求状态并展示连接错误 | 否 |

核心规则：

1. `SidebarNav` 不再通过 `/api/v1/alphasift/status` 决定是否渲染 `screening` 导航项。
2. `/screening` 路由保持可访问，由 `StockScreeningPage` 负责展示当前状态。
3. 后端授权边界不变：`enabled=false` 时，`strategies`、`screen` 和修复安装相关入口继续执行现有检查。
4. `status` 仍返回真实的 `enabled`、`available` 和诊断信息，不把“默认显示导航”伪装成后端可用。
5. 只有用户点击“运行选股”并成功提交任务后才读取全市场快照、调用外部数据源和 LLM。

## 5. 配置与兼容语义

### 5.1 缺省值

以下位置需要统一为 `true`：

- `Config.alphasift_enabled` 字段缺省值。
- `Config.from_env()`（或当前等价配置加载入口）对缺失环境变量的解析缺省值。
- `src/core/config_registry.py` 中 `ALPHASIFT_ENABLED.default_value`。
- `.env.example` 示例值及相邻说明。

不能只修改其中一个位置，否则会造成后端运行值、设置页显示值和新用户复制配置样例之间的漂移。

### 5.2 显式配置优先级

配置解析遵循现有规则：

```text
显式进程环境 / .env 中的 ALPHASIFT_ENABLED
    > 代码缺省值 true
```

- 显式 `false` 必须解析为关闭。
- 缺失、未配置时解析为开启。
- 不增加启动迁移脚本。
- 不因为缺少适配层而把 `.env` 自动回写为 `false`；可用性与用户开关分别报告。

### 5.3 已有部署

升级后存在以下两类行为：

- 已有实例没有该配置项：采用新缺省值 `true`。
- 已有实例明确保存 `ALPHASIFT_ENABLED=false`：继续关闭，但导航仍显示。

本次目标实例已有显式 `false`，部署时必须由运维步骤把它改为 `true`。该操作属于部署配置变更，不应通过应用启动时的隐式迁移完成。

## 6. 详细改动设计

### 6.1 后端配置

涉及：

- `src/config.py`
- `src/core/config_registry.py`
- `.env.example`

改动：

- 将 AlphaSift 缺省启用值从 `false` 改为 `true`。
- 更新配置项英文描述，明确“默认开启；显式设为 false 可关闭；关闭不隐藏导航”。
- 保持 `is_required=false` 和 `is_editable=true`。
- 保持 `ALPHASIFT_INSTALL_SPEC`、受信任来源校验、管理员权限和运行时安装边界不变。

### 6.2 Web 导航

涉及：

- `apps/dsa-web/src/components/layout/SidebarNav.tsx`
- 对应组件测试

改动：

- `NAV_ITEMS` 中的 `screening` 项始终参与渲染。
- 删除仅用于隐藏选股导航的状态请求、事件监听和 `showAlphaSiftNav` 状态。
- 若 AlphaSift 配置变更事件仍被其它行为使用，则只移除本组件不再需要的监听，不改变共享事件定义。
- 保持导航顺序：`首页 → 问股 → 选股 → 持仓 → 投资画像 → 回测 → 告警 → 设置`。
- Web 与 Electron 桌面端复用同一前端构建，因此无需桌面端另建导航实现。

### 6.3 选股页

现有 `StockScreeningPage` 已具备以下状态，原则上复用而非重写：

- 未开启时展示开启按钮。
- 已开启但适配层不可用时展示依赖/重建提示。
- 正常时加载策略并允许提交后台任务。
- 展示实验功能和投资风险提示。

实现阶段需要回归确认：

- 直接访问 `/screening` 且 `enabled=false` 时页面不崩溃。
- `status` 请求失败时不误显示为可运行。
- 新缺省值下正常环境不会先展示“未开启”闪烁并触发错误操作。
- 页面加载本身不会调用 `/screen` 或创建后台任务。

如现有行为已满足，不为本次需求新增平行状态机。

### 6.4 API

API 路径和响应结构不变：

- `GET /api/v1/alphasift/status`
- `GET /api/v1/alphasift/strategies`
- `POST /api/v1/alphasift/screen/tasks`
- `GET /api/v1/alphasift/screen/tasks/{task_id}`
- `POST /api/v1/alphasift/install`

本次不修改 API schema。显式关闭时的现有 `403 alphasift_disabled`、适配层不可用时的 `424` 以及诊断字段保持兼容。

### 6.5 文档

同步更新：

- `docs/alphasift-integration.md`
- `docs/full-guide.md`
- `docs/full-guide_EN.md`
- `.env.example`
- `docs/CHANGELOG.md` 的 `[Unreleased]` 扁平条目

至少消除以下过时表述：

- “AlphaSift 默认关闭”。
- “关闭时隐藏左侧选股入口”。
- “用户必须先开启才能发现选股页面”。
- Docker/桌面发布包“默认仍关闭”的说明。

README 只保留首页级能力概览，本次不因配置默认值变化扩写 README。繁体首页若没有描述默认开关语义，无需修改；交付时说明评估结果。

## 7. 部署设计

### 7.1 部署前

1. 确认目标环境使用 Docker、桌面打包或源码 Python 服务中的哪一种。
2. 检查目标环境是否显式设置 `ALPHASIFT_ENABLED`。
3. 本次目标实例将该值设置为：

```env
ALPHASIFT_ENABLED=true
```

4. 不修改任何 LLM 密钥、provider、base URL 或 fallback 配置。
5. 重建后端产物，不能只替换前端静态文件，因为依赖可用性需要由镜像/打包产物保证。

### 7.2 Docker

Dockerfile 已通过 `requirements.txt` 安装锁定 commit 的 AlphaSift，并执行：

```text
import alphasift.dsa_adapter
```

部署时应重建镜像，并让 `docker/docker-compose.yml` 从目标 `.env` 读取新的显式 `true`。不得仅依赖代码缺省值去覆盖已有 env 文件。

### 7.3 桌面端

Windows/macOS 后端构建脚本已有 AlphaSift 收集和导入校验。发布桌面包时需要重新构建 Web 和桌面后端，确认固定导航入口与打包后的适配层同时存在。

### 7.4 部署后验收

按顺序验证：

1. 左侧稳定显示“选股”，刷新页面后仍存在。
2. `GET /api/v1/alphasift/status` 返回 `enabled=true`、`available=true`。
3. 选股页成功加载策略列表。
4. 使用 A 股市场、返回数量 3，完成一次小规模选股任务。
5. 任务状态从 `pending/processing` 进入 `completed`，并返回候选或明确的空结果/降级原因。
6. 首页个股分析、问股、历史报告和设置页基本 smoke 正常。
7. 页面首次加载和服务启动期间没有自动创建选股任务。

## 8. 测试策略

### 8.1 后端

- 配置缺失时 `alphasift_enabled is True`。
- 显式 `ALPHASIFT_ENABLED=false` 时仍解析为 `False`。
- 显式 `true` 时解析为 `True`。
- 配置注册表的默认值与运行时默认值一致。
- `enabled=false` 时，受保护的 AlphaSift API 仍拒绝调用。
- `status` 在缺少适配层时仍返回 `available=false + diagnostics`，不因默认开启而自动安装。
- Docker/桌面构建脚本继续校验并收集 `alphasift.dsa_adapter`。

建议命令：

```bash
python -m pytest \
  tests/test_alphasift_api.py \
  tests/test_config_env_compat.py \
  tests/test_system_config_service.py \
  tests/test_docker_entrypoint.py \
  tests/test_packaging_build_scripts.py
./scripts/ci_gate.sh
```

### 8.2 Web

- 无论状态接口返回 `enabled=true`、`enabled=false`、请求失败，侧边栏都显示“选股”。
- 导航顺序保持不变。
- `enabled=false` 时选股页显示开启入口且运行按钮不可用。
- `enabled=true, available=false` 时显示适配层错误且不能提交任务。
- `enabled=true, available=true` 时加载策略并可提交任务。
- 渲染侧边栏不会额外依赖 AlphaSift 状态请求。

建议命令：

```bash
cd apps/dsa-web
npm run test -- SidebarNav.test.tsx StockScreeningPage.test.tsx SettingsPage.test.tsx alphasift.test.ts --run
npm run lint
npm run build
```

### 8.3 可视证据

这是用户可见的 Web UI 变更，PR 描述必须附截图：

- 修改前：侧边栏无“选股”。
- 修改后：侧边栏在“问股”和“持仓”之间显示“选股”。
- 至少一张选股页正常状态截图；若测试故障态，附“已关闭”或“适配层不可用”页面截图。

截图作为 PR 描述、评论或 Actions artifact，不作为一次性验收文件提交到仓库。

## 9. 风险与控制

### 风险 1：已有部署不会自动开启

原因：显式 `.env=false` 优先于代码缺省值。

控制：部署清单必须检查并显式更新目标环境；部署后以 `/status` 的 `enabled` 实际值验收。

### 风险 2：默认开启增加误调用概率

默认开启后用户可以直接运行全市场筛选，可能产生外部数据源、LLM、时间和算力成本。

控制：不自动运行；保留明确的“运行选股”按钮、任务状态和实验风险提示；默认返回数量仍为 3。

### 风险 3：依赖或外部数据源不可用

导航始终可见后，更多用户会进入不可用页面。

控制：保留 `available` 与 diagnostics；页面明确展示重建依赖、数据源降级和 LLM 未重排提示，不把故障结果包装为正常推荐。

### 风险 4：第三方能力默认开启的治理变化

虽然依赖已锁定并随构建安装，但默认开启改变了功能暴露策略。

控制：保留显式关闭开关；不开启自动任务；不进行运行时静默安装；文档说明第三方来源、实验性质和投资风险。

### 风险 5：前后端默认值漂移

如果只修改 `.env.example` 或 `Config`，设置页可能仍显示不同默认值。

控制：以测试同时断言运行时配置、配置注册表和示例文档，代码评审检查所有默认值入口。

## 10. 回滚

### 配置回滚

将目标环境恢复为：

```env
ALPHASIFT_ENABLED=false
```

重启服务后，策略读取与选股执行恢复为关闭状态。按照本 Spec 的产品约定，“选股”导航仍显示，并在页面解释服务已关闭。

### 代码回滚

如需完全恢复旧产品行为，可回滚本次 PR，使：

- 缺省值恢复为 `false`。
- 侧边栏重新根据 `enabled` 隐藏“选股”。

不需要数据库迁移或数据清理；本改动不新增表、不改变任务结果结构。

### 部署回滚

回退到上一镜像/桌面构建，并恢复原部署环境配置。由于本改动不修改持久化数据 schema，版本回退不需要数据转换。

## 11. 实现完成后的交付说明要求

按 `AGENTS.md` 说明：

- 改了什么。
- 为什么把导航可见性与服务开关解耦。
- 后端、Web、Docker/桌面构建验证情况。
- 未执行的真实外部数据源或 LLM 验证。
- 已有显式 `false` 实例的兼容影响。
- 风险点和回滚方式。
- 本次目标环境是否已经显式改为 `true`，以及部署后 `/status` 验收结果。

## 12. 后续生产准入

本 Spec 只负责“缺省开启 + 固定入口”的产品行为，不代表真实数据源、LLM、资源与候选质量已经通过生产验收。部署前的 P0-P2 准入、画像联动和 HK/US 扩展已拆分到：

- `docs/superpowers/specs/2026-07-26-alphasift-production-readiness-design.md`
- `docs/superpowers/plans/2026-07-26-alphasift-production-readiness.md`
