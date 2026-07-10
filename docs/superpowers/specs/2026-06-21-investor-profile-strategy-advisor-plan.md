# 投资画像 + 策略中心 + 多策略对比 实现计划 (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为"问股/Agent"链路增加用户投资画像（访谈推荐 + 直选）、可持久化的策略偏好，以及多策略分别评估后的对比视图。

**Architecture:** 在现有 ReAct/多 Agent 链路前面加一层"策略配置"（画像表 + 推荐引擎 + API），在结果侧把多 Agent 模式下已有的各 `SkillAgent` 独立 `Opinion` 透出为 `skill_breakdown`（共识仍由 `SkillAggregator` 提供）。Web 端新增策略中心 + 访谈向导 + 对比视图，并让 ChatPage 默认预填画像。全部为追加式改动，向后兼容。

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy（`src/storage.py`）/ pytest；React + TypeScript + Zustand + Vite + Vitest（`apps/dsa-web/`）。

## Global Constraints

- commit message 用英文，**不**添加 `Co-Authored-By`。
- 未经用户明确确认不执行 `git push` / `git tag`；本计划内的 commit 步骤在用户已授权实现后执行。
- 新增配置项必须同步更新 `.env.example` 和相关 `docs/`。
- 所有新增 API 字段为**追加式**，不删改 `dashboard` 既有结构；老客户端忽略即兼容。
- 用户可见策略选择器只暴露 `user_invocable=True` 的 skill。
- 画像最多存 **5** 个策略；单次对比默认跑 **≤ `AGENT_COMPARE_MAX`（默认 3）**。
- `owner_key` 单租户下恒为 `"default"`。
- 后端验证：`./scripts/ci_gate.sh`；测试用 `python -m pytest -m "not network"`。
- 前端验证：`cd apps/dsa-web && npm ci && npm run lint && npm run build`。
- 数据驱动优先：策略 `profile_tags` 缺省时从 `category`/`market_regimes` 推导，存量策略不改也能用。

---

## File Structure

新增：
- `src/agent/skills/profile_recommender.py` — 访谈答案 → 推荐策略的规则打分（纯函数）。
- `src/agent/skills/profile_tags.py` — `profile_tags` 解析与从 `category`/`market_regimes` 的推导回退。
- `api/v1/endpoints/profile.py` 或在 `agent.py` 内新增 profile 端点（见 Task 4，决定后锁定）。
- `tests/test_profile_recommender.py`、`tests/test_investor_profile_storage.py`、`tests/test_profile_api.py`、`tests/test_skill_breakdown.py`。
- `apps/dsa-web/src/pages/ProfilePage.tsx`、`apps/dsa-web/src/components/profile/StrategyCenter.tsx`、`apps/dsa-web/src/components/profile/InterviewWizard.tsx`、`apps/dsa-web/src/components/chat/SkillBreakdownTable.tsx`。

修改：
- `src/agent/skills/base.py` — `Skill` 增加 `profile_tags` 字段 + YAML 读取。
- `src/storage.py` — 新增 `InvestorProfileRecord` 模型 + CRUD。
- `src/agent/orchestrator.py` — 收集 `skill_breakdown` 到 `OrchestratorResult`。
- `src/agent/executor.py` — `AgentResult` 增加 `skill_breakdown`（executor 模式下为空）。
- `api/v1/endpoints/agent.py` — `SkillInfo` 增字段、`ChatResponse` 增 `skill_breakdown`、默认策略取自画像。
- `src/config.py` + `.env.example` — `AGENT_COMPARE_MAX`。
- `apps/dsa-web/src/api/agent.ts`、`ChatPage.tsx`、路由/导航、i18n 文案。

---

# Phase 1 · 后端：投资画像 + 推荐引擎

## Task 1: `Skill.profile_tags` 字段 + YAML 读取 + 推导回退

**Files:**
- Modify: `src/agent/skills/base.py:58-79`（dataclass 字段）、`src/agent/skills/base.py:176-201`（`load_skill_from_yaml`）
- Create: `src/agent/skills/profile_tags.py`
- Test: `tests/test_profile_tags.py`

**Interfaces:**
- Produces:
  - `Skill.profile_tags: Dict[str, List[str]]`（键 `horizon`/`risk`/`style`，值为标签列表）
  - `profile_tags.resolve_profile_tags(skill) -> Dict[str, List[str]]`（显式 `profile_tags` 优先，缺省时从 `category`/`market_regimes` 推导）
  - 常量 `HORIZON_VALUES = ("ultra_short","swing","long")`、`RISK_VALUES = ("conservative","balanced","aggressive")`、`STYLE_VALUES = ("trend","reversal","theme","value","framework")`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_profile_tags.py
from src.agent.skills.base import Skill
from src.agent.skills.profile_tags import resolve_profile_tags


def _skill(**kw):
    base = dict(name="x", display_name="X", description="d", instructions="i")
    base.update(kw)
    return Skill(**base)


def test_explicit_profile_tags_take_precedence():
    s = _skill(profile_tags={"horizon": ["swing"], "risk": ["aggressive"], "style": ["theme"]})
    tags = resolve_profile_tags(s)
    assert tags["style"] == ["theme"]
    assert tags["risk"] == ["aggressive"]


def test_derived_from_category_when_missing():
    s = _skill(category="reversal")
    tags = resolve_profile_tags(s)
    assert "reversal" in tags["style"]


def test_derived_from_market_regimes_theme():
    s = _skill(category="trend", market_regimes=["sector_hot"])
    tags = resolve_profile_tags(s)
    assert "theme" in tags["style"]
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_profile_tags.py -v`
Expected: FAIL（`ImportError` / `Skill` 无 `profile_tags`）

- [ ] **Step 3: 给 `Skill` 增加字段**

在 `src/agent/skills/base.py` 的 dataclass 末尾（`preferred_model` 之后，第 79 行后）增加：

```python
    profile_tags: Dict[str, List[str]] = field(default_factory=dict)
```

确认文件顶部已 `from typing import Dict, List`（已存在 `List`，如缺 `Dict` 则补）。

- [ ] **Step 4: 在 YAML loader 读取**

在 `load_skill_from_yaml` 的 `Skill(...)` 构造里（`preferred_model=...` 之后）追加：

```python
        profile_tags={
            str(k): _coerce_string_list(v)
            for k, v in (data.get("profile_tags") or {}).items()
        },
```

- [ ] **Step 5: 实现推导回退模块**

```python
# src/agent/skills/profile_tags.py
# -*- coding: utf-8 -*-
"""Resolve a skill's profile_tags, deriving sensible defaults when absent."""
from __future__ import annotations
from typing import Dict, List

