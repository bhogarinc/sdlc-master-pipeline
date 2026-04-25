"""API layer."""

from fastapi import APIRouter

from .routes import auth, tasks, teams, users, websocket

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(teams.router, prefix="/teams", tags=["Teams"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["Tasks"])

__all__ = ["api_router"]
