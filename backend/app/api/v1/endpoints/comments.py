"""
Comment API endpoints.
"""

from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.database import get_db
from app.core.deps import get_current_user
from app.schemas.comment import (
    CommentCreate,
    CommentUpdate,
    CommentResponse,
    PaginatedCommentResponse
)
from app.schemas.common import PaginationParams
from app.services.comment_service import CommentService
from app.services.notification_service import NotificationService

router = APIRouter()
logger = structlog.get_logger()


@router.get("/task/{task_id}", response_model=PaginatedCommentResponse)
async def list_task_comments(
    task_id: str,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    List comments for a task.
    
    Supports pagination and includes reply counts.
    """
    comment_service = CommentService(db)
    
    comments, total = await comment_service.get_task_comments(
        task_id=task_id,
        pagination=pagination,
        user_id=current_user.id
    )
    
    return PaginatedCommentResponse.create(
        items=comments,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size
    )


@router.post("", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
async def create_comment(
    comment_in: CommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Create a new comment on a task.
    
    Supports replies by specifying parent_id.
    Sends notifications to task assignee and mentioned users.
    """
    comment_service = CommentService(db)
    
    comment = await comment_service.create(
        comment_data=comment_in,
        author_id=current_user.id
    )
    
    # Send notifications
    await NotificationService.send_comment_notification(
        task_id=comment_in.task_id,
        comment_id=comment.id,
        author_id=current_user.id,
        mentions=comment.mentions if hasattr(comment, 'mentions') else []
    )
    
    logger.info(
        "comment_created",
        comment_id=comment.id,
        task_id=comment_in.task_id,
        author_id=current_user.id
    )
    
    return comment


@router.get("/{comment_id}", response_model=CommentResponse)
async def get_comment(
    comment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Get comment by ID.
    """
    comment_service = CommentService(db)
    
    comment = await comment_service.get_by_id(comment_id, user_id=current_user.id)
    
    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found"
        )
    
    return comment


@router.patch("/{comment_id}", response_model=CommentResponse)
async def update_comment(
    comment_id: str,
    comment_update: CommentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Update comment content.
    
    Only author or team admin can edit.
    """
    comment_service = CommentService(db)
    
    comment = await comment_service.update(
        comment_id=comment_id,
        update_data=comment_update,
        user_id=current_user.id
    )
    
    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found"
        )
    
    logger.info("comment_updated", comment_id=comment_id)
    
    return comment


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> None:
    """
    Delete comment.
    
    Only author or team admin can delete.
    Cascades to replies.
    """
    comment_service = CommentService(db)
    
    success = await comment_service.delete(
        comment_id=comment_id,
        user_id=current_user.id
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found"
        )
    
    logger.info("comment_deleted", comment_id=comment_id)


@router.get("/{comment_id}/replies", response_model=List[CommentResponse])
async def get_comment_replies(
    comment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Get replies to a comment.
    """
    comment_service = CommentService(db)
    
    replies = await comment_service.get_replies(
        parent_id=comment_id,
        user_id=current_user.id
    )
    
    return replies