# Applicant Growth Paths Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Applicant 已有岗位匹配结果增加一个同步、可解释、可复用的成长路径生成 API。

**Architecture:** Growth Service 复用 Matching 的可见性校验，读取不可变 Match Run/Match Result 快照，只把岗位和标准技能事实作为上下文发送到现有 OpenAI Responses endpoint。Shared Responses Client 负责 HTTP、重试、Structured Outputs 响应解析；Growth Service 负责缺失 required 技能范围校验、快照、幂等、事务和审计。结果写入 PostgreSQL `growth_paths`，不使用 Celery、Redis、Neo4j、LangGraph 或外部课程检索。

**Tech Stack:** Python 3.12、FastAPI、Pydantic 2、SQLAlchemy 2 AsyncSession、PostgreSQL JSONB、Alembic、httpx、pytest、Ruff、OpenAI Responses API `text.format` Structured Outputs。

---

## 0. Baseline and constraints

**Files:**

- Read: `docs/superpowers/specs/2026-08-07-growth-paths-design.md`
- Read: `backend/app/matching/service.py`
- Read: `backend/app/resumes/llm.py`
- Read: `backend/tests/test_resume_llm.py`
- Read: `backend/tests/matching_fixtures.py`

- [ ] **Step 1: Verify the current baseline before editing**

Run from `backend/`:

```bash
uv run pytest -q
uv run ruff check .
```

Expected: the existing suite is green and Ruff reports no errors. Do not modify fixtures or configuration to hide a database runtime failure.

- [ ] **Step 2: Confirm only the existing report is unrelated work**

Run from the repository root:

```bash
git status --short --branch
```

Expected: `docs/superpowers/reports/` may remain untracked from the previous report task. It must not be staged in any Growth Path commit.

## Task 1: Extract the shared Responses Structured Outputs client

**Files:**

- Create: `backend/app/llm/__init__.py`
- Create: `backend/app/llm/responses.py`
- Modify: `backend/app/resumes/llm.py`
- Test: `backend/tests/test_responses_client.py`
- Test: `backend/tests/test_resume_llm.py`

- [ ] **Step 1: Write the failing generic client contract test**

Add a minimal Pydantic payload and assert that the client sends the existing Responses contract:

```python
class DemoPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(min_length=1)


async def test_structured_client_posts_strict_responses_schema():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json=completed_response(json.dumps({"value": "ok"})),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await StructuredResponsesClient(http=http).generate(
            url="https://provider.test/v1/responses",
            api_key="secret",
            model="test-model",
            instructions="return the schema",
            input_text="context",
            schema_name="demo_v1",
            response_model=DemoPayload,
            metadata={"operation": "demo"},
        )

    body = json.loads(captured["request"].content)
    assert body["text"]["format"] == {
        "type": "json_schema",
        "name": "demo_v1",
        "strict": True,
        "schema": DemoPayload.model_json_schema(),
    }
    assert body["store"] is False
    assert body["stream"] is False
    assert "tools" not in body
    assert result.payload.value == "ok"
```

- [ ] **Step 2: Run the new test and verify the expected RED failure**

Run:

```bash
uv run pytest tests/test_responses_client.py::test_structured_client_posts_strict_responses_schema -q
```

Expected: FAIL because `app.llm.responses.StructuredResponsesClient` does not exist yet.

- [ ] **Step 3: Implement the smallest generic client**

Implement `StructuredResponsesClient.generate()` with these exact boundaries:

```python
T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class StructuredResponseResult(Generic[T]):
    payload: T
    response_id: str | None
    returned_model: str | None
    status: str
    usage: dict[str, int | None]
    provider_attempts: int
    response_sha256: str


class ResponsesAPIError(Exception):
    def __init__(self, code: str, stage: str, retryable: bool,
                 http_status: int | None = None) -> None:
        self.code = code
        self.stage = stage
        self.retryable = retryable
        self.http_status = http_status
        super().__init__(code)
```

The implementation must preserve the current Resume behavior: two attempts for timeout, request errors, 429, 5xx and invalid/incomplete responses; no retry for ordinary 4xx or refusal; parse every completed `message` output text; validate with `response_model.model_validate_json`; and never expose the raw provider envelope.

- [ ] **Step 4: Run the generic client tests GREEN**

Run:

```bash
uv run pytest tests/test_responses_client.py -q
```

Expected: all new shared-client tests pass.

