"""
TaskFlow Pro - FastAPI Application Entry Point
==============================================
Main application module with route registration and middleware setup.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
import structlog

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import engine
from app.core.logging import configure_logging
from app.core.metrics import setup_metrics
from app.middleware.error_handler import error_handler_middleware
from app.middleware.request_logging import RequestLoggingMiddleware

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown events."""
    # Startup
    configure_logging()
    logger.info(
        "application_startup",
        app_name=settings.PROJECT_NAME,
        version=settings.VERSION,
        environment=settings.ENVIRONMENT
    )
    
    # Create database tables (in production, use Alembic migrations)
    # from app.models import Base
    # Base.metadata.create_all(bind=engine)
    
    yield
    
    # Shutdown
    logger.info("application_shutdown")
    await engine.dispose()


def create_application() -> FastAPI:
    """Application factory pattern for creating FastAPI instance."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description="TaskFlow Pro - Online Task Management API",
        version=settings.VERSION,
        docs_url="/api/docs" if settings.ENVIRONMENT != "production" else None,
        redoc_url="/api/redoc" if settings.ENVIRONMENT != "production" else None,
        openapi_url="/api/openapi.json" if settings.ENVIRONMENT != "production" else None,
        lifespan=lifespan
    )
    
    # Middleware configuration (order matters)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(error_handler_middleware)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Setup metrics
    setup_metrics(app)
    
    # Include API routes
    app.include_router(api_router, prefix=settings.API_V1_STR)
    
    # Health check endpoints
    @app.get("/health", tags=["Health"])
    async def health_check():
        """Liveness probe endpoint."""
        return {"status": "healthy", "version": settings.VERSION}
    
    @app.get("/ready", tags=["Health"])
    async def readiness_check():
        """Readiness probe endpoint - checks database connectivity."""
        from sqlalchemy import text
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return {
                "status": "ready",
                "checks": {
                    "database": "connected"
                }
            }
        except Exception as e:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "checks": {
                        "database": f"disconnected: {str(e)}"
                    }
                }
            )
    
    return app


app = create_application()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.ENVIRONMENT == "development",
        workers=1 if settings.ENVIRONMENT == "development" else 4
    )