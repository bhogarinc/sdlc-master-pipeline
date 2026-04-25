"""
Board management API endpoints.
"""

from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.database import get_db
from app.core.deps import get_current_user, require_team_permission
from app.schemas.board import (
    BoardCreate,
    BoardUpdate,
    BoardResponse,
    ColumnCreate,
    ColumnUpdate,
    BoardColumn
)
from app.schemas.task import TaskResponse
from app.schemas.common import PaginationParams
from app.services.board_service import BoardService

router = APIRouter()
logger = structlog.get_logger()


@router.get("/team/{team_id}", response_model=List[BoardResponse])
async def list_team_boards(
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    List all boards for a team.
    """
    board_service = BoardService(db)
    boards = await board_service.get_team_boards(
        team_id=team_id,
        user_id=current_user.id
    )
    
    return boards


@router.post("", response_model=BoardResponse, status_code=status.HTTP_201_CREATED)
async def create_board(
    board_in: BoardCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_team_permission("board:create"))
) -> Any:
    """
    Create a new board.
    
    Creates default columns: Backlog, To Do, In Progress, Done
    """
    board_service = BoardService(db)
    
    board = await board_service.create(
        board_data=board_in,
        created_by=current_user.id
    )
    
    logger.info("board_created", board_id=board.id, team_id=board_in.team_id)
    
    return board


@router.get("/{board_id}", response_model=BoardResponse)
async def get_board(
    board_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Get board with columns and tasks.
    """
    board_service = BoardService(db)
    board = await board_service.get_by_id(board_id, user_id=current_user.id)
    
    if not board:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Board not found"
        )
    
    return board


@router.patch("/{board_id}", response_model=BoardResponse)
async def update_board(
    board_id: str,
    board_update: BoardUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_team_permission("board:update"))
) -> Any:
    """
    Update board details.
    """
    board_service = BoardService(db)
    
    board = await board_service.update(
        board_id=board_id,
        update_data=board_update,
        user_id=current_user.id
    )
    
    logger.info("board_updated", board_id=board_id)
    
    return board


@router.delete("/{board_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_board(
    board_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_team_permission("board:delete"))
) -> None:
    """
    Delete board and all associated tasks.
    """
    board_service = BoardService(db)
    
    success = await board_service.delete(board_id, user_id=current_user.id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Board not found"
        )
    
    logger.info("board_deleted", board_id=board_id)


# Column management

@router.post("/{board_id}/columns", response_model=BoardColumn, status_code=status.HTTP_201_CREATED)
async def create_column(
    board_id: str,
    column_in: ColumnCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_team_permission("board:update"))
) -> Any:
    """
    Add a new column to board.
    """
    board_service = BoardService(db)
    
    column = await board_service.create_column(
        board_id=board_id,
        column_data=column_in,
        user_id=current_user.id
    )
    
    return column


@router.patch("/{board_id}/columns/{column_id}", response_model=BoardColumn)
async def update_column(
    board_id: str,
    column_id: str,
    column_update: ColumnUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_team_permission("board:update"))
) -> Any:
    """
    Update column details.
    """
    board_service = BoardService(db)
    
    column = await board_service.update_column(
        column_id=column_id,
        update_data=column_update,
        user_id=current_user.id
    )
    
    return column


@router.delete("/{board_id}/columns/{column_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_column(
    board_id: str,
    column_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_team_permission("board:update"))
) -> None:
    """
    Delete column and move tasks to another column.
    """
    board_service = BoardService(db)
    
    await board_service.delete_column(
        column_id=column_id,
        user_id=current_user.id
    )


@router.post("/{board_id}/columns/reorder", response_model=List[BoardColumn])
async def reorder_columns(
    board_id: str,
    column_ids: List[str],
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_team_permission("board:update"))
) -> Any:
    """
    Reorder board columns.
    
    Provide ordered list of column IDs.
    """
    board_service = BoardService(db)
    
    columns = await board_service.reorder_columns(
        board_id=board_id,
        column_ids=column_ids,
        user_id=current_user.id
    )
    
    return columns


@router.get("/{board_id}/tasks", response_model=List[TaskResponse])
async def get_board_tasks(
    board_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Any:
    """
    Get all tasks for a board organized by columns.
    """
    board_service = BoardService(db)
    
    tasks = await board_service.get_board_tasks(
        board_id=board_id,
        user_id=current_user.id
    )
    
    return tasks