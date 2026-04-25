"""
Attachment API endpoints.
"""

from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.database import get_db
from app.core.deps import get_current_user
from app.schemas.attachment import (
    AttachmentResponse,
    PaginatedAttachmentResponse
)
from app.schemas.common import PaginationParams
from app.services.attachment_service import AttachmentService
from app.services.file_service import FileService

router = APIRouter()
logger = structlog.get_logger()

# Maximum file size: 50MB
MAX_FILE_SIZE = 50 * 1024 * 1024


@router.get("/task/{task_id}", response_model=PaginatedAttachmentResponse)
async def list_task_attachments(
    task_id: str,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    List attachments for a task.
    """
    attachment_service = AttachmentService(db)
    
    attachments, total = await attachment_service.get_task_attachments(
        task_id=task_id,
        pagination=pagination,
        user_id=current_user.id
    )
    
    return PaginatedAttachmentResponse.create(
        items=attachments,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size
    )


@router.post("/task/{task_id}", response_model=AttachmentResponse, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    task_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Upload file attachment to task.
    
    - Max file size: 50MB
    - Supported types: images, documents, archives
    - Generates thumbnail for images
    """
    # Validate file size
    file_content = await file.read()
    if len(file_content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE / 1024 / 1024}MB"
        )
    
    # Reset file pointer
    await file.seek(0)
    
    # Upload to storage
    file_service = FileService()
    storage_key, thumbnail_key = await file_service.upload_file(
        file=file,
        file_content=file_content,
        folder=f"tasks/{task_id}"
    )
    
    # Create attachment record
    attachment_service = AttachmentService(db)
    attachment = await attachment_service.create(
        task_id=task_id,
        filename=file.filename,
        content_type=file.content_type,
        size_bytes=len(file_content),
        storage_key=storage_key,
        thumbnail_key=thumbnail_key,
        uploaded_by=current_user.id
    )
    
    logger.info(
        "attachment_uploaded",
        attachment_id=attachment.id,
        task_id=task_id,
        filename=file.filename
    )
    
    return attachment


@router.get("/{attachment_id}", response_model=AttachmentResponse)
async def get_attachment(
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Get attachment metadata.
    """
    attachment_service = AttachmentService(db)
    
    attachment = await attachment_service.get_by_id(
        attachment_id=attachment_id,
        user_id=current_user.id
    )
    
    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found"
        )
    
    return attachment


@router.get("/{attachment_id}/download")
async def download_attachment(
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Get presigned download URL for attachment.
    
    URL expires in 5 minutes.
    """
    attachment_service = AttachmentService(db)
    file_service = FileService()
    
    attachment = await attachment_service.get_by_id(
        attachment_id=attachment_id,
        user_id=current_user.id
    )
    
    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found"
        )
    
    # Generate presigned URL
    download_url = await file_service.get_presigned_url(
        storage_key=attachment.storage_key,
        filename=attachment.filename,
        expires_in=300  # 5 minutes
    )
    
    return {"download_url": download_url, "expires_in": 300}


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> None:
    """
    Delete attachment.
    
    Removes from storage and database.
    """
    attachment_service = AttachmentService(db)
    file_service = FileService()
    
    # Get attachment
    attachment = await attachment_service.get_by_id(
        attachment_id=attachment_id,
        user_id=current_user.id
    )
    
    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found"
        )
    
    # Delete from storage
    await file_service.delete_file(attachment.storage_key)
    if attachment.thumbnail_key:
        await file_service.delete_file(attachment.thumbnail_key)
    
    # Delete from database
    await attachment_service.delete(
        attachment_id=attachment_id,
        user_id=current_user.id
    )
    
    logger.info("attachment_deleted", attachment_id=attachment_id)