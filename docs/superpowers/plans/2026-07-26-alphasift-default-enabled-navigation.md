# AlphaSift 选股默认开启与固定导航入口 Implementation Plan

> 对应设计：`docs/superpowers/specs/2026-07-26-alphasift-default-enabled-navigation-design.md`

**Goal:** 让“选股”始终作为稳定导航入口显示，并让未声明 `ALPHASIFT_ENABLED` 的新安装默认启用 AlphaSift，同时继续尊重已有部署显式保存的 `false`。

**Architecture:** 将“导航可见性”“服务启用状态”“适配层可用状态”解耦。后端配置缺省值统一改为 `true`；Web 侧边栏不再请求 AlphaSift 状态决定是否渲染入口；选股页继续承担未开启、依赖异常和正常运行三类状态。升级时不迁移 `.env`，目标部署通过显式环境配置开启。

**Tech Stack:** Python 3 / FastAPI 配置体系、React / TypeScript / Vitest、pytest、Docker。

**Status:** 实现完成，待部署授权与目标环境验收。

**Production-readiness handoff:** 后续真实数据源/LLM smoke、质量与资源准入不在本 Plan 内继续扩张，见 `docs/superpowers/plans/2026-07-26-alphasift-production-readiness.md`。

## Global Constraints

- 不自动改写已有 `.env`，显式 `ALPHASIFT_ENABLED=false` 继续生效。
- 不在启动、菜单渲染或选股页加载时自动创建选股任务。
- 不修改 AlphaSift 筛选、策略、LLM 重排和 API schema。
- 不修改 LLM provider、模型、密钥、base URL 或 fallback 语义。
- Web 仍只开放 A 股 `cn`。
- 不执行 `git commit`、`git tag`、`git push` 或真实部署，除非用户另行明确确认。
- `docs/CHANGELOG.md` 的 `[Unreleased]` 只追加扁平条目。
- UI 改动的 PR 描述需附前后截图；截图不提交为仓库文件。

## File Structure

| 文件 | 变更 | 职责 |
| --- | --- | --- |
| `src/config.py` | Modify | 运行时字段与环境缺失时的默认值改为 `true` |
| `src/core/config_registry.py` | Modify | 设置页配置元数据默认值和说明同步 |
| `.env.example` | Modify | 新安装示例默认开启 |
| `apps/dsa-web/src/components/layout/SidebarNav.tsx` | Modify | 固定渲染“选股”，移除状态驱动显隐 |
| `apps/dsa-web/src/components/layout/__tests__/SidebarNav.test.tsx` | Modify | 固定入口、顺序和无状态请求回归 |
| `tests/test_config_env_compat.py` | Modify | 缺失/显式 false/显式 true 配置测试 |
| `tests/test_system_config_service.py` | Modify（按需） | 注册表默认值与配置更新兼容测试 |
| `docs/alphasift-integration.md` | Modify | 默认、导航、部署和回滚语义 |
| `docs/full-guide.md` | Modify | 中文 API/功能说明同步 |
| `docs/full-guide_EN.md` | Modify | 英文说明同步 |
| `docs/CHANGELOG.md` | Modify | `[Unreleased]` 新增一条改进记录 |

---

## Task 1：锁定后端配置契约

**Files:**

- Test: `tests/test_config_env_compat.py`
- Modify: `src/config.py`
- Modify: `src/core/config_registry.py`

- [ ] 新增或调整测试：删除 `ALPHASIFT_ENABLED` 后构造配置，断言 `alphasift_enabled is True`。
- [ ] 新增或调整测试：显式 `ALPHASIFT_ENABLED=false` 时断言仍为 `False`。
- [ ] 新增或调整测试：显式 `ALPHASIFT_ENABLED=true` 时断言为 `True`。
- [ ] 检查测试环境是否被仓库根 `.env` 污染；必要时用 patch 明确隔离环境变量，不修改生产加载顺序。
- [ ] 把 `Config.alphasift_enabled` 字段默认值改为 `True`。
- [ ] 把配置加载入口 `parse_env_bool(..., default=...)` 改为 `default=True`。
- [ ] 把配置注册表 `default_value` 改为 `"true"`，更新描述为“默认开启、显式 false 可关闭、关闭不隐藏导航”。
- [ ] 运行针对性配置测试，确认显式关闭兼容路径未破坏。

**Verification:**

```bash
python3 -m pytest tests/test_config_env_compat.py tests/test_system_config_service.py -q
python3 -m py_compile src/config.py src/core/config_registry.py
```

## Task 2：将选股导航改为固定入口

**Files:**

- Modify: `apps/dsa-web/src/components/layout/SidebarNav.tsx`
- Modify: `apps/dsa-web/src/components/layout/__tests__/SidebarNav.test.tsx`

- [ ] 先调整测试：无论 AlphaSift 状态是开启、关闭或请求失败，导航都显示 `/screening`。
- [ ] 断言入口顺序保持在 `/chat` 与 `/portfolio` 之间。
- [ ] 从 `SidebarNav` 移除 `showAlphaSiftNav` 状态、状态查询、AlphaSift 配置事件监听和过滤表达式。
- [ ] 清理因此不再使用的 React hooks、API 和事件常量 import。
- [ ] 不删除共享 AlphaSift 配置事件定义，因为设置页和其它消费者仍可能使用。
- [ ] 回归折叠/rail 侧边栏，确认固定入口不破坏布局。

