"""
TaskFlow Pro - API v1 Router
============================
Main router aggregating all API v1 endpoints.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, users, tasks, teams, notifications, boards, comments, attachments

api_router = APIRouter()

# Authentication endpoints
api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["Authentication"]
)

# User management endpoints
api_router.include_router(
    users.router,
    prefix="/users",
    tags=["Users"]
)

# Task management endpoints
api_router.include_router(
    tasks.router,
    prefix="/tasks",
    tags=["Tasks"]
)

# Team collaboration endpoints
api_router.include_router(
    teams.router,
    prefix="/teams",
    tags=["Teams"]
)

# Board management endpoints
api_router.include_router(
    boards.router,
    prefix="/boards",
    tags=["Boards"]
)

# Comment endpoints
api_router.include_router(
    comments.router,
    prefix="/comments",
    tags=["Comments"]
)

# Attachment endpoints
api_router.include_router(
    attachments.router,
    prefix="/attachments",
    tags=["Attachments"]
)

# Notification endpoints
api_router.include_router(
    notifications.router,
    prefix="/notifications",
    tags=["Notifications"]
)