"""API routes package."""
from src.api.routes.auth import router as auth_router
from src.api.routes.tasks import router as tasks_router
from src.api.routes.teams import router as teams_router

__all__ = ["auth_router", "tasks_router", "teams_router"]