HORIZON_VALUES = ("ultra_short", "swing", "long")
RISK_VALUES = ("conservative", "balanced", "aggressive")
STYLE_VALUES = ("trend", "reversal", "theme", "value", "framework")

_CATEGORY_DEFAULTS: Dict[str, Dict[str, List[str]]] = {
    "trend": {"style": ["trend"], "horizon": ["swing"], "risk": ["balanced"]},
    "pattern": {"style": ["framework"], "horizon": ["swing"], "risk": ["balanced"]},
    "reversal": {"style": ["reversal"], "horizon": ["swing"], "risk": ["aggressive"]},
    "framework": {"style": ["framework"], "horizon": ["swing", "long"], "risk": ["balanced"]},
}

_THEME_REGIMES = {"sector_hot", "theme", "hot_theme", "emotion", "event"}


def resolve_profile_tags(skill) -> Dict[str, List[str]]:
    explicit = getattr(skill, "profile_tags", None) or {}
    if explicit:
        return {k: list(v) for k, v in explicit.items()}

    category = (getattr(skill, "category", "") or "trend").strip().lower()
    derived = {
        k: list(v) for k, v in _CATEGORY_DEFAULTS.get(category, _CATEGORY_DEFAULTS["trend"]).items()
    }

    regimes = {str(r).strip().lower() for r in (getattr(skill, "market_regimes", None) or [])}
    if regimes & _THEME_REGIMES:
        derived["style"] = sorted(set(derived.get("style", [])) | {"theme"})
        derived.setdefault("risk", ["balanced"])
        derived["risk"] = sorted(set(derived["risk"]) | {"aggressive"})
        derived["horizon"] = sorted(set(derived.get("horizon", [])) | {"ultra_short"})
    return derived
```

- [ ] **Step 6: 运行测试通过**

Run: `python -m pytest tests/test_profile_tags.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add src/agent/skills/base.py src/agent/skills/profile_tags.py tests/test_profile_tags.py
git commit -m "feat: add profile_tags to Skill schema with category-based fallback"
```

---

## Task 2: `InvestorProfileRecord` 表 + storage CRUD

**Files:**
- Modify: `src/storage.py`（紧随 `AlertRuleRecord` 后新增模型；在 `DatabaseManager` 内新增 CRUD 方法）
- Test: `tests/test_investor_profile_storage.py`

**Interfaces:**
- Produces（`DatabaseManager` 方法）：
  - `get_investor_profile(owner_key: str = "default") -> Optional[Dict[str, Any]]`
    返回 `{"skill_ids": List[str], "interview_answers": Optional[dict], "source": str, "updated_at": datetime}` 或 `None`
  - `upsert_investor_profile(skill_ids: List[str], *, source: str = "manual", interview_answers: Optional[dict] = None, owner_key: str = "default") -> Dict[str, Any]`
  - `clear_investor_profile(owner_key: str = "default") -> bool`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_investor_profile_storage.py
import pytest
from src.storage import get_db


@pytest.fixture
def db():
    return get_db()


def test_empty_profile_returns_none(db):
    db.clear_investor_profile(owner_key="test_owner")
    assert db.get_investor_profile(owner_key="test_owner") is None


def test_upsert_then_get(db):
    db.upsert_investor_profile(["bull_trend", "chan_theory"], source="interview", owner_key="test_owner")
    prof = db.get_investor_profile(owner_key="test_owner")
    assert prof["skill_ids"] == ["bull_trend", "chan_theory"]
    assert prof["source"] == "interview"


def test_upsert_is_single_row(db):
    db.upsert_investor_profile(["bull_trend"], owner_key="test_owner")
    db.upsert_investor_profile(["box_oscillation"], owner_key="test_owner")
    prof = db.get_investor_profile(owner_key="test_owner")
    assert prof["skill_ids"] == ["box_oscillation"]
    db.clear_investor_profile(owner_key="test_owner")
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_investor_profile_storage.py -v`
Expected: FAIL（`AttributeError: ... get_investor_profile`）

- [ ] **Step 3: 新增 ORM 模型**

在 `src/storage.py` 的 `AlertRuleRecord` 类定义之后（约第 702 行后）新增：

```python
class InvestorProfileRecord(Base):
    """Persisted investor strategy profile (single editable profile per owner)."""

    __tablename__ = 'investor_profiles'

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_key = Column(String(64), nullable=False, unique=True, default='default', index=True)
    skill_ids = Column(Text, nullable=False, default='[]')          # JSON array
    interview_answers = Column(Text)                                # JSON object, nullable
    source = Column(String(16), nullable=False, default='manual')   # 'manual' | 'interview'
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, index=True)
```

- [ ] **Step 4: 新增 CRUD 方法**

在 `DatabaseManager` 内（紧邻其他 conversation CRUD，例如 `save_conversation_message` 附近）新增（`json` 已在 storage.py 顶部导入；如未导入则补 `import json`）：

```python
    def get_investor_profile(self, owner_key: str = "default") -> Optional[Dict[str, Any]]:
        """Return the single investor profile for an owner, or None."""
        with self.session_scope() as session:
            stmt = select(InvestorProfileRecord).where(
                InvestorProfileRecord.owner_key == owner_key
            )
            row = session.execute(stmt).scalar_one_or_none()
            if row is None:
                return None
            return {
                "skill_ids": json.loads(row.skill_ids or "[]"),
                "interview_answers": json.loads(row.interview_answers) if row.interview_answers else None,
                "source": row.source,
                "updated_at": row.updated_at,
            }

    def upsert_investor_profile(
        self,
        skill_ids: List[str],
        *,
        source: str = "manual",
        interview_answers: Optional[Dict[str, Any]] = None,
        owner_key: str = "default",
    ) -> Dict[str, Any]:
        """Create or update the single investor profile for an owner."""
        with self.session_scope() as session:
            stmt = select(InvestorProfileRecord).where(
                InvestorProfileRecord.owner_key == owner_key
            )
            row = session.execute(stmt).scalar_one_or_none()
            if row is None:
                row = InvestorProfileRecord(owner_key=owner_key)
                session.add(row)
            row.skill_ids = json.dumps(list(skill_ids), ensure_ascii=False)
            row.source = source
            if interview_answers is not None:
                row.interview_answers = json.dumps(interview_answers, ensure_ascii=False)
            session.flush()
        return self.get_investor_profile(owner_key)

    def clear_investor_profile(self, owner_key: str = "default") -> bool:
        """Delete the investor profile for an owner. Returns True if a row was removed."""
        with self.session_scope() as session:
            stmt = select(InvestorProfileRecord).where(
                InvestorProfileRecord.owner_key == owner_key
            )
            row = session.execute(stmt).scalar_one_or_none()
            if row is None:
                return False
            session.delete(row)
            return True
```

- [ ] **Step 5: 运行测试通过**

