import csv
import json
import re
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
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
    JobRoleAlias,
)
from app.catalog.schemas import CatalogImportResponse
from app.core.config import get_settings
from app.core.errors import APIError
from app.files.models import StoredFile
from app.infrastructure.file_storage import FileSizeLimitExceeded, FileStorage

ALLOWED_EXTENSIONS = {"csv", "json", "tsv", "txt"}
MODEL_SOURCE_TYPES = {"model", "llm", "algorithm"}
VALID_SOURCE_TYPES = MODEL_SOURCE_TYPES | {"manual", "import"}
MAX_CATALOG_FILE_BYTES = get_settings().max_import_file_bytes
storage = FileStorage(get_settings().file_storage_root)


async def create_catalog_import(
    db: AsyncSession,
    actor: User,
    upload: UploadFile,
    *,
    import_type: str,
    schema_version: str,
    mode: str,
    request_id: str,
    ip_address: str | None,
) -> CatalogImportResponse:
    import_type = import_type.strip().lower()
    mode = mode.strip().lower()
    if import_type not in {"capability", "job_role"}:
        raise APIError(422, "CATALOG_IMPORT_TYPE_UNSUPPORTED", "不支持的目录导入类型")
    if mode not in {"validate_only", "apply"}:
        raise APIError(422, "CATALOG_IMPORT_MODE_UNSUPPORTED", "不支持的目录导入模式")
    if not schema_version.strip():
        raise APIError(
            422,
            "CATALOG_SCHEMA_VERSION_REQUIRED",
            "目录 schema_version 不能为空",
        )

    extension = Path(upload.filename or "").suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise APIError(422, "CATALOG_FILE_TYPE_UNSUPPORTED", "目录文件格式不受支持")

    file_id = uuid4()
    import_id = uuid4()
    storage_key = f"catalog/{file_id}.{extension}"
    try:
        size_bytes, sha256 = await storage.save_stream(
            upload,
            storage_key,
            MAX_CATALOG_FILE_BYTES,
        )
    except FileSizeLimitExceeded:
        raise APIError(413, "CATALOG_FILE_TOO_LARGE", "目录文件超过大小限制") from None
    except ValueError as error:
        if str(error) == "empty file":
            raise APIError(422, "CATALOG_EMPTY_FILE", "目录文件不能为空") from None
        raise

    stored_file = StoredFile(
        id=file_id,
        uploaded_by_user_id=actor.id,
        original_name=upload.filename or f"catalog.{extension}",
        storage_key=storage_key,
        media_type=upload.content_type or "application/octet-stream",
        extension=extension,
        size_bytes=size_bytes,
        sha256=sha256,
        category="catalog",
        scan_status="not_required",
        status="attached",
    )
    catalog_import = CatalogImport(
        id=import_id,
        uploaded_by_user_id=actor.id,
        file_id=file_id,
        import_type=import_type,
        schema_version=schema_version.strip(),
        mode=mode,
        status="processing",
        summary={},
    )
    db.add(stored_file)
    await db.flush()
    db.add(catalog_import)
    await db.flush()

    try:
        rows = _parse_rows(storage.resolve(storage_key), extension)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, csv.Error) as error:
        catalog_import.status = "failed"
        catalog_import.summary = {"valid_rows": 0, "error_rows": 1, "total_rows": 1}
        db.add(
            CatalogImportRow(
                id=uuid4(),
                catalog_import_id=import_id,
                row_number=1,
                row_status="error",
                payload={"filename": upload.filename or ""},
                error_code="CATALOG_FILE_INVALID",
                error_message=str(error) or "目录文件无法解析",
            )
        )
        record_audit(
            db,
            action="catalog.import",
            resource_type="catalog_import",
            resource_id=import_id,
            actor_user_id=actor.id,
            outcome="failed",
            request_id=request_id,
            ip_address=ip_address,
        )
        await db.commit()
        return CatalogImportResponse(
            import_id=import_id,
            status="failed",
            summary=catalog_import.summary,
        )

    validated = await _validate_rows(db, rows, import_type)
    valid_rows = [value for value in validated if value["row_status"] == "valid"]
    error_rows = [value for value in validated if value["row_status"] == "error"]
    summary = {
        "total_rows": len(validated),
        "valid_rows": len(valid_rows),
        "error_rows": len(error_rows),
    }
    for value in validated:
        db.add(
            CatalogImportRow(
                id=uuid4(),
                catalog_import_id=import_id,
                row_number=value["row_number"],
                row_status=value["row_status"],
                payload=value["payload"],
                error_code=value.get("error_code"),
                error_message=value.get("error_message"),
            )
        )

    version_id: UUID | None = None
    if mode == "validate_only":
        catalog_import.status = "validated"
    elif valid_rows:
        version_id = await _apply_rows(
            db,
            actor,
            valid_rows,
            import_type=import_type,
            summary=summary,
        )
        catalog_import.status = "applied"
    else:
        catalog_import.status = "failed"
    catalog_import.summary = summary
    record_audit(
        db,
        action="catalog.import",
        resource_type="catalog_import",
        resource_id=import_id,
        actor_user_id=actor.id,
        outcome="success" if catalog_import.status != "failed" else "failed",
        request_id=request_id,
        ip_address=ip_address,
        metadata={"mode": mode, "import_type": import_type, **summary},
    )
    # ponytail: one transaction handles internal seeds; chunk after profiling.
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        _remove_file(storage_key)
        raise
    return CatalogImportResponse(
        import_id=import_id,
        status=catalog_import.status,
        summary=summary,
        version_id=version_id,
    )


