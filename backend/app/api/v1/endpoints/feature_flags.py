"""
Feature Flag Management API Endpoints

Provides CRUD operations for feature flags and real-time evaluation.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field

from app.api.deps import get_current_user, get_current_active_superuser
from app.core.feature_flags import (
    feature_flag_service,
    FeatureFlag,
    FlagType,
    create_context,
    is_enabled,
    get_value,
    initialize_default_flags
)
from app.models.user import User

router = APIRouter()


class FeatureFlagCreate(BaseModel):
    """Request model for creating a feature flag."""
    key: str = Field(..., min_length=1, max_length=100, regex=r'^[a-z0-9_]+$')
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    flag_type: FlagType = Field(default=FlagType.BOOLEAN)
    default_value: Any = Field(default=False)
    rollout_percentage: int = Field(default=0, ge=0, le=100)
    target_segments: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    enabled: bool = Field(default=True)


class FeatureFlagUpdate(BaseModel):
    """Request model for updating a feature flag."""
    name: Optional[str] = None
    description: Optional[str] = None
    flag_type: Optional[FlagType] = None
    default_value: Optional[Any] = None
    rollout_percentage: Optional[int] = Field(None, ge=0, le=100)
    target_segments: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    enabled: Optional[bool] = None
    archived: Optional[bool] = None


class FeatureFlagResponse(BaseModel):
    """Response model for feature flags."""
    key: str
    name: str
    description: str
    flag_type: str
    default_value: Any
    rollout_percentage: int
    target_segments: List[str]
    tags: List[str]
    enabled: bool
    archived: bool
    created_at: datetime
    updated_at: datetime
    created_by: str


class FlagEvaluationRequest(BaseModel):
    """Request model for flag evaluation."""
    flag_keys: List[str]
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)


class FlagEvaluationResponse(BaseModel):
    """Response model for flag evaluation."""
    flag_key: str
    value: Any
    source: str
    reason: Optional[str] = None


@router.post("/flags", response_model=FeatureFlagResponse, status_code=201)
async def create_flag(
    flag_data: FeatureFlagCreate,
    current_user: User = Depends(get_current_active_superuser)
) -> Any:
    """
    Create a new feature flag.
    
    Requires superuser privileges.
    """
    # Check if flag already exists
    existing = await feature_flag_service.store.get_flag(flag_data.key)
    if existing:
        raise HTTPException(status_code=409, detail=f"Flag '{flag_data.key}' already exists")
    
    # Create flag
    flag = FeatureFlag(
        key=flag_data.key,
        name=flag_data.name,
        description=flag_data.description,
        flag_type=flag_data.flag_type,
        default_value=flag_data.default_value,
        rollout_percentage=flag_data.rollout_percentage,
        target_segments=flag_data.target_segments,
        tags=flag_data.tags,
        enabled=flag_data.enabled,
        created_by=str(current_user.id)
    )
    
    created = await feature_flag_service.create_flag(flag)
    return _flag_to_response(created)


@router.get("/flags", response_model=List[FeatureFlagResponse])
async def list_flags(
    tags: Optional[List[str]] = Query(None),
    include_archived: bool = Query(False),
    current_user: User = Depends(get_current_user)
) -> Any:
    """List all feature flags."""
    flags = await feature_flag_service.list_flags(
        tags=tags,
        include_archived=include_archived
    )
    return [_flag_to_response(f) for f in flags]


@router.get("/flags/{flag_key}", response_model=FeatureFlagResponse)
async def get_flag(
    flag_key: str,
    current_user: User = Depends(get_current_user)
) -> Any:
    """Get a specific feature flag."""
    flag = await feature_flag_service.store.get_flag(flag_key)
    if not flag:
        raise HTTPException(status_code=404, detail=f"Flag '{flag_key}' not found")
    return _flag_to_response(flag)


@router.patch("/flags/{flag_key}", response_model=FeatureFlagResponse)
async def update_flag(
    flag_key: str,
    updates: FeatureFlagUpdate,
    current_user: User = Depends(get_current_active_superuser)
) -> Any:
    """
    Update a feature flag.
    
    Requires superuser privileges.
    """
    update_dict = updates.dict(exclude_unset=True)
    if not update_dict:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    try:
        updated = await feature_flag_service.update_flag(flag_key, update_dict)
        return _flag_to_response(updated)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/flags/{flag_key}", status_code=204)
async def delete_flag(
    flag_key: str,
    current_user: User = Depends(get_current_active_superuser)
) -> None:
    """
    Delete a feature flag.
    
    Requires superuser privileges.
    """
    success = await feature_flag_service.delete_flag(flag_key)
    if not success:
        raise HTTPException(status_code=404, detail=f"Flag '{flag_key}' not found")


@router.post("/evaluate", response_model=List[FlagEvaluationResponse])
async def evaluate_flags(
    request: FlagEvaluationRequest,
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Evaluate multiple feature flags for the current user context.
    """
    # Build context from current user
    context = create_context(
        user={
            "id": str(current_user.id),
            "email": current_user.email,
            "role": current_user.role,
            "is_active": current_user.is_active,
        },
        **request.context
    )
    
    # Evaluate all requested flags
    results = await feature_flag_service.bulk_evaluate(request.flag_keys, context)
    
    return [
        FlagEvaluationResponse(
            flag_key=r.flag_key,
            value=r.value,
            source=r.source,
            reason=r.reason
        )
        for r in results.values()
    ]


