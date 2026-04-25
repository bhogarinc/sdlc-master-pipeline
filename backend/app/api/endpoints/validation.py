"""
Migration Validation API Endpoints

REST API for running and monitoring migration validations.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
import json

from ...database import get_db
from ...deps import get_current_user, require_admin
from ..validation.migration_validator import MigrationValidator
from ..validation.performance_monitor import PerformanceMonitor

router = APIRouter(prefix="/validation", tags=["migration-validation"])


# Pydantic models for API
class ValidationRequest(BaseModel):
    migration_id: str = Field(..., description="Unique migration identifier")
    source_database_url: Optional[str] = Field(None, description="Source database URL")
    validate_checksums: bool = Field(True, description="Validate data checksums")
    validate_referential: bool = Field(True, description="Validate referential integrity")
    validate_business_rules: bool = Field(True, description="Validate business rules")
    tables: Optional[List[str]] = Field(None, description="Specific tables to validate")


class ValidationResponse(BaseModel):
    migration_id: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    overall_status: str
    summary: Dict[str, Any]


class ValidationStatusResponse(BaseModel):
    migration_id: str
    status: str
    phase: str
    progress: Dict[str, Any]
    current_operation: Optional[str]
    estimated_completion: Optional[datetime]


class ValidationReportResponse(BaseModel):
    migration_id: str
    report: Dict[str, Any]
    download_url: Optional[str]


# In-memory store for active validations (use Redis in production)
_active_validations: Dict[str, Dict] = {}
_validation_reports: Dict[str, Dict] = {}


@router.post("/validate", response_model=ValidationResponse)
async def start_validation(
    request: ValidationRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_admin)
):
    """
    Start a new migration validation.
    
    This runs validation in the background and returns immediately.
    Use /validation/{migration_id}/status to check progress.
    """
    if request.migration_id in _active_validations:
        raise HTTPException(
            status_code=409,
            detail=f"Validation already in progress for migration {request.migration_id}"
        )
    
    # Initialize validation tracking
    _active_validations[request.migration_id] = {
        'status': 'starting',
        'phase': 'pre_migration',
        'started_at': datetime.utcnow(),
        'progress': {'completed_tables': 0, 'total_tables': 12}
    }
    
    # Start validation in background
    background_tasks.add_task(
        _run_validation,
        request.migration_id,
        request,
        db
    )
    
    return ValidationResponse(
        migration_id=request.migration_id,
        status='started',
        started_at=datetime.utcnow(),
        completed_at=None,
        overall_status='pending',
        summary={'message': 'Validation started in background'}
    )


async def _run_validation(
    migration_id: str,
    request: ValidationRequest,
    db: AsyncSession
):
    """Background task to run validation."""
    try:
        # Create source session if URL provided
        source_session = None
        if request.source_database_url:
            from sqlalchemy.ext.asyncio import create_async_engine
            from sqlalchemy.orm import sessionmaker
            
            engine = create_async_engine(request.source_database_url)
            async_session = sessionmaker(engine, class_=AsyncSession)
            source_session = async_session()
        
        validator = MigrationValidator(
            migration_id=migration_id,
            source_session=source_session or db,
            destination_session=db
        )
        
        # Update status
        _active_validations[migration_id]['status'] = 'running'
        _active_validations[migration_id]['phase'] = 'post_migration'
        
        # Run validation
        report = await validator.run_post_migration_validation(
            validate_checksums=request.validate_checksums,
            validate_referential=request.validate_referential,
            validate_business_rules=request.validate_business_rules
        )
        
        # Store report
        _validation_reports[migration_id] = report.to_dict()
        
        # Update status
        _active_validations[migration_id]['status'] = 'completed'
        _active_validations[migration_id]['completed_at'] = datetime.utcnow()
        
    except Exception as e:
        _active_validations[migration_id]['status'] = 'failed'
        _active_validations[migration_id]['error'] = str(e)
    finally:
        if source_session:
            await source_session.close()


@router.get("/{migration_id}/status", response_model=ValidationStatusResponse)
async def get_validation_status(
    migration_id: str,
    current_user = Depends(get_current_user)
):
    """Get current status of a running or completed validation."""
    if migration_id not in _active_validations:
        raise HTTPException(
            status_code=404,
            detail=f"No validation found for migration {migration_id}"
        )
    
    validation = _active_validations[migration_id]
    
    return ValidationStatusResponse(
        migration_id=migration_id,
        status=validation['status'],
        phase=validation['phase'],
        progress=validation.get('progress', {}),
        current_operation=validation.get('current_operation'),
        estimated_completion=validation.get('estimated_completion')
    )


@router.get("/{migration_id}/report", response_model=ValidationReportResponse)
async def get_validation_report(
    migration_id: str,
    format: str = Query('json', enum=['json', 'html', 'pdf']),
    current_user = Depends(get_current_user)
):
    """
    Get complete validation report for a migration.
    
    Formats:
    - json: Raw JSON report
    - html: Formatted HTML report
    - pdf: PDF report (generated on demand)
    """
    if migration_id not in _validation_reports:
        # Check if validation is still running
        if migration_id in _active_validations:
            raise HTTPException(
                status_code=202,
                detail="Validation still in progress"
            )
        raise HTTPException(
            status_code=404,
            detail=f"No report found for migration {migration_id}"
        )
    
    report = _validation_reports[migration_id]
    
    if format == 'html':
        html_report = _generate_html_report(report)
        return ValidationReportResponse(
            migration_id=migration_id,
            report={'html': html_report},
            download_url=None
        )
    
    return ValidationReportResponse(
        migration_id=migration_id,
        report=report,
        download_url=f"/api/v1/validation/{migration_id}/download?format={format}"
    )


@router.post("/{migration_id}/rollback-verification")
async def verify_rollback(
    migration_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_admin)
):
    """
    Verify that rollback procedure correctly restores data.
    
    This should be run after a rollback operation to ensure data integrity.
    """
    from ..validation.rollback_verifier import RollbackVerifier
    
    verifier = RollbackVerifier(session=db, migration_id=migration_id)
    
    # Run verification
    results = await verifier.verify_all_tables(
        MigrationValidator.CORE_TABLES
    )
    
    report = verifier.generate_report()
    
    return {
        'migration_id': migration_id,
        'rollback_verified': verifier.is_rollback_verified(),
        'overall_status': report.overall_status.value,
        'summary': report.summary,
        'failed_tables': verifier.get_failed_tables()
    }


@router.get("/health")
async def validation_health_check():
    """Health check endpoint for validation service."""
    return {
        'status': 'healthy',
        'active_validations': len(_active_validations),
        'completed_validations': len(_validation_reports),
        'timestamp': datetime.utcnow()
    }


@router.get("/reports")
async def list_validation_reports(
    status: Optional[str] = None,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user = Depends(get_current_user)
):
    """List all validation reports with optional filtering."""
    reports = []
    
    for migration_id, report in _validation_reports.items():
        if status and report.get('overall_status') != status:
            continue
        
        reports.append({
            'migration_id': migration_id,
            'status': report.get('overall_status'),
            'completed_at': report.get('completed_at'),
            'total_issues': report.get('summary', {}).get('total_issues', 0)
        })
    
    # Sort by completed_at descending
    reports.sort(key=lambda x: x['completed_at'] or datetime.min, reverse=True)
    
    total = len(reports)
    reports = reports[offset:offset + limit]
    
    return {
        'total': total,
        'offset': offset,
        'limit': limit,
        'reports': reports
    }


def _generate_html_report(report: Dict) -> str:
    """Generate HTML formatted report."""
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Migration Validation Report - {report['migration_id']}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            .header {{ background: #f0f0f0; padding: 20px; border-radius: 5px; }}
            .status-pass {{ color: green; }}
            .status-fail {{ color: red; }}
            .status-warning {{ color: orange; }}
            table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background: #4CAF50; color: white; }}
            tr:nth-child(even) {{ background: #f2f2f2; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Migration Validation Report</h1>
            <p>Migration ID: {report['migration_id']}</p>
            <p>Status: <span class="status-{report['overall_status']}">{report['overall_status'].upper()}</span></p>
            <p>Completed: {report.get('completed_at', 'N/A')}</p>
        </div>
        
        <h2>Summary</h2>
        <ul>
            <li>Total Issues: {report.get('summary', {}).get('total_issues', 0)}</li>
            <li>Total Warnings: {report.get('summary', {}).get('total_warnings', 0)}</li>
        </ul>
        
        <h2>Row Count Validation</h2>
        <table>
            <tr>
                <th>Table</th>
                <th>Source</th>
                <th>Destination</th>
                <th>Difference</th>
                <th>Status</th>
            </tr>
    """
    
    for row in report.get('row_count_checks', []):
        status_class = f"status-{row['status'].lower()}"
        html += f"""
            <tr>
                <td>{row['table_name']}</td>
                <td>{row['source_count']}</td>
                <td>{row['destination_count']}</td>
                <td>{row['difference']:+d}</td>
                <td class="{status_class}">{row['status']}</td>
            </tr>
        """
    
    html += """
        </table>
    </body>
    </html>
    """
    
    return html