- [ ] **Step 5: Adapt Resume without changing its public contract**

Keep `app.resumes.llm.ResponsesClient.parse_resume()` and `LLMParseResult` available to existing imports. The wrapper should delegate to `StructuredResponsesClient.generate()` with `ResumeParseResponse`, `PROMPT_VERSION`, and the existing resume request body. Preserve `ResumeLLMError` as the resume-facing error name by translating or aliasing the shared error fields.

- [ ] **Step 6: Run the existing Resume LLM tests**

Run:

```bash
uv run pytest tests/test_resume_llm.py -q
```

Expected: all existing Resume Structured Outputs, refusal, retry, schema and response parsing tests remain green.

- [ ] **Step 7: Commit the shared client extraction**

```bash
git add backend/app/llm backend/app/resumes/llm.py backend/tests/test_responses_client.py backend/tests/test_resume_llm.py
git commit -m "refactor: share responses structured client"
```

## Task 2: Add Growth Path schemas and semantic validation

**Files:**

- Create: `backend/app/growth/__init__.py`
- Create: `backend/app/growth/schemas.py`
- Test: `backend/tests/test_growth_schemas.py`

- [ ] **Step 1: Write failing schema and scope tests**

Cover one valid plan and all three semantic failures:

```python
def test_growth_plan_rejects_extra_fields_and_invalid_limits():
    with pytest.raises(ValidationError):
        GrowthPlanLLM.model_validate({**VALID_PLAN, "unexpected": True})

    invalid = copy.deepcopy(VALID_PLAN)
    invalid["stages"][0]["estimated_weeks"] = 0
    with pytest.raises(ValidationError):
        GrowthPlanLLM.model_validate(invalid)


def test_validate_capability_scope_rejects_missing_duplicate_and_unknown():
    expected = {CAPABILITY_A, CAPABILITY_B}
    with pytest.raises(GrowthPathScopeError):
        validate_capability_scope(plan_with_ids([CAPABILITY_A]), expected)
    with pytest.raises(GrowthPathScopeError):
        validate_capability_scope(plan_with_ids([CAPABILITY_A, CAPABILITY_A]), expected)
    with pytest.raises(GrowthPathScopeError):
        validate_capability_scope(plan_with_ids([CAPABILITY_A, CAPABILITY_B, CAPABILITY_C]), expected)
```

- [ ] **Step 2: Run the tests and confirm RED**

```bash
uv run pytest tests/test_growth_schemas.py -q
```

Expected: FAIL because the Growth schemas and semantic validator do not exist.

- [ ] **Step 3: Implement strict LLM and API schemas**

Define in `growth/schemas.py`:

- `GrowthStageLLM` with `stage_no`, `title`, `objective`, `capability_ids`, `estimated_weeks`, `actions`, `completion_criteria`;
- `GrowthPlanLLM` with `schema_version`, `summary`, `stages`, `final_project`;
- `GrowthCapabilityRead`, `GrowthStageRead`, `GrowthPlanRead`, `GrowthSourceRead`, `GrowthPathRead`;
- `GrowthPathCreateResponse` with `reused` and `growth_path`;
- `GrowthPathScopeError` and `validate_capability_scope()`.

All Pydantic models use `ConfigDict(extra="forbid")`. `GrowthPlanLLM` uses `Literal["growth_path_v1"]`; stage arrays and strings use the exact limits from the design document. The semantic validator must flatten stage Capability IDs, require exact set equality against the missing required ID set, reject duplicate IDs, and require stage numbers to equal `1..len(stages)`.

- [ ] **Step 4: Run schema tests GREEN**

```bash
uv run pytest tests/test_growth_schemas.py -q
uv run ruff check app/growth/schemas.py tests/test_growth_schemas.py
```

- [ ] **Step 5: Commit schema behavior**

```bash
git add backend/app/growth/__init__.py backend/app/growth/schemas.py backend/tests/test_growth_schemas.py
git commit -m "feat: add growth path schemas"
```

## Task 3: Add the immutable Growth Path table

**Files:**

- Create: `backend/app/growth/models.py`
- Create: `backend/alembic/versions/0012_create_growth_paths.py`
- Modify: `backend/alembic/env.py`
- Test: `backend/tests/test_growth_database_constraints.py`

- [ ] **Step 1: Write failing database constraint tests**

Add tests that insert a valid row and then assert failures for the natural duplicate, missing composite Match Result, and non-object JSON values:

