from fastapi import APIRouter

from app.api.dependencies import DB, Admin
from app.core.errors import APIError
from app.system import service

health_router = APIRouter(prefix="/health", tags=["system"])
admin_router = APIRouter(prefix="/admin/system", tags=["admin-system"])
REQUIRED_DEPENDENCIES = {"postgresql", "redis", "neo4j", "file_volume"}


@health_router.get("/ready")
async def ready() -> dict:
    statuses = await service.probe_dependencies()
    public_statuses = {name: value.status for name, value in statuses.items()}
    if any(public_statuses[name] == "down" for name in REQUIRED_DEPENDENCIES):
        raise APIError(
            503,
            "DEPENDENCY_UNAVAILABLE",
            "必需依赖暂不可用",
            {"dependencies": public_statuses},
        )
    return {"status": "ready", "dependencies": public_statuses}


@admin_router.get("/dependencies")
async def dependencies(db: DB, _admin: Admin) -> dict:
    return {"data": await service.dependency_diagnostics(db)}


@admin_router.get("/versions")
async def versions(db: DB, _admin: Admin) -> dict:
    return {"data": await service.system_versions(db)}