def _parse_rows(path: Path, extension: str) -> list[dict[str, Any]]:
    text = _decode(path.read_bytes())
    if extension == "json":
        value = json.loads(text)
        if isinstance(value, dict):
            value = value.get("rows")
        if not isinstance(value, list) or not all(
            isinstance(row, dict) for row in value
        ):
            raise ValueError("JSON 须为对象数组")
        return value
    delimiter = "\t" if extension in {"tsv", "txt"} else ","
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValueError("文件缺少表头")
    return [
        {str(key).strip().lstrip("\ufeff"): value for key, value in row.items()}
        for row in reader
    ]


def _decode(value: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("catalog", value, 0, len(value), "unsupported encoding")


async def _validate_rows(
    db: AsyncSession,
    rows: list[dict[str, Any]],
    import_type: str,
) -> list[dict[str, Any]]:
    domains = (await db.scalars(select(Domain))).all()
    domains_by_code = {domain.code.casefold(): domain for domain in domains}
    domain_names = {
        str(row.get("domain_code", "")).strip().casefold(): str(
            row.get("domain_name", "")
        ).strip()
        for row in rows
        if isinstance(row, dict) and row.get("domain_code") and row.get("domain_name")
    }
    if import_type == "capability":
        entities = (await db.scalars(select(Capability))).all()
        aliases = (await db.scalars(select(CapabilityAlias))).all()
    else:
        entities = (await db.scalars(select(JobRole))).all()
        aliases = (await db.scalars(select(JobRoleAlias))).all()
    domain_codes_by_id = {domain.id: domain.code.casefold() for domain in domains}
    entity_keys = {
        (domain_codes_by_id[entity.domain_id], entity.canonical_name.casefold())
        for entity in entities
    }
    alias_targets = {alias.alias.casefold() for alias in aliases}
    seen_entities: set[tuple[str, str]] = set()
    seen_aliases: dict[str, str] = {}
    result: list[dict[str, Any]] = []
    for row_number, payload in enumerate(rows, start=1):
        if not isinstance(payload, dict):
            result.append(
                _error_row(row_number, payload, "ROW_NOT_OBJECT", "行必须是对象")
            )
            continue
        domain_code = str(payload.get("domain_code", "")).strip().casefold()
        canonical_name = str(payload.get("canonical_name", "")).strip()
        source_type = str(payload.get("source_type", "manual")).strip().lower()
        error = None
        if not domain_code:
            error = ("DOMAIN_CODE_REQUIRED", "domain_code 不能为空")
        elif not canonical_name:
            error = ("CANONICAL_NAME_REQUIRED", "canonical_name 不能为空")
        elif source_type not in VALID_SOURCE_TYPES:
            error = ("SOURCE_TYPE_INVALID", "source_type 不受支持")
        elif domain_code not in domains_by_code and domain_code not in domain_names:
            error = ("DOMAIN_REQUIRED", "未知 domain_code 必须同时提供 domain_name")
        key = (domain_code, canonical_name.casefold())
        if error is None and (key in entity_keys or key in seen_entities):
            error = ("DUPLICATE_CANONICAL_NAME", "目录中 canonical_name 重复")

        aliases_value = payload.get("aliases", [])
        aliases_list = _aliases(aliases_value)
        if aliases_list is None and error is None:
            error = ("ALIASES_INVALID", "aliases 必须是字符串数组")
            aliases_list = []
        alias_target = f"{domain_code}:{canonical_name.casefold()}"
        if error is None:
            for alias in aliases_list:
                alias_key = alias.casefold()
                if (
                    alias_key in seen_aliases
                    and seen_aliases[alias_key] != alias_target
                ):
                    error = ("ALIAS_CONFLICT", "alias 指向多个目录项")
                    break
                if alias_key in alias_targets:
                    error = ("ALIAS_CONFLICT", "alias 已被其他目录项使用")
                    break
        if error is not None:
            result.append(
                _error_row(row_number, payload, error[0], error[1])
            )
            continue
        seen_entities.add(key)
        for alias in aliases_list:
            seen_aliases[alias.casefold()] = alias_target
        result.append(
            {
                "row_number": row_number,
                "row_status": "valid",
                "payload": dict(payload),
                "domain_code": domain_code,
                "domain_name": str(
                    payload.get("domain_name")
                    or domain_names.get(domain_code)
                    or domain_code
                ),
                "canonical_name": canonical_name,
                "source_type": source_type,
                "aliases": aliases_list,
            }
        )
    return result


def _aliases(value: Any) -> list[str] | None:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,;|]", value) if item.strip()]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))
    return None