```python
async def test_growth_path_natural_key_is_unique(db_session, matching_context):
    first = build_growth_path(matching_context)
    db_session.add(first)
    await db_session.flush()
    db_session.add(build_growth_path(matching_context))
    with pytest.raises(IntegrityError):
        await db_session.flush()
```

- [ ] **Step 2: Run the constraint test and verify RED**

```bash
uv run pytest tests/test_growth_database_constraints.py -q
```

Expected: FAIL because `GrowthPath` and revision `0012` do not exist.

- [ ] **Step 3: Implement the ORM model and migration**

`GrowthPath` must contain:

```python
class GrowthPath(CreatedAtMixin, Base):
    __tablename__ = "growth_paths"
    __table_args__ = (
        ForeignKeyConstraint(
            ["match_run_id", "job_role_id"],
            ["match_results.match_run_id", "match_results.job_role_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "match_run_id", "job_role_id", "prompt_version",
            name="uq_growth_paths_match_role_prompt",
        ),
        CheckConstraint("jsonb_typeof(source_snapshot) = 'object'", name="source_object"),
        CheckConstraint("jsonb_typeof(path_payload) = 'object'", name="path_object"),
        CheckConstraint("jsonb_typeof(generation_metadata) = 'object'", name="metadata_object"),
    )
```

The primary key is `id`; the composite foreign key preserves the invariant that a path can only be attached to an existing role result from the same Match Run. The Alembic revision must create and drop the table without data backfill.

- [ ] **Step 4: Run migration and constraint tests GREEN**

```bash
uv run pytest tests/test_growth_database_constraints.py -q
alembic upgrade head
alembic downgrade 0011
alembic upgrade head
```

Expected: tests pass and the database reaches revision `0012` after the round trip.

- [ ] **Step 5: Commit the database boundary**

```bash
git add backend/app/growth/models.py backend/alembic/env.py backend/alembic/versions/0012_create_growth_paths.py backend/tests/test_growth_database_constraints.py
git commit -m "feat: persist growth paths"
```

## Task 4: Expose a shared visible Match Result record

**Files:**

- Modify: `backend/app/matching/service.py`
- Test: `backend/tests/test_matching_service.py`

- [ ] **Step 1: Write the failing helper test**

Add a test proving the shared helper returns the same visible Match Run and Match Result for the owner, returns the record for Admin, and hides another Applicant’s record as 404.

- [ ] **Step 2: Run the focused test and verify RED**

```bash
uv run pytest tests/test_matching_service.py -q -k visible_match_result
```

Expected: FAIL because the public helper does not exist.

- [ ] **Step 3: Implement and reuse the helper**

Add:

```python
async def get_visible_match_result_record(
    db: AsyncSession,
    actor: User,
    match_run_id: UUID,
    job_role_id: UUID,
) -> tuple[MatchRun, MatchResult]:
    run_row = await _get_visible_match_run_row(db, actor, match_run_id)
    result = await db.scalar(
        select(MatchResult).where(
            MatchResult.match_run_id == match_run_id,
            MatchResult.job_role_id == job_role_id,
        )
    )
    if result is None:
        raise APIError(404, "MATCH_RESULT_NOT_FOUND", "岗位匹配结果不存在")
    return run_row[0], result
```

Refactor `get_match_result_detail()` to call this helper so Growth and existing matching details use one ownership rule.

- [ ] **Step 4: Run matching regression tests GREEN**

```bash
uv run pytest tests/test_matching_service.py tests/test_matching_api.py -q
```

- [ ] **Step 5: Commit the shared visibility boundary**

```bash
git add backend/app/matching/service.py backend/tests/test_matching_service.py
git commit -m "refactor: share match result visibility"
```

## Task 5: Add the Growth Responses prompt adapter

**Files:**

- Create: `backend/app/growth/llm.py`
- Test: `backend/tests/test_growth_llm.py`

- [ ] **Step 1: Write the failing request and parsing tests**

Assert the adapter calls the shared client with `growth_path_v1`, does not include resume text or evidence quotes, and returns a typed `GrowthPlanLLM`:

