"""TaskFlow Pro FastAPI Application Entry Point."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import auth, tasks, teams
from src.api.websocket import router as websocket_router
from src.config.database import close_db, init_db
from src.config.settings import get_settings
from src.middleware.error_handler import setup_error_handlers
from src.middleware.rate_limiter import RateLimitMiddleware

settings = get_settings()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    await init_db()
    yield
    # Shutdown
    logger.info(f"Shutting down {settings.APP_NAME}")
    await close_db()


def create_application() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="TaskFlow Pro - Modern Task Management API",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=settings.CORS_ALLOW_METHODS,
        allow_headers=settings.CORS_ALLOW_HEADERS,
    )
    
    # Rate limiting middleware
    app.add_middleware(RateLimitMiddleware)
    
    # Error handlers
    setup_error_handlers(app)
    
    # API routes
    api_prefix = "/api/v1"
    
    app.include_router(auth.router, prefix=f"{api_prefix}/auth")
    app.include_router(tasks.router, prefix=f"{api_prefix}")
    app.include_router(teams.router, prefix=f"{api_prefix}")
    
    # WebSocket routes
    app.include_router(websocket_router, prefix= api_prefix)
    
    return app


app = create_application()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT
    }


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "api": "/api/v1"
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "src.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=not settings.is_production,
        workers=1 if settings.DEBUG else settings.WORKERS
    )