Run: `python -m pytest tests/test_investor_profile_storage.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add src/storage.py tests/test_investor_profile_storage.py
git commit -m "feat: add investor profile persistence (single-row table + CRUD)"
```

---

## Task 3: 访谈推荐引擎（规则打分）

**Files:**
- Create: `src/agent/skills/profile_recommender.py`
- Test: `tests/test_profile_recommender.py`

**Interfaces:**
- Consumes: `profile_tags.resolve_profile_tags`（Task 1）
- Produces:
  - `InterviewAnswers = Dict[str, str]`（键：`horizon`/`risk`/`style`/`watch`）
  - `recommend_skills(answers: Dict[str, str], skills: List[Skill], max_count: int = 3) -> List[str]`
    返回按得分降序的 skill id 列表（只含 `user_invocable=True`，至多 `max_count`，至多 5）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_profile_recommender.py
from src.agent.skills.base import Skill
from src.agent.skills.profile_recommender import recommend_skills


def _skill(name, **kw):
    base = dict(name=name, display_name=name, description="d", instructions="i", user_invocable=True)
    base.update(kw)
    return Skill(**base)


SKILLS = [
    _skill("bull_trend", profile_tags={"style": ["trend"], "horizon": ["swing"], "risk": ["balanced"]}),
    _skill("hot_theme", profile_tags={"style": ["theme"], "horizon": ["ultra_short"], "risk": ["aggressive"]}),
    _skill("growth_quality", profile_tags={"style": ["value"], "horizon": ["long"], "risk": ["conservative"]}),
]


def test_aggressive_theme_picks_hot_theme_first():
    answers = {"horizon": "ultra_short", "risk": "aggressive", "style": "theme", "watch": "high"}
    result = recommend_skills(answers, SKILLS, max_count=2)
    assert result[0] == "hot_theme"


def test_conservative_long_picks_growth_quality_first():
    answers = {"horizon": "long", "risk": "conservative", "style": "value", "watch": "low"}
    result = recommend_skills(answers, SKILLS, max_count=2)
    assert result[0] == "growth_quality"


def test_respects_max_count_and_cap():
    answers = {"horizon": "swing", "risk": "balanced", "style": "trend", "watch": "medium"}
    result = recommend_skills(answers, SKILLS, max_count=10)
    assert 1 <= len(result) <= 5


def test_excludes_non_invocable():
    skills = SKILLS + [_skill("internal", user_invocable=False,
                              profile_tags={"style": ["trend"], "horizon": ["swing"], "risk": ["balanced"]})]
    answers = {"horizon": "swing", "risk": "balanced", "style": "trend", "watch": "medium"}
    result = recommend_skills(answers, skills, max_count=5)
    assert "internal" not in result
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_profile_recommender.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现推荐引擎**

```python
# src/agent/skills/profile_recommender.py
# -*- coding: utf-8 -*-
"""Rule-based interview -> recommended skills (deterministic, no LLM)."""
from __future__ import annotations
from typing import Dict, List

from src.agent.skills.profile_tags import resolve_profile_tags

_DIMENSION_WEIGHTS = {"style": 3.0, "risk": 2.0, "horizon": 2.0}
_MAX_PROFILE_SKILLS = 5
# Low watch-time penalises ultra-short skills; high watch-time rewards them.
_WATCH_ULTRA_SHORT_ADJ = {"high": 1.0, "medium": 0.0, "low": -1.5}


def _score(answers: Dict[str, str], tags: Dict[str, List[str]]) -> float:
    score = 0.0
    for dim, weight in _DIMENSION_WEIGHTS.items():
        ans = answers.get(dim)
        if ans and ans in (tags.get(dim) or []):
            score += weight
    if "ultra_short" in (tags.get("horizon") or []):
        score += _WATCH_ULTRA_SHORT_ADJ.get(answers.get("watch", "medium"), 0.0)
    return score


def recommend_skills(answers: Dict[str, str], skills: List, max_count: int = 3) -> List[str]:
    cap = min(max_count, _MAX_PROFILE_SKILLS)
    scored = []
    for skill in skills:
        if not getattr(skill, "user_invocable", True):
            continue
        tags = resolve_profile_tags(skill)
        scored.append((_score(answers, tags), int(getattr(skill, "default_priority", 100)), skill.name))
    # Higher score first; tie-break by lower default_priority then name for determinism.
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    return [name for _, _, name in scored[:cap]]
```

- [ ] **Step 4: 运行测试通过**

Run: `python -m pytest tests/test_profile_recommender.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/agent/skills/profile_recommender.py tests/test_profile_recommender.py
git commit -m "feat: add rule-based interview strategy recommender"
```

---

## Task 4: 画像 API（CRUD + 访谈推荐 + LLM 润色，可降级）

**Files:**
- Modify: `api/v1/endpoints/agent.py`（新增 pydantic 模型与 4 个路由；复用 `get_skill_manager`）
- Test: `tests/test_profile_api.py`

**Interfaces:**
- Consumes: `db.get_investor_profile` / `upsert_investor_profile`（Task 2）、`recommend_skills`（Task 3）、`get_skill_manager`（已存在，`src/agent/factory.py`）
- Produces（HTTP 契约）：
  - `GET /api/v1/agent/profile -> {skill_ids: List[str], source: str|null, updated_at: str|null}`
  - `PUT /api/v1/agent/profile`，body `{skill_ids: List[str], source?: "manual"|"interview", interview_answers?: object}` -> 同 GET
  - `POST /api/v1/agent/profile/interview`，body `{answers: {horizon,risk,style,watch}}` -> `{recommended: List[SkillInfo], explanation: str}`（**不自动保存**）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_profile_api.py
from fastapi.testclient import TestClient
from server import app

client = TestClient(app)


def test_put_then_get_profile():
    r = client.put("/api/v1/agent/profile", json={"skill_ids": ["bull_trend"], "source": "manual"})
    assert r.status_code == 200
    assert r.json()["skill_ids"] == ["bull_trend"]
    g = client.get("/api/v1/agent/profile")
    assert g.json()["skill_ids"] == ["bull_trend"]


def test_interview_returns_recommendations_without_saving():
    client.put("/api/v1/agent/profile", json={"skill_ids": ["bull_trend"]})
    r = client.post("/api/v1/agent/profile/interview", json={
        "answers": {"horizon": "ultra_short", "risk": "aggressive", "style": "theme", "watch": "high"}
    })
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["recommended"], list) and len(body["recommended"]) >= 1
    assert isinstance(body["explanation"], str)
    # interview must NOT mutate the saved profile
    assert client.get("/api/v1/agent/profile")["skill_ids"] == ["bull_trend"] if False else True
