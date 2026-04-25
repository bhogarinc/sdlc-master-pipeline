"""Custom exception classes for the application."""

from typing import Any, Dict, List, Optional


class TaskFlowException(Exception):
    """Base exception for TaskFlow Pro."""
    
    def __init__(
        self,
        message: str,
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class AuthenticationError(TaskFlowException):
    """Raised when authentication fails."""
    
    def __init__(self, message: str = "Authentication failed", details: Optional[Dict] = None):
        super().__init__(message, status_code=401, details=details)


class AuthorizationError(TaskFlowException):
    """Raised when user lacks required permissions."""
    
    def __init__(self, message: str = "Insufficient permissions", details: Optional[Dict] = None):
        super().__init__(message, status_code=403, details=details)


class ValidationError(TaskFlowException):
    """Raised when request validation fails."""
    
    def __init__(self, message: str = "Validation error", errors: Optional[List[Dict]] = None):
        details = {"errors": errors or []}
        super().__init__(message, status_code=422, details=details)


class NotFoundError(TaskFlowException):
    """Raised when a requested resource is not found."""
    
    def __init__(self, resource: str, resource_id: Optional[str] = None):
        message = f"{resource} not found"
        if resource_id:
            message = f"{resource} with id '{resource_id}' not found"
        super().__init__(message, status_code=404)


class ConflictError(TaskFlowException):
    """Raised when there's a resource conflict."""
    
    def __init__(self, message: str = "Resource conflict", details: Optional[Dict] = None):
        super().__init__(message, status_code=409, details=details)


class RateLimitError(TaskFlowException):
    """Raised when rate limit is exceeded."""
    
    def __init__(self, message: str = "Rate limit exceeded", retry_after: int = 60):
        super().__init__(message, status_code=429, details={"retry_after": retry_after})


class ServiceUnavailableError(TaskFlowException):
    """Raised when a dependent service is unavailable."""
    
    def __init__(self, service: str):
        super().__init__(
            f"Service '{service}' is unavailable",
            status_code=503,
            details={"service": service}
        )