def _error_row(
    row_number: int,
    payload: Any,
    code: str,
    message: str,
) -> dict[str, Any]:
    return {
        "row_number": row_number,
        "row_status": "error",
        "payload": payload if isinstance(payload, dict) else {"value": payload},
        "error_code": code,
        "error_message": message,
    }


async def _apply_rows(
    db: AsyncSession,
    actor: User,
    rows: list[dict[str, Any]],
    *,
    import_type: str,
    summary: dict[str, int],
) -> UUID:
    version_no = (await db.scalar(select(func.max(CatalogVersion.version_no))) or 0) + 1
    version = CatalogVersion(
        id=uuid4(),
        version_no=version_no,
        status="draft",
        is_current=False,
        created_by_user_id=actor.id,
        summary=summary,
    )
    db.add(version)
    await db.flush()
    domains_by_code = {
        domain.code.casefold(): domain
        for domain in (await db.scalars(select(Domain))).all()
    }
    for row in rows:
        domain = domains_by_code.get(row["domain_code"])
        if domain is None:
            domain = Domain(
                id=uuid4(),
                code=row["domain_code"],
                name=row["domain_name"],
                status="active",
                sort_order=0,
            )
            db.add(domain)
            await db.flush()
            domains_by_code[row["domain_code"]] = domain
        requested_status = str(row["payload"].get("status", "candidate")).lower()
        status = (
            "candidate"
            if row["source_type"] in MODEL_SOURCE_TYPES
            else requested_status
            if requested_status in {"active", "candidate"}
            else "candidate"
        )
        if import_type == "capability":
            entity = Capability(
                id=uuid4(),
                domain_id=domain.id,
                canonical_name=row["canonical_name"],
                description=row["payload"].get("description"),
                skill_type=str(row["payload"].get("skill_type") or "other"),
                status=status,
                source_type=row["source_type"],
            )
            db.add(entity)
            await db.flush()
            for alias in row["aliases"]:
                db.add(
                    CapabilityAlias(
                        id=uuid4(),
                        capability_id=entity.id,
                        alias=alias,
                        status="active",
                    )
                )
            item = CatalogVersionItem(
                id=uuid4(),
                catalog_version_id=version.id,
                item_type="capability",
                capability_id=entity.id,
                change_type="added",
            )
        else:
            entity = JobRole(
                id=uuid4(),
                domain_id=domain.id,
                canonical_name=row["canonical_name"],
                description=row["payload"].get("description"),
                status=status,
                source_type=row["source_type"],
            )
            db.add(entity)
            await db.flush()
            for alias in row["aliases"]:
                db.add(
                    JobRoleAlias(
                        id=uuid4(),
                        job_role_id=entity.id,
                        alias=alias,
                        status="active",
                    )
                )
            item = CatalogVersionItem(
                id=uuid4(),
                catalog_version_id=version.id,
                item_type="job_role",
                job_role_id=entity.id,
                change_type="added",
            )
        db.add(item)
    await db.flush()
    return version.id


async def list_catalog_imports(db: AsyncSession) -> list[dict[str, Any]]:
    values = (
        await db.scalars(
            select(CatalogImport).order_by(
                CatalogImport.created_at.desc(), CatalogImport.id
            )
        )
    ).all()
    return [_import_data(value) for value in values]


async def get_catalog_import(db: AsyncSession, import_id: UUID) -> CatalogImport:
    value = await db.get(CatalogImport, import_id)
    if value is None:
        raise APIError(404, "RESOURCE_NOT_FOUND", "目录导入不存在")
    return value