```python
async def test_growth_prompt_contains_only_structured_match_context(monkeypatch):
    captured = {}

    async def fake_generate(**kwargs):
        captured.update(kwargs)
        return StructuredResponseResult(
            payload=valid_growth_plan(),
            response_id="resp_test",
            returned_model="test-model",
            status="completed",
            usage={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
            provider_attempts=1,
            response_sha256="hash",
        )

    result = await generate_growth_path(
        http=object(),
        url="https://provider.test/v1/responses",
        api_key="secret",
        model="test-model",
        growth_path_id=uuid4(),
        match_run_id=uuid4(),
        job_role_id=uuid4(),
        context={"missing_required_capabilities": []},
        client_factory=fake_generate,
    )

    assert result.payload.schema_version == "growth_path_v1"
    assert "evidence_quote" not in json.dumps(captured["input_text"])
```

- [ ] **Step 2: Run and verify RED**

```bash
uv run pytest tests/test_growth_llm.py -q
```

Expected: FAIL because the Growth prompt adapter does not exist.

- [ ] **Step 3: Implement the minimal adapter**

`growth/llm.py` must:

- define `PROMPT_VERSION = "growth_path_v1"`;
- define fixed Chinese instructions from the design;
- serialize only the sanitized context with `json.dumps(..., ensure_ascii=False)`;
- call `StructuredResponsesClient.generate()` with `GrowthPlanLLM`;
- use the existing configured Responses URL, API key and model;
- return the shared `StructuredResponseResult[GrowthPlanLLM]`.

Do not add web tools or a second provider client.

- [ ] **Step 4: Run the adapter tests GREEN**

```bash
uv run pytest tests/test_growth_llm.py -q
uv run ruff check app/growth/llm.py tests/test_growth_llm.py
```

- [ ] **Step 5: Commit the prompt adapter**

```bash
git add backend/app/growth/llm.py backend/tests/test_growth_llm.py
git commit -m "feat: add growth path responses prompt"
```

## Task 6: Implement Growth Service create/reuse and persistence

**Files:**

- Create: `backend/app/growth/service.py`
- Modify: `backend/app/growth/schemas.py`
- Test: `backend/tests/test_growth_service.py`
- Test: `backend/tests/matching_fixtures.py`

- [ ] **Step 1: Write the failing service tests**

Cover these behaviors with a fake provider function, not a real network call:

```python
async def test_create_growth_path_uses_required_gaps_and_reuses_without_provider(
    db_session,
    matching_context,
):
    calls = []

    async def provider(**kwargs):
        calls.append(kwargs)
        return valid_provider_result_for(matching_context)

    created = await create_or_reuse_growth_path(
        db_session,
        matching_context.applicant,
        matching_context.match_run.id,
        matching_context.job_role.id,
        provider=provider,
    )
    reused = await create_or_reuse_growth_path(
        db_session,
        matching_context.applicant,
        matching_context.match_run.id,
        matching_context.job_role.id,
        provider=provider,
    )

    assert created.reused is False
    assert reused.reused is True
    assert len(calls) == 1
```

Also test no required gaps, HR denial, Applicant ownership hiding, scope mismatch, provider failure rollback, and Admin actor audit.

- [ ] **Step 2: Run and verify RED**

```bash
uv run pytest tests/test_growth_service.py -q
```

Expected: FAIL because the service and persistence path do not exist.

- [ ] **Step 3: Implement the service flow**

Implement these functions:

```python
async def create_or_reuse_growth_path(
    db: AsyncSession,
    actor: User,
    match_run_id: UUID,
    job_role_id: UUID,
    *,
    request_id: str | None = None,
    ip_address: str | None = None,
    provider: GrowthProvider | None = None,
) -> GrowthPathResult:
    ...


async def get_growth_path(
    db: AsyncSession,
    actor: User,
    match_run_id: UUID,
    job_role_id: UUID,
) -> GrowthPathRead:
    ...
```

The implementation must:

1. call `get_visible_match_result_record()`;
2. extract and sanitize required missing capabilities;
3. return `GROWTH_PATH_NOT_REQUIRED` before provider configuration or network access when the set is empty;
4. query the natural key;
5. load the same `LLM_RESPONSES_URL`, `LLM_API_KEY`, and `LLM_MODEL` settings used by Resume;
6. commit/close the read transaction before the provider call;
7. validate the typed plan and exact Capability scope;
8. hydrate Capability snapshots from the source map;
9. calculate `total_estimated_weeks` in Python;
10. insert `GrowthPath`, audit creation, commit, and return;
11. on unique conflict rollback and load the winner as reuse;
12. on provider or semantic failure rollback and raise a stable `APIError` without a row.

