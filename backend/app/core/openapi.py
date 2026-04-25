"""
OpenAPI documentation configuration for TaskFlow Pro API.
"""

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.core.config import settings


def custom_openapi(app: FastAPI):
    """Generate custom OpenAPI schema with enhanced documentation."""
    
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description="""
        # TaskFlow Pro API
        
        A comprehensive task management platform with team collaboration features.
        
        ## Features
        
        - **Authentication**: JWT-based authentication with refresh tokens
        - **Task Management**: Full CRUD operations with filtering and pagination
        - **Team Collaboration**: Invite members, assign roles, shared boards
        - **Real-time Notifications**: WebSocket support for live updates
        - **File Attachments**: Upload and manage task attachments
        
        ## Authentication
        
        All protected endpoints require a Bearer token in the Authorization header:
        ```
        Authorization: Bearer <access_token>
        ```
        
        ## Error Responses
        
        Standard error format:
        ```json
        {
            "success": false,
            "error_code": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "details": [...]
        }
        ```
        
        ## Pagination
        
        List endpoints support pagination with:
        - `page`: Page number (1-indexed)
        - `page_size`: Items per page (1-100)
        - `sort_by`: Field to sort by
        - `sort_order`: asc or desc
        """,
        routes=app.routes,
    )
    
    # Add security scheme
    openapi_schema["components"]["securitySchemes"] = {
        "bearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Enter your JWT token in the format: Bearer <token>"
        }
    }
    
    # Add global security
    openapi_schema["security"] = [{"bearerAuth": []}]
    
    # Add servers
    openapi_schema["servers"] = [
        {"url": "http://localhost:8000", "description": "Local development"},
        {"url": "https://api.taskflow.pro", "description": "Production"},
        {"url": "https://api.staging.taskflow.pro", "description": "Staging"}
    ]
    
    # Add tags with descriptions
    openapi_schema["tags"] = [
        {
            "name": "Authentication",
            "description": "User registration, login, and token management"
        },
        {
            "name": "Users",
            "description": "User profile management and preferences"
        },
        {
            "name": "Tasks",
            "description": "Task CRUD operations and assignment"
        },
        {
            "name": "Teams",
            "description": "Team management and member invitations"
        },
        {
            "name": "Boards",
            "description": "Kanban board management with columns"
        },
        {
            "name": "Comments",
            "description": "Task comments and threaded discussions"
        },
        {
            "name": "Attachments",
            "description": "File upload and attachment management"
        },
        {
            "name": "Notifications",
            "description": "Real-time notifications and preferences"
        },
        {
            "name": "Health",
            "description": "Service health and readiness checks"
        }
    ]
    
    # Add external docs
    openapi_schema["externalDocs"] = {
        "description": "Find more info here",
        "url": "https://docs.taskflow.pro/api"
    }
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema


def configure_openapi(app: FastAPI):
    """Configure OpenAPI for the application."""
    app.openapi = lambda: custom_openapi(app)