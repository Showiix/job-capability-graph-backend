from fastapi import APIRouter

from app.auth.admin_router import router as admin_users_router
from app.auth.router import router as auth_router
from app.catalog.router import router as catalog_router
from app.discovery.router import router as discovery_router
from app.files.router import router as files_router
from app.graph.router import read_router as graph_read_router
from app.graph.router import router as graph_router
from app.growth.router import router as growth_router
from app.imports.router import router as imports_router
from app.matching.router import router as matching_router
from app.processing.router import router as processing_router
from app.recruitment.router import router as recruitment_router
from app.resumes.router import router as resumes_router
from app.reviews.router import router as reviews_router
from app.system.router import admin_router as admin_system_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(admin_users_router)
api_router.include_router(catalog_router)
api_router.include_router(discovery_router)
api_router.include_router(files_router)
api_router.include_router(graph_router)
api_router.include_router(graph_read_router)
api_router.include_router(growth_router)
api_router.include_router(imports_router)
api_router.include_router(matching_router)
api_router.include_router(processing_router)
api_router.include_router(recruitment_router)
api_router.include_router(resumes_router)
api_router.include_router(reviews_router)
api_router.include_router(admin_system_router)