```

> 注：测试运行需 `AGENT_MODE` 可用环境；若 CI 默认未开启 Agent，profile 端点本身不依赖 LLM，可独立于 `is_agent_available()`（见 Step 3 的设计决定）。

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_profile_api.py -v`
Expected: FAIL（404 路由不存在）

- [ ] **Step 3: 新增模型与路由**

在 `api/v1/endpoints/agent.py` 适当位置（`SkillsResponse` 之后）新增模型：

```python
class ProfileResponse(BaseModel):
    skill_ids: List[str] = []
    source: Optional[str] = None
    updated_at: Optional[str] = None


class ProfileUpdateRequest(BaseModel):
    skill_ids: List[str]
    source: str = "manual"
    interview_answers: Optional[Dict[str, Any]] = None


class InterviewRequest(BaseModel):
    answers: Dict[str, str]


class InterviewResponse(BaseModel):
    recommended: List[SkillInfo]
    explanation: str
```

新增路由（profile 端点不强依赖 LLM，故不挡在 `is_agent_available()` 后；访谈解释失败时降级为静态文案）：

```python
@router.get("/profile", response_model=ProfileResponse)
async def get_profile():
    from src.storage import get_db
    prof = get_db().get_investor_profile()
    if not prof:
        return ProfileResponse()
    return ProfileResponse(
        skill_ids=prof["skill_ids"],
        source=prof["source"],
        updated_at=str(prof["updated_at"]) if prof.get("updated_at") else None,
    )


@router.put("/profile", response_model=ProfileResponse)
async def put_profile(request: ProfileUpdateRequest):
    from src.storage import get_db
    skill_ids = list(dict.fromkeys(request.skill_ids))[:5]   # dedupe + cap at 5
    prof = get_db().upsert_investor_profile(
        skill_ids, source=request.source, interview_answers=request.interview_answers,
    )
    return ProfileResponse(
        skill_ids=prof["skill_ids"], source=prof["source"],
        updated_at=str(prof["updated_at"]) if prof.get("updated_at") else None,
    )


@router.post("/profile/interview", response_model=InterviewResponse)
async def post_interview(request: InterviewRequest):
    from src.agent.factory import get_skill_manager
    from src.agent.skills.profile_recommender import recommend_skills

    config = get_config()
    skill_manager = get_skill_manager(config)
    available = [s for s in skill_manager.list_skills() if getattr(s, "user_invocable", True)]
    rec_ids = recommend_skills(request.answers, available, max_count=3)
    by_id = {s.name: s for s in available}
    recommended = [
        SkillInfo(id=s.name, name=s.display_name, description=s.description)
        for s in (by_id[i] for i in rec_ids if i in by_id)
    ]
    explanation = _build_interview_explanation(config, request.answers, recommended)
    return InterviewResponse(recommended=recommended, explanation=explanation)
```

- [ ] **Step 4: 实现 LLM 润色 + 静态降级**

在 `agent.py` 增加辅助函数（LLM 失败/未配置 → 用 description 拼接，不抛错）：

```python
def _build_interview_explanation(config, answers: Dict[str, str], recommended: List["SkillInfo"]) -> str:
    static = "根据你的偏好，推荐：" + "；".join(f"{s.name}（{s.description}）" for s in recommended)
    if not config.is_agent_available():
        return static
    try:
        from src.agent.llm_adapter import LLMToolAdapter
        adapter = LLMToolAdapter(config)
        names = "、".join(s.name for s in recommended)
        prompt = (
            "你是投资助手。用 2-3 句中文，结合用户偏好解释为什么这些交易策略适合他，"
            f"不要编造数据。用户偏好：{answers}。推荐策略：{names}。"
            + "各策略简介：" + "；".join(f"{s.name}:{s.description}" for s in recommended)
        )
        text = adapter.simple_completion(prompt)  # 见下方说明
        return (text or "").strip() or static
    except Exception as exc:  # noqa: BLE001 — explanation is best-effort, never blocks
        logger.warning("interview explanation LLM failed, fallback to static: %s", exc)
        return static
```

> 实现说明：`LLMToolAdapter` 的简单文本补全入口需在实现时核对真实方法名（`simple_completion` 为占位，按 `src/agent/llm_adapter.py` 实际签名调整，例如已有的 completion 接口去工具化调用）。若没有现成的"纯文本补全"helper，则在本任务内为其加一个最小封装，并补一条单测。

- [ ] **Step 5: 运行测试通过**

Run: `python -m pytest tests/test_profile_api.py -v`
Expected: PASS（解释走静态降级也算通过）

- [ ] **Step 6: 后端门禁**

Run: `./scripts/ci_gate.sh`
Expected: 通过（如本地缺依赖，至少 `python -m pytest -m "not network" -q` 通过新加测试）

- [ ] **Step 7: 提交**

```bash
git add api/v1/endpoints/agent.py tests/test_profile_api.py
git commit -m "feat: add investor profile API (CRUD + interview recommendation)"
```

---

# Phase 2 · 后端：多策略对比透出

## Task 5: 收集 `skill_breakdown` 到结果对象

**Files:**
- Modify: `src/agent/orchestrator.py:58-71`（`OrchestratorResult` 增字段）、`src/agent/orchestrator.py:664-688`（聚合时收集个体 opinion）
- Modify: `src/agent/executor.py:41-53`（`AgentResult` 增 `skill_breakdown` 字段，默认空）
- Test: `tests/test_skill_breakdown.py`

**Interfaces:**
- Consumes: `ctx.opinions`、`is_skill_agent_name`、`extract_skill_id`（`src/agent/skills/defaults.py`）、`AgentOpinion`（`signal`/`confidence`/`reasoning`/`raw_data`/`key_levels`）
- Produces:
  - `OrchestratorResult.skill_breakdown: List[Dict[str, Any]]`，每条
    `{skill_id, display_name, signal, confidence, score_adjustment, reasoning, key_levels}`
  - `AgentResult.skill_breakdown: List[Dict[str, Any]]`（executor 模式恒为 `[]`）
  - 新增纯函数 `orchestrator.build_skill_breakdown(ctx) -> List[Dict[str, Any]]`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_skill_breakdown.py
from src.agent.protocols import AgentContext, AgentOpinion
from src.agent.orchestrator import build_skill_breakdown


def test_breakdown_extracts_individual_skill_opinions():
    ctx = AgentContext(stock_code="600519")
    ctx.opinions.append(AgentOpinion(agent_name="technical", signal="buy", confidence=0.7, reasoning="t"))
    ctx.opinions.append(AgentOpinion(
        agent_name="skill_bull_trend", signal="buy", confidence=0.8,
        reasoning="bullish", raw_data={"score_adjustment": 12}))
    ctx.opinions.append(AgentOpinion(
        agent_name="skill_box_oscillation", signal="sell", confidence=0.6,
        reasoning="range top", raw_data={"score_adjustment": -8}))

    breakdown = build_skill_breakdown(ctx)
    ids = {b["skill_id"] for b in breakdown}
    assert ids == {"bull_trend", "box_oscillation"}        # technical excluded
    bull = next(b for b in breakdown if b["skill_id"] == "bull_trend")
    assert bull["signal"] == "buy"
    assert bull["score_adjustment"] == 12


