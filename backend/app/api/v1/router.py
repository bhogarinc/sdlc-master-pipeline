"""API v1 router - aggregates all endpoint routers"""
from fastapi import APIRouter

from app.api.v1.endpoints import auth, users, tasks, teams, notifications, websocket

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["Tasks"])
api_router.include_router(teams.router, prefix="/teams", tags=["Teams"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
api_router.include_router(websocket.router, prefix="/ws", tags=["WebSocket"])