@router.get("/evaluate/{flag_key}", response_model=FlagEvaluationResponse)
async def evaluate_flag(
    flag_key: str,
    current_user: User = Depends(get_current_user)
) -> Any:
    """Evaluate a single feature flag."""
    context = create_context(
        user={
            "id": str(current_user.id),
            "email": current_user.email,
            "role": current_user.role,
        }
    )
    
    result = await feature_flag_service.evaluate(flag_key, context)
    return FlagEvaluationResponse(
        flag_key=result.flag_key,
        value=result.value,
        source=result.source,
        reason=result.reason
    )


@router.post("/flags/{flag_key}/enable", response_model=FeatureFlagResponse)
async def enable_flag(
    flag_key: str,
    current_user: User = Depends(get_current_active_superuser)
) -> Any:
    """Enable a feature flag."""
    try:
        updated = await feature_flag_service.update_flag(flag_key, {"enabled": True})
        return _flag_to_response(updated)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/flags/{flag_key}/disable", response_model=FeatureFlagResponse)
async def disable_flag(
    flag_key: str,
    current_user: User = Depends(get_current_active_superuser)
) -> Any:
    """Disable a feature flag."""
    try:
        updated = await feature_flag_service.update_flag(flag_key, {"enabled": False})
        return _flag_to_response(updated)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/flags/{flag_key}/archive", response_model=FeatureFlagResponse)
async def archive_flag(
    flag_key: str,
    current_user: User = Depends(get_current_active_superuser)
) -> Any:
    """Archive a feature flag."""
    try:
        updated = await feature_flag_service.update_flag(flag_key, {"archived": True})
        return _flag_to_response(updated)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/initialize-defaults", status_code=204)
async def initialize_defaults(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_superuser)
) -> None:
    """
    Initialize default feature flags.
    
    Runs in background. Requires superuser privileges.
    """
    background_tasks.add_task(initialize_default_flags)


def _flag_to_response(flag: FeatureFlag) -> Dict[str, Any]:
    """Convert FeatureFlag to response dict."""
    return {
        "key": flag.key,
        "name": flag.name,
        "description": flag.description,
        "flag_type": flag.flag_type.value,
        "default_value": flag.default_value,
        "rollout_percentage": flag.rollout_percentage,
        "target_segments": flag.target_segments,
        "tags": flag.tags,
        "enabled": flag.enabled,
        "archived": flag.archived,
        "created_at": flag.created_at,
        "updated_at": flag.updated_at,
        "created_by": flag.created_by,
    }