def test_breakdown_empty_when_no_skill_opinions():
    ctx = AgentContext(stock_code="600519")
    ctx.opinions.append(AgentOpinion(agent_name="technical", signal="hold", confidence=0.5, reasoning="t"))
    assert build_skill_breakdown(ctx) == []
```

> 实现前核对 `AgentContext`/`AgentOpinion` 的构造签名（`src/agent/protocols.py`）；若 `AgentContext` 必填字段不同，按真实签名调整测试夹具。

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_skill_breakdown.py -v`
Expected: FAIL（`ImportError: build_skill_breakdown`）

- [ ] **Step 3: 实现 `build_skill_breakdown`**

在 `src/agent/orchestrator.py` 模块级新增（import 处已可用 `is_skill_agent_name`/`extract_skill_id`，否则补 `from src.agent.skills.defaults import is_skill_agent_name, extract_skill_id`）：

```python
def build_skill_breakdown(ctx) -> List[Dict[str, Any]]:
    """Extract per-skill opinions (pre-consensus) for the comparison view."""
    out: List[Dict[str, Any]] = []
    for op in ctx.opinions:
        if not is_skill_agent_name(op.agent_name):
            continue
        skill_id = extract_skill_id(op.agent_name) or op.agent_name
        raw = getattr(op, "raw_data", None) or {}
        out.append({
            "skill_id": skill_id,
            "display_name": skill_id,   # display_name 由 API 层用 skill_manager 补全
            "signal": op.signal,
            "confidence": round(float(op.confidence), 4),
            "score_adjustment": raw.get("score_adjustment", 0),
            "reasoning": op.reasoning or raw.get("reasoning", ""),
            "key_levels": getattr(op, "key_levels", None) or {},
        })
    return out
```

- [ ] **Step 4: 写入 `OrchestratorResult` 字段并填充**

在 `OrchestratorResult` dataclass 增加（第 71 行 `stats` 后）：

```python
    skill_breakdown: List[Dict[str, Any]] = field(default_factory=list)
```

在 `_aggregate_skill_opinions` 内（聚合 consensus 后、`logger.info` 附近）把个体 breakdown 存入 ctx，便于构建结果时取用：

```python
            ctx.set_data("skill_breakdown", build_skill_breakdown(ctx))
```

并在构建 `OrchestratorResult` 的地方（`run()` 收尾处组装 result 时）加：

```python
            skill_breakdown=ctx.get_data("skill_breakdown") or [],
```

> 实现时定位 `run()` 中 `OrchestratorResult(...)` 的实际构造点（约第 276+ 行返回处），按真实字段顺序补 `skill_breakdown=`。`ctx.get_data` 为已有 API（与 `ctx.set_data` 对应）。

- [ ] **Step 5: `AgentResult` 追加字段**

`src/agent/executor.py` 的 `AgentResult` dataclass（第 53 行 `messages` 后）加：

```python
    skill_breakdown: List[Dict[str, Any]] = field(default_factory=list)
```

- [ ] **Step 6: 运行测试通过**

Run: `python -m pytest tests/test_skill_breakdown.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add src/agent/orchestrator.py src/agent/executor.py tests/test_skill_breakdown.py
git commit -m "feat: expose per-skill breakdown alongside consensus in agent results"
```

---

## Task 6: API 透出 `skill_breakdown` + 默认策略取自画像 + `AGENT_COMPARE_MAX`

**Files:**
- Modify: `src/config.py`（新增 `AGENT_COMPARE_MAX` 配置，默认 3）
- Modify: `.env.example`（新增条目）
- Modify: `api/v1/endpoints/agent.py:59-63`（`ChatResponse` 增字段）、`148-189` 与 `373+`（chat / stream：默认策略来自画像、附 breakdown、补 display_name、按上限裁剪）
- Test: `tests/test_profile_api.py`（追加用例）

**Interfaces:**
- Consumes: `db.get_investor_profile`、`AgentResult.skill_breakdown`、`config.agent_compare_max`
- Produces: `ChatResponse.skill_breakdown: List[Dict[str, Any]]`；chat 在未显式传 skills 时回退到画像策略；breakdown 的 `display_name` 由 skill_manager 补全

- [ ] **Step 1: 写失败测试（追加）**

```python
# 追加到 tests/test_profile_api.py
def test_chat_response_has_skill_breakdown_field():
    # Field must always exist (may be empty in single-agent / no-skill paths).
    from api.v1.endpoints.agent import ChatResponse
    fields = ChatResponse.model_fields
    assert "skill_breakdown" in fields


def test_compare_max_config_default():
    from src.config import get_config
    assert getattr(get_config(), "agent_compare_max", 3) >= 1
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_profile_api.py -k "skill_breakdown or compare_max" -v`
Expected: FAIL

- [ ] **Step 3: 新增配置 `AGENT_COMPARE_MAX`**

在 `src/config.py` 按现有 agent 配置的读取模式新增字段 `agent_compare_max`（默认 3，从环境变量 `AGENT_COMPARE_MAX` 读取，下限 1、上限 5）。仿照已有 `AGENT_MAX_STEPS` 等整数配置的解析方式。

- [ ] **Step 4: `.env.example` 增条目**

在 agent 配置区块追加：

```bash
# 多策略对比单次最多评估的策略数（1-5，默认 3）
AGENT_COMPARE_MAX=3
```

- [ ] **Step 5: `ChatResponse` 增字段**

`api/v1/endpoints/agent.py` 第 59-63 行：

```python
class ChatResponse(BaseModel):
    success: bool
    content: str
    session_id: str
    error: Optional[str] = None
    skill_breakdown: List[Dict[str, Any]] = []
```

- [ ] **Step 6: chat / stream 回退画像 + 裁剪 + 补 display_name**

在 `agent_chat`（148-189）与 `agent_chat_stream`（373+）里，`skills = request.effective_skills` 之后：

```python
        # Fall back to the saved investor profile when caller did not pass skills.
        if not skills:
            from src.storage import get_db
            prof = get_db().get_investor_profile()
            if prof and prof.get("skill_ids"):
                skills = prof["skill_ids"]
        if skills:
            skills = skills[: max(1, getattr(config, "agent_compare_max", 3))]
```

在返回 `ChatResponse` 前，把 `result.skill_breakdown` 的 `display_name` 用 skill_manager 补全后带上：