**Verification:**

```bash
cd apps/dsa-web
npm run test -- SidebarNav.test.tsx --run
npm run lint
```

## Task 3：回归选股页状态边界

**Files:**

- Test/Modify as needed: `apps/dsa-web/src/pages/__tests__/StockScreeningPage.test.tsx`
- Modify only if a real defect is exposed: `apps/dsa-web/src/pages/StockScreeningPage.tsx`

- [ ] 确认 `enabled=false` 时页面可访问、显示开启入口、不能提交选股。
- [ ] 确认 `enabled=true, available=false` 时显示依赖故障、不能提交选股。
- [ ] 确认 `enabled=true, available=true` 时加载策略并允许提交后台任务。
- [ ] 确认页面首次加载不会调用 `/screen` 或创建任务。
- [ ] 若现有测试已经完整覆盖，则不重复增加测试和实现。

**Verification:**

```bash
cd apps/dsa-web
npm run test -- StockScreeningPage.test.tsx alphasift.test.ts --run
```

## Task 4：同步配置示例与文档

**Files:**

- Modify: `.env.example`
- Modify: `docs/alphasift-integration.md`
- Modify: `docs/full-guide.md`
- Modify: `docs/full-guide_EN.md`
- Modify: `docs/CHANGELOG.md`

- [ ] `.env.example` 将示例值改为 `true`，说明 `false` 仍可关闭服务但不隐藏入口。
- [ ] 集成文档更新当前方案、Web、桌面端、Docker 与回滚章节。
- [ ] 中文完整指南将“需先开启”的表述改为“默认开启；显式关闭时不可用”。
- [ ] 英文完整指南同步同一配置语义。
- [ ] `[Unreleased]` 追加一行：`- [改进] AlphaSift 选股默认开启并固定显示导航入口，关闭或依赖异常时可进入页面查看状态与修复指引`。
- [ ] 评估 README/繁体首页：若没有配置默认值或导航显隐的细节，不修改，并在交付说明记录。

**Verification:**

```bash
rg -n "默认关闭|默认仍关闭|Disabled by default|must be enabled first|ALPHASIFT_ENABLED=false" \
  .env.example docs/alphasift-integration.md docs/full-guide.md docs/full-guide_EN.md
```

## Task 5：完整验证与部署就绪检查

- [ ] 执行后端针对性测试。
- [ ] 执行 Web 针对性测试、lint 和 build。
- [ ] 执行 `./scripts/ci_gate.sh`。
- [ ] 执行 `git diff --check` 并检查只包含任务相关变更。
- [ ] 确认没有修改用户已有的无关工作区文件。
- [ ] 记录真实 AlphaSift 在线筛选是否未验证，以及原因。
- [ ] 准备部署清单：目标环境显式设置 `ALPHASIFT_ENABLED=true`、重建镜像/桌面后端、检查 `/status`、策略列表和 3 条候选小规模任务。
- [ ] 未经用户明确授权，不修改目标部署状态。

**Verification:**

```bash
python3 -m pytest \
  tests/test_alphasift_api.py \
  tests/test_config_env_compat.py \
  tests/test_system_config_service.py \
  tests/test_docker_entrypoint.py \
  tests/test_packaging_build_scripts.py -q
./scripts/ci_gate.sh

cd apps/dsa-web
npm run test -- SidebarNav.test.tsx StockScreeningPage.test.tsx SettingsPage.test.tsx alphasift.test.ts --run
npm run lint
npm run build
```

## Deployment Checklist（实现完成后，需另行授权）

- [ ] 将目标部署配置从 `ALPHASIFT_ENABLED=false` 改为 `true`。
- [ ] 重建后端镜像/桌面产物，确认 `import alphasift.dsa_adapter`。
- [ ] 部署保存后的完整前端构建产物。
- [ ] 验证左侧固定显示“选股”。
- [ ] 验证 `/api/v1/alphasift/status` 为 `enabled=true, available=true`。
- [ ] 验证策略列表加载。
- [ ] 运行 A 股、最多 3 条结果的小规模选股。
- [ ] 验证首页、问股、报告与设置 smoke。
- [ ] 如需回滚，将目标环境恢复 `ALPHASIFT_ENABLED=false`；入口仍显示并提示服务关闭。

## Implementation Verification Record

- 2026-07-26：后端针对性测试 271 项通过。
- 2026-07-26：`test_system_config_api.py + test_system_config_service.py` 169 项通过。
- 2026-07-26：Web 全量测试 667 项通过、2 项跳过；lint 与 production build 通过。
- 2026-07-26：Python `py_compile` 与 `git diff --check` 通过。
- 2026-07-26：完整 `ci_gate.sh` 的 syntax、flake8、deterministic checks 均通过；离线套件 3053 项中 3043 项通过，10 项 `test_system_config_service.py` 在全仓顺序下受此前测试残留的 LLM 环境影响失败。同一文件独立运行以及与其 API 测试连续运行均全通过。本改动不扩张到修复该既有全仓测试隔离问题。
- 真实 AlphaSift 数据源与 LLM 选股未执行，留待部署后的受控 3 条候选 smoke。
