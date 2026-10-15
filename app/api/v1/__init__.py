from fastapi import APIRouter
from app.api.v1.scores import router as scores_router

api_router = APIRouter()
api_router.include_router(scores_router)
