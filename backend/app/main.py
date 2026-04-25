"""
TaskFlow Pro - FastAPI Application Entry Point
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
import time
import logging

from app.core.config import settings
from app.core.database import engine
from app.api.v1.router import api_router
from app.core.exceptions import TaskFlowException

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="TaskFlow Pro API",
    description="Online task management application with team collaboration",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response

@app.exception_handler(TaskFlowException)
async def taskflow_exception_handler(request: Request, exc: TaskFlowException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details
            }
        }
    )

app.include_router(api_router, prefix="/api/v1")

@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "healthy", "service": "taskflow-api"}

@app.get("/ready", tags=["Health"])
async def readiness_check():
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready", "checks": {"database": "connected"}}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "checks": {"database": "disconnected"}}
        )

@app.get("/metrics", tags=["Health"])
async def metrics():
    return {"http_requests_total": 0, "http_request_duration_seconds": 0.0, "active_connections": 0}

@app.on_event("startup")
async def startup_event():
    logger.info("Starting TaskFlow Pro API")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down TaskFlow Pro API")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