The service must never return or persist raw Resume evidence. `source_snapshot` and API source fields contain only standard Capability and role facts.

- [ ] **Step 4: Run service tests GREEN**

```bash
uv run pytest tests/test_growth_service.py -q
```

- [ ] **Step 5: Run related regression tests**

```bash
uv run pytest tests/test_matching_service.py tests/test_matching_api.py tests/test_resume_llm.py -q
```

- [ ] **Step 6: Commit the service**

```bash
git add backend/app/growth/service.py backend/app/growth/schemas.py backend/tests/test_growth_service.py backend/tests/matching_fixtures.py
git commit -m "feat: generate and persist growth paths"
```

## Task 7: Expose the nested Growth Path API

**Files:**

- Create: `backend/app/growth/router.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/test_growth_api.py`

- [ ] **Step 1: Write failing API tests**

Add tests for:

```python
response = await client.post(
    f"/api/v1/job-recommendations/{run_id}/job-roles/{job_role_id}/growth-path",
    headers={"X-CSRF-Token": csrf},
)
assert response.status_code == 200
assert response.json()["data"]["reused"] is False
```

Then assert the second POST is `reused=true`, GET returns the same ID, missing CSRF is 403, another Applicant is 404, Admin succeeds, HR gets 403, and no-gap is 409.

- [ ] **Step 2: Run and verify RED**

```bash
uv run pytest tests/test_growth_api.py -q
```

Expected: FAIL because the nested router is not registered.

- [ ] **Step 3: Implement the router**

Register an `APIRouter` with prefix `/job-recommendations` and add:

```python
@router.post(
    "/{match_run_id}/job-roles/{job_role_id}/growth-path",
)
async def create_growth_path(..., _csrf: CSRF) -> dict:
    ...


@router.get(
    "/{match_run_id}/job-roles/{job_role_id}/growth-path",
)
async def read_growth_path(...) -> dict:
    ...
```

POST passes request ID and client IP into the service, returns `{"data": {"reused": ..., "growth_path": ...}}`, and GET returns `{"data": growth_path}`. Do not accept a request body or query parameters.

- [ ] **Step 4: Run API tests GREEN**

```bash
uv run pytest tests/test_growth_api.py -q
uv run ruff check app/growth/router.py app/api/router.py tests/test_growth_api.py
```

- [ ] **Step 5: Commit the API**

```bash
git add backend/app/growth/router.py backend/app/api/router.py backend/tests/test_growth_api.py
git commit -m "feat: expose growth path api"
```

## Task 8: Document and run the complete verification gate

**Files:**

- Modify: `README.md`
- Test: `backend/tests/test_health.py` only if the route count/version smoke test requires an explicit update

- [ ] **Step 1: Add a concise README section**

Document the two endpoints, required configured LLM settings, source anchoring, `GROWTH_PATH_NOT_REQUIRED`, and the fact that the endpoint generates a full path for all missing required skills. Do not add a fake generated output or real credentials.

- [ ] **Step 2: Verify the README and route contract**

```bash
rg -n "growth-path|成长路径|growth_path_v1|GROWTH_PATH_NOT_REQUIRED" README.md backend/app backend/tests
```

- [ ] **Step 3: Run the focused suite**

```bash
uv run pytest tests/test_responses_client.py tests/test_growth_schemas.py tests/test_growth_llm.py tests/test_growth_database_constraints.py tests/test_growth_service.py tests/test_growth_api.py -q
```

Expected: all focused tests pass.

- [ ] **Step 4: Run the full quality gate**

```bash
uv run pytest -q
uv run ruff check .
docker compose config -q
docker compose build api
```

Expected: pytest exits 0, Ruff reports no errors, Compose config exits 0, and the API image builds successfully.

- [ ] **Step 5: Verify Alembic and OpenAPI**

```bash
alembic upgrade head
alembic downgrade 0011
alembic upgrade head
uv run python -c 'from app.main import app; assert "/api/v1/job-recommendations/{match_run_id}/job-roles/{job_role_id}/growth-path" in app.openapi()["paths"]'
git diff --check
```

- [ ] **Step 6: Inspect the final scope and commit**

```bash
git status --short --branch
git diff --stat HEAD~8..HEAD
git diff --check
git add README.md
git commit -m "docs: document applicant growth paths"
```

Stage only the README in this step. Never stage the pre-existing `docs/superpowers/reports/` directory unless the user explicitly asks to commit that report.
