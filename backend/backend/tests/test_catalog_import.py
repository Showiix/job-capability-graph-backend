import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import func, select

from app.auth.models import User
from app.catalog.models import (
    Capability,
    CapabilityAlias,
    CatalogImport,
    CatalogImportRow,
    CatalogVersion,
    CatalogVersionItem,
    Domain,
    JobRole,
)
from app.core.security import hash_password


@pytest_asyncio.fixture
async def catalog_admin(db_session) -> User:
    value = User(
        id=uuid4(),
        username="catalog_admin",
        username_normalized="catalog_admin",
        password_hash=hash_password("catalog-admin-password"),
        display_name="Catalog Admin",
        role="admin",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(value)
    await db_session.flush()
    return value


@pytest_asyncio.fixture
async def catalog_hr(db_session) -> User:
    value = User(
        id=uuid4(),
        username="catalog_hr",
        username_normalized="catalog_hr",
        password_hash=hash_password("catalog-hr-password"),
        display_name="Catalog HR",
        role="hr",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(value)
    await db_session.flush()
    return value


@pytest_asyncio.fixture
async def catalog_applicant(db_session) -> User:
    value = User(
        id=uuid4(),
        username="catalog_applicant",
        username_normalized="catalog_applicant",
        password_hash=hash_password("catalog-applicant-password"),
        display_name="Catalog Applicant",
        role="applicant",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(value)
    await db_session.flush()
    return value


async def _login(client, username: str, password: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"]


def _rows(*values: dict) -> bytes:
    return json.dumps(list(values), ensure_ascii=False).encode("utf-8")


async def _upload(client, csrf: str, content: bytes, *, mode: str = "validate_only"):
    return await client.post(
        "/api/v1/catalog/imports",
        data={
            "import_type": "capability",
            "schema_version": "catalog_v1",
            "mode": mode,
        },
        files={"file": ("catalog.json", content, "application/json")},
        headers={"X-CSRF-Token": csrf},
    )


async def _upload_role(client, csrf: str, content: bytes, *, mode: str = "apply"):
    return await client.post(
        "/api/v1/catalog/imports",
        data={
            "import_type": "job_role",
            "schema_version": "catalog_v1",
            "mode": mode,
        },
        files={"file": ("roles.json", content, "application/json")},
        headers={"X-CSRF-Token": csrf},
    )


async def test_validate_only_records_rows_without_writing_catalog(
    client,
    db_session,
    catalog_admin,
) -> None:
    csrf = await _login(client, "catalog_admin", "catalog-admin-password")
    response = await _upload(
        client,
        csrf,
        _rows(
            {
                "domain_code": "ai",
                "domain_name": "人工智能",
                "canonical_name": "RAG 评测",
                "description": "检索增强生成系统评测",
                "skill_type": "method",
                "source_type": "manual",
                "aliases": ["RAG Evaluation"],
            }
        ),
    )

    assert response.status_code == 202
    data = response.json()["data"]
    assert data["status"] == "validated"
    catalog_import = await db_session.get(CatalogImport, data["import_id"])
    assert catalog_import is not None
    assert catalog_import.summary["valid_rows"] == 1
    row_count = await db_session.scalar(
        select(func.count()).select_from(CatalogImportRow)
    )
    assert row_count == 1
    assert await db_session.scalar(select(func.count()).select_from(Domain)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Capability)) == 0
    version_count = await db_session.scalar(
        select(func.count()).select_from(CatalogVersion)
    )
    assert version_count == 0
    listing = await client.get("/api/v1/catalog/imports")
    detail = await client.get(f"/api/v1/catalog/imports/{data['import_id']}")
    assert listing.status_code == detail.status_code == 200
    assert listing.json()["data"][0]["id"] == data["import_id"]
    assert detail.json()["data"]["status"] == "validated"


async def test_apply_creates_draft_version_and_candidate_model_item(
    client,
    db_session,
    catalog_admin,
) -> None:
    csrf = await _login(client, "catalog_admin", "catalog-admin-password")
    response = await _upload(
        client,
        csrf,
        _rows(
            {
                "domain_code": "ai",
                "domain_name": "人工智能",
                "canonical_name": "RAG 评测",
                "skill_type": "method",
                "source_type": "model",
                "status": "active",
                "aliases": ["RAG Evaluation"],
            }
        ),
        mode="apply",
    )

    assert response.status_code == 202
    data = response.json()["data"]
    assert data["status"] == "applied"
    catalog_import = await db_session.get(CatalogImport, data["import_id"])
    version = await db_session.get(CatalogVersion, data["version_id"])
    capability = await db_session.scalar(select(Capability))
    alias = await db_session.scalar(select(CapabilityAlias))
    assert catalog_import is not None
    assert version is not None and version.status == "draft"
    assert capability is not None and capability.status == "candidate"
    assert alias is not None and alias.alias == "RAG Evaluation"
    item = await db_session.scalar(
        select(CatalogVersionItem).where(
            CatalogVersionItem.catalog_version_id == version.id
        )
    )
    assert item is not None and item.capability_id == capability.id


async def test_apply_continues_after_duplicate_and_invalid_rows(
    client,
    db_session,
    catalog_admin,
) -> None:
    csrf = await _login(client, "catalog_admin", "catalog-admin-password")
    response = await _upload(
        client,
        csrf,
        _rows(
            {
                "domain_code": "ai",
                "domain_name": "人工智能",
                "canonical_name": "Prompt Engineering",
                "skill_type": "method",
                "source_type": "manual",
            },
            {
                "domain_code": "ai",
                "canonical_name": "Prompt Engineering",
                "skill_type": "method",
                "source_type": "manual",
            },
            {
                "domain_code": "unknown",
                "canonical_name": "No Domain",
                "skill_type": "method",
                "source_type": "manual",
            },
        ),
        mode="apply",
    )

    assert response.status_code == 202
    data = response.json()["data"]
    assert data["status"] == "applied"
    assert data["summary"]["valid_rows"] == 1
    assert data["summary"]["error_rows"] == 2
    errors = (
        await db_session.scalars(
            select(CatalogImportRow).where(CatalogImportRow.row_status == "error")
        )
    ).all()
    assert {row.error_code for row in errors} == {
        "DUPLICATE_CANONICAL_NAME",
        "DOMAIN_REQUIRED",
    }
    assert await db_session.scalar(select(func.count()).select_from(Capability)) == 1


async def test_validate_tsv_and_reject_ambiguous_alias(
    client,
    db_session,
    catalog_admin,
) -> None:
    csrf = await _login(client, "catalog_admin", "catalog-admin-password")
    content = (
        "domain_code\tdomain_name\tcanonical_name\tskill_type\tsource_type\taliases\n"
        "ai\t人工智能\t检索增强生成\tmethod\tmanual\tRAG\n"
        "ai\t人工智能\t生成式检索\tmethod\tmanual\tRAG\n"
    ).encode()
    response = await client.post(
        "/api/v1/catalog/imports",
        data={
            "import_type": "capability",
            "schema_version": "catalog_v1",
            "mode": "validate_only",
        },
        files={"file": ("catalog.tsv", content, "text/tab-separated-values")},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 202
    assert response.json()["data"]["summary"] == {
        "total_rows": 2,
        "valid_rows": 1,
        "error_rows": 1,
    }
    error = await db_session.scalar(
        select(CatalogImportRow).where(CatalogImportRow.error_code == "ALIAS_CONFLICT")
    )
    assert error is not None and error.row_number == 2


async def test_apply_job_role_creates_role_version_item(
    client,
    db_session,
    catalog_admin,
) -> None:
    csrf = await _login(client, "catalog_admin", "catalog-admin-password")
    response = await _upload_role(
        client,
        csrf,
        _rows(
            {
                "domain_code": "ai",
                "domain_name": "人工智能",
                "canonical_name": "RAG 应用工程师",
                "source_type": "manual",
                "status": "active",
                "aliases": ["RAG Engineer"],
            }
        ),
    )

    assert response.status_code == 202
    role = await db_session.scalar(select(JobRole))
    assert role is not None and role.status == "active"
    item = await db_session.scalar(
        select(CatalogVersionItem).where(CatalogVersionItem.job_role_id == role.id)
    )
    assert item is not None and item.item_type == "job_role"
    roles = await client.get(
        "/api/v1/catalog/job-roles", params={"include_candidates": "true"}
    )
    assert roles.status_code == 200
    assert roles.json()["data"][0]["canonical_name"] == "RAG 应用工程师"


async def test_malformed_catalog_file_is_recorded_as_failed_import(
    client,
    db_session,
    catalog_admin,
) -> None:
    csrf = await _login(client, "catalog_admin", "catalog-admin-password")
    response = await _upload(client, csrf, b"{not-json")

    assert response.status_code == 202
    data = response.json()["data"]
    assert data["status"] == "failed"
    row = await db_session.scalar(
        select(CatalogImportRow).where(
            CatalogImportRow.catalog_import_id == data["import_id"]
        )
    )
    assert row is not None and row.error_code == "CATALOG_FILE_INVALID"


async def test_catalog_import_requires_admin(client, catalog_hr) -> None:
    csrf = await _login(client, "catalog_hr", "catalog-hr-password")
    response = await _upload(client, csrf, _rows({"canonical_name": "Python"}))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ROLE_NOT_ALLOWED"


async def test_authenticated_user_sees_only_published_and_active_catalog(
    client,
    db_session,
    catalog_admin,
    catalog_applicant,
) -> None:
    domain = Domain(
        id=uuid4(), code="ai_public", name="人工智能", status="active", sort_order=0
    )
    active = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="Python",
        skill_type="language",
        source_type="manual",
        status="active",
    )
    candidate = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="Future Skill",
        skill_type="method",
        source_type="model",
        status="candidate",
    )
    version = CatalogVersion(
        id=uuid4(),
        version_no=99,
        status="published",
        is_current=True,
        created_by_user_id=catalog_admin.id,
        summary={},
    )
    db_session.add_all([domain, version])
    await db_session.flush()
    db_session.add_all([active, candidate])
    await db_session.flush()
    db_session.add_all(
        [
            CatalogVersionItem(
                id=uuid4(),
                catalog_version_id=version.id,
                item_type="capability",
                capability_id=active.id,
                change_type="added",
            ),
            CatalogVersionItem(
                id=uuid4(),
                catalog_version_id=version.id,
                item_type="capability",
                capability_id=candidate.id,
                change_type="added",
            ),
        ]
    )
    await db_session.commit()

    await _login(client, "catalog_applicant", "catalog-applicant-password")
    versions = await client.get("/api/v1/catalog/versions")
    current = await client.get("/api/v1/catalog/versions/current")
    capabilities = await client.get("/api/v1/catalog/capabilities")

    assert versions.status_code == 200
    assert [value["status"] for value in versions.json()["data"]] == ["published"]
    assert current.status_code == 200
    assert current.json()["data"]["version_no"] == 99
    assert capabilities.status_code == 200
    assert [value["canonical_name"] for value in capabilities.json()["data"]] == [
        "Python"
    ]


async def test_admin_can_query_drafts_and_candidates(
    client,
    catalog_admin,
    db_session,
) -> None:
    csrf = await _login(client, "catalog_admin", "catalog-admin-password")
    await _upload(
        client,
        csrf,
        _rows(
            {
                "domain_code": "ai",
                "domain_name": "人工智能",
                "canonical_name": "LLM Ops",
                "skill_type": "method",
                "source_type": "llm",
            }
        ),
        mode="apply",
    )

    versions = await client.get(
        "/api/v1/catalog/versions", params={"include_drafts": "true"}
    )
    capabilities = await client.get(
        "/api/v1/catalog/capabilities", params={"include_candidates": "true"}
    )
    assert versions.status_code == 200
    assert versions.json()["data"][0]["status"] == "draft"
    assert capabilities.status_code == 200
    assert capabilities.json()["data"][0]["status"] == "candidate"
