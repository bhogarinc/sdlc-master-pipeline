"""Rate limiting middleware."""
import logging
import time
from typing import Dict, Optional, Tuple

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class RateLimiter:
    """In-memory rate limiter using sliding window."""
    
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, list] = {}
    
    def is_allowed(self, key: str) -> Tuple[bool, Dict[str, any]]:
        """Check if request is allowed and return rate limit info."""
        now = time.time()
        window_start = now - self.window_seconds
        
        # Clean old requests
        if key in self.requests:
            self.requests[key] = [
                req_time for req_time in self.requests[key]
                if req_time > window_start
            ]
        else:
            self.requests[key] = []
        
        # Check limit
        current_count = len(self.requests[key])
        allowed = current_count < self.max_requests
        
        if allowed:
            self.requests[key].append(now)
        
        # Calculate reset time
        if self.requests[key]:
            reset_time = int(self.requests[key][0] + self.window_seconds)
        else:
            reset_time = int(now + self.window_seconds)
        
        remaining = max(0, self.max_requests - len(self.requests[key]))
        
        return allowed, {
            "limit": self.max_requests,
            "remaining": remaining,
            "reset": reset_time,
            "window": self.window_seconds
        }


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce rate limiting."""
    
    def __init__(
        self,
        app,
        max_requests: int = None,
        window_seconds: int = None,
        exclude_paths: Optional[list] = None
    ):
        super().__init__(app)
        self.max_requests = max_requests or settings.RATE_LIMIT_REQUESTS
        self.window_seconds = window_seconds or settings.RATE_LIMIT_WINDOW
        self.limiter = RateLimiter(self.max_requests, self.window_seconds)
        self.exclude_paths = exclude_paths or ["/health", "/docs", "/openapi.json"]
    
    def _get_client_key(self, request: Request) -> str:
        """Generate rate limit key for request."""
        # Use authenticated user ID if available
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            # Use token hash as identifier
            import hashlib
            token = auth_header[7:]
            return f"user:{hashlib.sha256(token.encode()).hexdigest()[:16]}"
        
        # Fall back to IP address
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"
        
        return f"ip:{ip}"
    
    def _is_excluded(self, path: str) -> bool:
        """Check if path is excluded from rate limiting."""
        return any(path.startswith(excluded) for excluded in self.exclude_paths)
    
    async def dispatch(self, request: Request, call_next):
        """Process request with rate limiting."""
        if self._is_excluded(request.url.path):
            return await call_next(request)
        
        key = self._get_client_key(request)
        allowed, rate_info = self.limiter.is_allowed(key)
        
        if not allowed:
            logger.warning(f"Rate limit exceeded for {key}")
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={
                    "X-RateLimit-Limit": str(rate_info["limit"]),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(rate_info["reset"]),
                    "Retry-After": str(rate_info["window"])
                },
                content={
                    "error": {
                        "code": 429,
                        "message": "Rate limit exceeded",
                        "details": {
                            "retry_after": rate_info["window"]
                        }
                    }
                }
            )
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(rate_info["limit"])
        response.headers["X-RateLimit-Remaining"] = str(rate_info["remaining"])
        response.headers["X-RateLimit-Reset"] = str(rate_info["reset"])
        
        return response


def get_rate_limit_headers(
    max_requests: int,
    remaining: int,
    reset_time: int
) -> Dict[str, str]:
    """Generate rate limit headers."""
    return {
        "X-RateLimit-Limit": str(max_requests),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset_time)
    }
