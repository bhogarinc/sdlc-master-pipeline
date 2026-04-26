"""Global error handling middleware."""
import logging
import traceback
from typing import Any, Dict

from fastapi import Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class APIError(Exception):
    """Custom API error with status code."""
    
    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Dict[str, Any] = None
    ):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """Handle custom API errors."""
    logger.warning(f"API error: {exc.message}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.status_code,
                "message": exc.message,
                "details": exc.details
            }
        }
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle Pydantic validation errors."""
    from fastapi.exceptions import RequestValidationError
    
    if isinstance(exc, RequestValidationError):
        errors = []
        for error in exc.errors():
            errors.append({
                "field": ".".join(str(loc) for loc in error["loc"]),
                "message": error["msg"],
                "type": error["type"]
            })
        
        logger.warning(f"Validation error: {errors}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": 422,
                    "message": "Validation error",
                    "details": {"errors": errors}
                }
            }
        )
    
    return await generic_exception_handler(request, exc)


async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """Handle database errors."""
    if isinstance(exc, IntegrityError):
        logger.warning(f"Database integrity error: {exc}")
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": {
                    "code": 409,
                    "message": "Resource conflict",
                    "details": {"reason": "Duplicate or conflicting data"}
                }
            }
        )
    
    logger.error(f"Database error: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": 500,
                "message": "Database error",
                "details": {} if settings.is_production else {"error": str(exc)}
            }
        }
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle HTTP exceptions."""
    from fastapi import HTTPException
    
    if isinstance(exc, HTTPException):
        content = {
            "error": {
                "code": exc.status_code,
                "message": exc.detail if isinstance(exc.detail, str) else "Error",
                "details": {} if isinstance(exc.detail, str) else exc.detail
            }
        }
        
        if exc.headers:
            return JSONResponse(
                status_code=exc.status_code,
                content=content,
                headers=exc.headers
            )
        
        return JSONResponse(
            status_code=exc.status_code,
            content=content
        )
    
    return await generic_exception_handler(request, exc)


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle all unhandled exceptions."""
    error_id = id(exc)
    
    logger.error(
        f"Unhandled exception [{error_id}]: {exc}\n"
        f"Traceback: {traceback.format_exc()}"
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": 500,
                "message": "Internal server error",
                "details": {
                    "error_id": error_id
                } if not settings.is_production else {}
            }
        }
    )


def setup_error_handlers(app):
    """Register all error handlers with FastAPI app."""
    from fastapi.exceptions import RequestValidationError
    from fastapi import HTTPException
    from sqlalchemy.exc import SQLAlchemyError
    
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(SQLAlchemyError, sqlalchemy_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
    
    logger.info("Error handlers registered")