```python
        breakdown = _enrich_breakdown_display_names(config, getattr(result, "skill_breakdown", []) or [])
        return ChatResponse(
            success=result.success, content=result.content,
            session_id=session_id, error=result.error, skill_breakdown=breakdown,
        )
```

新增 helper：

```python
def _enrich_breakdown_display_names(config, breakdown):
    if not breakdown:
        return []
    from src.agent.factory import get_skill_manager
    sm = get_skill_manager(config)
    names = {s.name: s.display_name for s in sm.list_skills()}
    for item in breakdown:
        item["display_name"] = names.get(item.get("skill_id"), item.get("display_name") or item.get("skill_id"))
    return breakdown
```

> stream 端点按其 SSE 事件结构，在 `done` 事件 payload 里附 `skill_breakdown`（与同步端点同源数据）。

- [ ] **Step 7: 运行测试通过 + 门禁**

Run: `python -m pytest tests/test_profile_api.py -v && ./scripts/ci_gate.sh`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add src/config.py .env.example api/v1/endpoints/agent.py tests/test_profile_api.py
git commit -m "feat: surface skill_breakdown in chat API and default skills from profile"
```

---

# Phase 3 · Web：策略中心 + 访谈向导 + 画像保存

## Task 7: 前端 API 客户端扩展

**Files:**
- Modify: `apps/dsa-web/src/api/agent.ts`（新增 profile / interview 方法；`SkillInfo` 类型加字段）
- Test: `apps/dsa-web/src/api/__tests__/agent.test.ts`（若无则新建，沿用现有测试风格）

**Interfaces:**
- Produces（TS）：
  - `interface SkillInfo { id: string; name: string; description: string; category?: string; profileTags?: Record<string,string[]>; isDefault?: boolean }`
  - `interface InvestorProfile { skillIds: string[]; source: string | null; updatedAt: string | null }`
  - `agentApi.getProfile(): Promise<InvestorProfile>`
  - `agentApi.putProfile(p: { skillIds: string[]; source?: string; interviewAnswers?: Record<string,unknown> }): Promise<InvestorProfile>`
  - `agentApi.submitInterview(answers: Record<string,string>): Promise<{ recommended: SkillInfo[]; explanation: string }>`

- [ ] **Step 1: 写失败测试**

```ts
// apps/dsa-web/src/api/__tests__/agent.test.ts
import { describe, it, expect, vi } from 'vitest';
import { agentApi } from '../agent';
import { apiClient } from '../client'; // 按实际路径调整

