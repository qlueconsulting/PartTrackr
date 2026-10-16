from fastapi import APIRouter
from app.api.v1.scores import router as scores_router
from app.api.v1.mcp import router as mcp_router

api_router = APIRouter()
api_router.include_router(scores_router)
api_router.include_router(mcp_router, prefix="/mcp", tags=["MCP & AI Engine"])
