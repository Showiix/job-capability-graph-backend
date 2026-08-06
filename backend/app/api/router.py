from fastapi import APIRouter

from app.auth.admin_router import router as admin_users_router
from app.auth.router import router as auth_router
from app.files.router import router as files_router
from app.imports.router import router as imports_router
from app.processing.router import router as processing_router
from app.system.router import admin_router as admin_system_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(admin_users_router)
api_router.include_router(files_router)
api_router.include_router(imports_router)
api_router.include_router(processing_router)
api_router.include_router(admin_system_router)