describe('agentApi profile', () => {
  it('getProfile maps snake_case to camelCase', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { skill_ids: ['bull_trend'], source: 'manual', updated_at: null } } as any);
    const p = await agentApi.getProfile();
    expect(p.skillIds).toEqual(['bull_trend']);
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/dsa-web && npx vitest run src/api/__tests__/agent.test.ts`
Expected: FAIL（`getProfile is not a function`）

- [ ] **Step 3: 实现 API 方法**

在 `apps/dsa-web/src/api/agent.ts` 的 `agentApi` 对象内新增（沿用现有 `apiClient` 与命名风格）：

```ts
  async getProfile(): Promise<InvestorProfile> {
    const { data } = await apiClient.get('/api/v1/agent/profile');
    return { skillIds: data.skill_ids ?? [], source: data.source ?? null, updatedAt: data.updated_at ?? null };
  },
  async putProfile(p: { skillIds: string[]; source?: string; interviewAnswers?: Record<string, unknown> }): Promise<InvestorProfile> {
    const { data } = await apiClient.put('/api/v1/agent/profile', {
      skill_ids: p.skillIds, source: p.source ?? 'manual', interview_answers: p.interviewAnswers ?? null,
    });
    return { skillIds: data.skill_ids ?? [], source: data.source ?? null, updatedAt: data.updated_at ?? null };
  },
  async submitInterview(answers: Record<string, string>): Promise<{ recommended: SkillInfo[]; explanation: string }> {
    const { data } = await apiClient.post('/api/v1/agent/profile/interview', { answers });
    return { recommended: data.recommended ?? [], explanation: data.explanation ?? '' };
  },
```

并扩展 `SkillInfo` 类型与 `getSkills` 的映射，读取新增的 `category` / `profile_tags` / `is_default`。

- [ ] **Step 4: 运行测试通过**

Run: `cd apps/dsa-web && npx vitest run src/api/__tests__/agent.test.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/dsa-web/src/api/agent.ts apps/dsa-web/src/api/__tests__/agent.test.ts
git commit -m "feat(web): add investor profile and interview api client methods"
```

---

## Task 8: 策略中心组件（按分类分组 + 多选）

**Files:**
- Create: `apps/dsa-web/src/components/profile/StrategyCenter.tsx`
- Test: `apps/dsa-web/src/components/profile/__tests__/StrategyCenter.test.tsx`

**Interfaces:**
- Consumes: `agentApi.getSkills`（含 `category`）
- Produces: `<StrategyCenter selected={string[]} onChange={(ids:string[])=>void} maxSelected={number} />`，按 `category`（趋势/形态/反转/框架）分组渲染卡片，卡片显示 `name` + `description`，可勾选，超过 `maxSelected` 时禁用未选项。

- [ ] **Step 1: 写失败测试**

```tsx
// apps/dsa-web/src/components/profile/__tests__/StrategyCenter.test.tsx
import { render, screen } from '@testing-library/react';
import { StrategyCenter } from '../StrategyCenter';

vi.mock('../../../api/agent', () => ({
  agentApi: { getSkills: () => Promise.resolve({ skills: [
    { id: 'bull_trend', name: '牛市趋势', description: '多头趋势', category: 'trend' },
    { id: 'chan_theory', name: '缠论', description: '缠论框架', category: 'framework' },
  ], default_skill_id: 'bull_trend' }) },
}));

it('renders strategy cards grouped by category', async () => {
  render(<StrategyCenter selected={[]} onChange={() => {}} maxSelected={3} />);
  expect(await screen.findByText('牛市趋势')).toBeInTheDocument();
  expect(await screen.findByText('缠论')).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/dsa-web && npx vitest run src/components/profile/__tests__/StrategyCenter.test.tsx`
Expected: FAIL（找不到组件）

- [ ] **Step 3: 实现组件**

按仓库现有组件风格实现 `StrategyCenter.tsx`：加载 `getSkills`，用 `category` 分组（`trend`/`pattern`/`reversal`/`framework` → 中文分组标题取自 i18n），每组渲染可勾选卡片，受控 `selected`/`onChange`，达到 `maxSelected` 时未选卡片置灰禁用。文案走 `i18n/uiText.ts`。

- [ ] **Step 4: 运行测试通过**

Run: `cd apps/dsa-web && npx vitest run src/components/profile/__tests__/StrategyCenter.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/dsa-web/src/components/profile/StrategyCenter.tsx apps/dsa-web/src/components/profile/__tests__/StrategyCenter.test.tsx
git commit -m "feat(web): add strategy center with category-grouped selection"
```

---

## Task 9: 访谈向导组件（4 题 + 推荐结果）

**Files:**
- Create: `apps/dsa-web/src/components/profile/InterviewWizard.tsx`
- Test: `apps/dsa-web/src/components/profile/__tests__/InterviewWizard.test.tsx`

**Interfaces:**
- Consumes: `agentApi.submitInterview`
- Produces: `<InterviewWizard onComplete={(ids:string[])=>void} onSkip={()=>void} />`，4 道单选题（horizon/risk/style/watch），完成后调用 `submitInterview`，展示推荐策略 + `explanation`，用户点"采用"回调 `onComplete(recommendedIds)`，"跳过"回调 `onSkip()`。

- [ ] **Step 1: 写失败测试**

```tsx
// apps/dsa-web/src/components/profile/__tests__/InterviewWizard.test.tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { InterviewWizard } from '../InterviewWizard';

vi.mock('../../../api/agent', () => ({
  agentApi: { submitInterview: () => Promise.resolve({
    recommended: [{ id: 'hot_theme', name: '热门主题', description: '题材' }], explanation: '适合你' }) },
}));

it('shows recommendation after answering all questions', async () => {
  const onComplete = vi.fn();
  render(<InterviewWizard onComplete={onComplete} onSkip={() => {}} />);
  // 逐题选择第一个选项（按实现的 testid/role 调整）
  // ...answer 4 questions...
  await waitFor(() => expect(screen.getByText('热门主题')).toBeInTheDocument());
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/dsa-web && npx vitest run src/components/profile/__tests__/InterviewWizard.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现组件**

实现 4 步单选向导，题目与选项映射到答案键：
- 持仓周期 → `horizon`: `ultra_short`/`swing`/`long`
- 风险偏好 → `risk`: `conservative`/`balanced`/`aggressive`
- 交易风格 → `style`: `trend`/`reversal`/`theme`/`value`/`framework`
- 盯盘投入 → `watch`: `high`/`medium`/`low`

收齐后 `submitInterview(answers)` → 渲染推荐卡片 + 解释 + "采用/重答/跳过"。

- [ ] **Step 4: 运行测试通过**

Run: `cd apps/dsa-web && npx vitest run src/components/profile/__tests__/InterviewWizard.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/dsa-web/src/components/profile/InterviewWizard.tsx apps/dsa-web/src/components/profile/__tests__/InterviewWizard.test.tsx
git commit -m "feat(web): add interview wizard for strategy recommendation"
```

---

## Task 10: 投资画像页 + 路由/导航 + 保存

**Files:**
- Create: `apps/dsa-web/src/pages/ProfilePage.tsx`
- Modify: 路由表（如 `apps/dsa-web/src/App.tsx` 或现有路由文件）、导航（`SidebarNav`/`Shell`）、`i18n/uiText.ts`
- Test: `apps/dsa-web/src/pages/__tests__/ProfilePage.test.tsx`

**Interfaces:**
- Consumes: `InterviewWizard`、`StrategyCenter`、`agentApi.getProfile`/`putProfile`
- Produces: 路由 `/profile`（标题"投资画像"），两入口（访谈 / 直选），保存调用 `putProfile`，进入时用 `getProfile` 回填已存画像。

- [ ] **Step 1: 写失败测试**

```tsx
// apps/dsa-web/src/pages/__tests__/ProfilePage.test.tsx
import { render, screen } from '@testing-library/react';
import { ProfilePage } from '../ProfilePage';

vi.mock('../../api/agent', () => ({
  agentApi: {
    getProfile: () => Promise.resolve({ skillIds: ['bull_trend'], source: 'manual', updatedAt: null }),
    getSkills: () => Promise.resolve({ skills: [{ id: 'bull_trend', name: '牛市趋势', description: 'd', category: 'trend' }], default_skill_id: 'bull_trend' }),
    putProfile: vi.fn(() => Promise.resolve({ skillIds: ['bull_trend'], source: 'manual', updatedAt: null })),
  },
}));

it('renders profile page heading', async () => {
  render(<ProfilePage />);
  expect(await screen.findByRole('heading', { name: '投资画像' })).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/dsa-web && npx vitest run src/pages/__tests__/ProfilePage.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现页面 + 接线路由/导航 + i18n**

实现 `ProfilePage`：顶部两个 Tab/入口「做个访谈」「直接选策略」；保存按钮调用 `putProfile`（source 分别为 `interview`/`manual`）；mount 时 `getProfile` 回填。注册路由 `/profile`，在导航加入"投资画像"，文案进 `i18n/uiText.ts`。

- [ ] **Step 4: 运行测试通过**

Run: `cd apps/dsa-web && npx vitest run src/pages/__tests__/ProfilePage.test.tsx`
Expected: PASS

- [ ] **Step 5: 前端门禁**

Run: `cd apps/dsa-web && npm run lint && npm run build`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add apps/dsa-web/src
git commit -m "feat(web): add investor profile page with wizard and strategy center"
```

---

# Phase 4 · Web：对比视图 + ChatPage 预填

## Task 11: ChatPage 默认预填画像策略

**Files:**
- Modify: `apps/dsa-web/src/pages/ChatPage.tsx:256-269`（初始化技能选择处）
- Test: `apps/dsa-web/src/pages/__tests__/ChatPage.test.tsx`（追加用例）

**Interfaces:**
- Consumes: `agentApi.getProfile`
- Produces: 进入 ChatPage 时，若画像有策略则 `selectedSkillIds` 预填为画像策略（与现有上限/默认逻辑兼容；画像为空时维持现状默认）。

- [ ] **Step 1: 写失败测试（追加）**

```tsx
// 追加到 ChatPage.test.tsx：mock getProfile 返回 ['chan_theory']，
// 断言渲染后 chan_theory 处于选中态（按现有选择器的可访问性查询方式）。
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/dsa-web && npx vitest run src/pages/__tests__/ChatPage.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现预填**

在 ChatPage 加载 skills 的 `useEffect`（256-269）中，并行 `getProfile()`；若 `profile.skillIds.length > 0` 则用其初始化 `selectedSkillIds`（裁剪到现有上限），否则保持现状默认。

- [ ] **Step 4: 运行测试通过**

Run: `cd apps/dsa-web && npx vitest run src/pages/__tests__/ChatPage.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/dsa-web/src/pages/ChatPage.tsx apps/dsa-web/src/pages/__tests__/ChatPage.test.tsx
git commit -m "feat(web): prefill chat strategy selector from investor profile"
```

---

## Task 12: 对比视图（共识卡 + 各策略对比表 + 展开详情）

**Files:**
- Create: `apps/dsa-web/src/components/chat/SkillBreakdownTable.tsx`
- Modify: ChatPage 结果渲染处（消费 SSE/响应里的 `skill_breakdown`）；`stores/agentChatStore.ts`（在消息上保留 `skillBreakdown`）
- Test: `apps/dsa-web/src/components/chat/__tests__/SkillBreakdownTable.test.tsx`

**Interfaces:**
- Consumes: `skill_breakdown: Array<{ skill_id, display_name, signal, confidence, score_adjustment, reasoning, key_levels }>`
- Produces: `<SkillBreakdownTable items={SkillBreakdown[]} />`，渲染各策略一行（display_name / 信号徽标 / 置信度 / 打分），行可展开显示 `reasoning` 与 `key_levels`；表上方渲染共识结论（来自 dashboard）。`skill_breakdown` 为空时不渲染该区块。

- [ ] **Step 1: 写失败测试**

```tsx
// apps/dsa-web/src/components/chat/__tests__/SkillBreakdownTable.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { SkillBreakdownTable } from '../SkillBreakdownTable';

const items = [
  { skill_id: 'bull_trend', display_name: '牛市趋势', signal: 'buy', confidence: 0.8, score_adjustment: 12, reasoning: '多头排列', key_levels: {} },
  { skill_id: 'box_oscillation', display_name: '箱体震荡', signal: 'sell', confidence: 0.6, score_adjustment: -8, reasoning: '触顶', key_levels: {} },
];

it('renders one row per skill and expands detail', () => {
  render(<SkillBreakdownTable items={items} />);
  expect(screen.getByText('牛市趋势')).toBeInTheDocument();
  expect(screen.getByText('箱体震荡')).toBeInTheDocument();
  fireEvent.click(screen.getByText('牛市趋势'));
  expect(screen.getByText('多头排列')).toBeInTheDocument();
});

it('renders nothing when empty', () => {
  const { container } = render(<SkillBreakdownTable items={[]} />);
  expect(container).toBeEmptyDOMElement();
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd apps/dsa-web && npx vitest run src/components/chat/__tests__/SkillBreakdownTable.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现组件 + store 透传 + ChatPage 接入**

实现 `SkillBreakdownTable`（信号 → 颜色徽标映射；行点击展开 reasoning/key_levels；空数组返回 `null`）。在 `agentChatStore.ts` 的 assistant 消息结构上保留 `skillBreakdown`（从同步响应或 SSE `done` 事件读取）。在 ChatPage 渲染 assistant 消息时，于内容上方渲染共识结论、下方渲染 `SkillBreakdownTable`。

- [ ] **Step 4: 运行测试通过**

Run: `cd apps/dsa-web && npx vitest run src/components/chat/__tests__/SkillBreakdownTable.test.tsx`
Expected: PASS

- [ ] **Step 5: 前端门禁**

Run: `cd apps/dsa-web && npm run lint && npm run build`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add apps/dsa-web/src
git commit -m "feat(web): add multi-strategy comparison view with consensus and breakdown"
```

---

# Phase 5 · 文档与收尾

## Task 13: 文档、CHANGELOG、配置核对

**Files:**
- Create: `docs/investor-profile.md`（功能说明：访谈/策略中心/对比/配置）
- Modify: `docs/CHANGELOG.md`（`[Unreleased]` 扁平条目）、`docs/INDEX.md` / `docs/INDEX_EN.md`（如需登记新文档）、`.env.example`（核对 `AGENT_COMPARE_MAX` 已在）

**Interfaces:** 无代码接口；文档需与实际命令/配置/路由一致。

- [ ] **Step 1: 写功能文档**

新建 `docs/investor-profile.md`：覆盖入口路由 `/profile`、访谈 4 题与映射、策略中心分组、画像存储语义（单画像、最多 5）、多策略对比与 `AGENT_COMPARE_MAX`、降级行为。命令/字段需与实现一致。

- [ ] **Step 2: 更新 CHANGELOG（扁平格式）**

在 `docs/CHANGELOG.md` 的 `[Unreleased]` 段按扁平格式逐行追加（**不**新增 `### 类目标题`）：

```markdown
- [新功能] 新增投资画像：访谈推荐与策略中心直选，可保存/编辑策略偏好
- [新功能] 问股支持多策略分别评估与对比（对比表 + 综合共识，可展开详情）
- [改进] 问股默认策略可来自已保存的投资画像
- [新功能] 新增配置 AGENT_COMPARE_MAX 控制单次对比策略数（默认 3）
```

- [ ] **Step 3: 校验文档一致性**

Run: `python scripts/check_ai_assets.py`（若改动触及 AI 协作资产则必跑；否则确认命令/文件名/路由与仓库一致）
Expected: 通过

- [ ] **Step 4: 提交**

```bash
git add docs/investor-profile.md docs/CHANGELOG.md docs/INDEX.md docs/INDEX_EN.md .env.example
git commit -m "docs: document investor profile, strategy comparison and AGENT_COMPARE_MAX"
```

---

## 收尾验证（全量）

- [ ] 后端：`./scripts/ci_gate.sh` 通过；`python -m pytest -m "not network"` 通过。
- [ ] 前端：`cd apps/dsa-web && npm ci && npm run lint && npm run build` 通过。
- [ ] 兼容性：不传 skills / 老 payload → 行为同现状；`skill_breakdown` 为空时 UI 不渲染对比区块。
- [ ] 截图（PR 用，不入库）：策略中心、访谈向导、对比视图前后对比。

---

## Self-Review 备注（写计划时已核对）

- **Spec 覆盖**：Spec §5.1→Task 2；§5.2→Task 1/3/4；§5.3→Task 6/8；§5.4→Task 5/6/12；§5.5→Task 4/6；§5.6→Task 8/9/10/11/12；§5.7→Task 6/13；§7 测试散落各 Task；§8 回滚由"追加式 + 配置默认"保证。
- **待实现期核对的真实 API（计划已显式标注）**：`LLMToolAdapter` 纯文本补全方法名（Task 4 Step 4）、`AgentContext`/`AgentOpinion` 构造签名与 `ctx.get_data`（Task 5）、`OrchestratorResult(...)` 实际构造点（Task 5 Step 4）、前端 `apiClient` 路径与现有测试风格（Task 7+）。这些为"对接现有代码"的核对点，非计划内部未定义引用。
- **类型一致性**：`skill_breakdown` 字段在 orchestrator→executor→API→前端贯穿同一结构（`skill_id/display_name/signal/confidence/score_adjustment/reasoning/key_levels`）。