def _import_data(value: CatalogImport) -> dict[str, Any]:
    return {
        "id": str(value.id),
        "file_id": str(value.file_id),
        "import_type": value.import_type,
        "schema_version": value.schema_version,
        "mode": value.mode,
        "status": value.status,
        "summary": value.summary,
        "created_at": value.created_at.isoformat(),
    }


async def list_versions(
    db: AsyncSession,
    *,
    include_drafts: bool,
    is_admin: bool,
) -> list[dict[str, Any]]:
    statement = select(CatalogVersion).order_by(
        CatalogVersion.version_no.desc(), CatalogVersion.id
    )
    if not (include_drafts and is_admin):
        statement = statement.where(CatalogVersion.status == "published")
    else:
        statement = statement.where(CatalogVersion.status != "archived")
    return [_version_data(value) for value in (await db.scalars(statement)).all()]


async def current_version(db: AsyncSession) -> dict[str, Any]:
    value = await db.scalar(
        select(CatalogVersion).where(
            CatalogVersion.status == "published",
            CatalogVersion.is_current.is_(True),
        )
    )
    if value is None:
        raise APIError(404, "CATALOG_VERSION_NOT_FOUND", "当前目录版本不存在")
    return _version_data(value)


async def list_domains(db: AsyncSession) -> list[dict[str, Any]]:
    values = (
        await db.scalars(
            select(Domain)
            .where(Domain.status == "active")
            .order_by(Domain.sort_order, Domain.code)
        )
    ).all()
    return [_domain_data(value) for value in values]


async def list_capabilities(
    db: AsyncSession,
    *,
    include_candidates: bool,
    is_admin: bool,
) -> list[dict[str, Any]]:
    statement = select(Capability, Domain).join(
        Domain, Domain.id == Capability.domain_id
    )
    if include_candidates and is_admin:
        statement = statement.where(Capability.status.in_({"active", "candidate"}))
    else:
        statement = (
            statement.join(
                CatalogVersionItem,
                CatalogVersionItem.capability_id == Capability.id,
            )
            .join(
                CatalogVersion,
                CatalogVersion.id == CatalogVersionItem.catalog_version_id,
            )
            .where(
                Capability.status == "active",
                CatalogVersion.status == "published",
                CatalogVersion.is_current.is_(True),
            )
        )
    values = (await db.execute(statement.order_by(Capability.canonical_name))).all()
    return [_capability_data(capability, domain) for capability, domain in values]


async def list_job_roles(
    db: AsyncSession,
    *,
    include_candidates: bool,
    is_admin: bool,
) -> list[dict[str, Any]]:
    statement = select(JobRole, Domain).join(Domain, Domain.id == JobRole.domain_id)
    if include_candidates and is_admin:
        statement = statement.where(JobRole.status.in_({"active", "candidate"}))
    else:
        statement = (
            statement.join(
                CatalogVersionItem,
                CatalogVersionItem.job_role_id == JobRole.id,
            )
            .join(
                CatalogVersion,
                CatalogVersion.id == CatalogVersionItem.catalog_version_id,
            )
            .where(
                JobRole.status == "active",
                CatalogVersion.status == "published",
                CatalogVersion.is_current.is_(True),
            )
        )
    values = (await db.execute(statement.order_by(JobRole.canonical_name))).all()
    return [_job_role_data(role, domain) for role, domain in values]


def _version_data(value: CatalogVersion) -> dict[str, Any]:
    return {
        "id": str(value.id),
        "version_no": value.version_no,
        "status": value.status,
        "is_current": value.is_current,
        "summary": value.summary,
        "created_at": value.created_at.isoformat(),
        "published_at": value.published_at.isoformat() if value.published_at else None,
    }


def _domain_data(value: Domain) -> dict[str, Any]:
    return {
        "id": str(value.id),
        "code": value.code,
        "name": value.name,
        "description": value.description,
        "status": value.status,
        "sort_order": value.sort_order,
    }


def _capability_data(value: Capability, domain: Domain) -> dict[str, Any]:
    return {
        "id": str(value.id),
        "domain_code": domain.code,
        "domain_name": domain.name,
        "canonical_name": value.canonical_name,
        "description": value.description,
        "skill_type": value.skill_type,
        "status": value.status,
        "source_type": value.source_type,
    }


def _job_role_data(value: JobRole, domain: Domain) -> dict[str, Any]:
    return {
        "id": str(value.id),
        "domain_code": domain.code,
        "domain_name": domain.name,
        "canonical_name": value.canonical_name,
        "description": value.description,
        "status": value.status,
        "source_type": value.source_type,
    }


def _remove_file(storage_key: str) -> None:
    try:
        storage.resolve(storage_key).unlink(missing_ok=True)
    except ValueError:
        return
