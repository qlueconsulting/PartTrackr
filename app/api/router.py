from fastapi import APIRouter
from app.api.endpoints.scores import router as scores_router
from app.api.endpoints.stems import router as stems_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(scores_router)
api_router.include_router(stems_router)
