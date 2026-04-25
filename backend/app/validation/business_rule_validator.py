"""
Business Rule Validation Module

Validates domain-specific business rules and constraints.
Ensures data integrity at the application level.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import text, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class RuleSeverity(Enum):
    """Severity levels for business rule violations."""
    CRITICAL = "critical"    # Data corruption - must fix
    HIGH = "high"           # Serious issue - should fix
    MEDIUM = "medium"       # Minor issue - investigate
    LOW = "low"             # Advisory - monitor


@dataclass
class BusinessRuleResult:
    """Result of a business rule validation."""
    rule_name: str
    rule_description: str
    severity: RuleSeverity
    violation_count: int
    total_checked: int
    violation_percentage: float
    status: str  # 'PASS', 'FAIL', 'WARNING'
    sample_violations: Optional[List[Dict]] = None
    validated_at: datetime = None
    details: Optional[str] = None
    
    def __post_init__(self):
        if self.validated_at is None:
            self.validated_at = datetime.utcnow()


class BusinessRuleValidator:
    """
    Validates domain-specific business rules for TaskFlow Pro.
    
    Rules include:
    - Email format validation
    - Task status transitions
    - Team member limits
    - Board column ordering
    - Notification preferences
    - Password reset token expiration
    """
    
    def __init__(
        self,
        session: AsyncSession,
        max_sample_violations: int = 10
    ):
        self.session = session
        self.max_sample_violations = max_sample_violations
        self.results: List[BusinessRuleResult] = []
        
    async def _execute_rule_query(
        self,
        query: str,
        violation_condition: str,
        table_name: str
    ) -> tuple:
        """Execute a business rule validation query."""
        # Count violations
        violation_query = f"""
            SELECT COUNT(*) 
            FROM {table_name}
            WHERE {violation_condition}
        """
        violation_result = await self.session.execute(text(violation_query))
        violation_count = violation_result.scalar()
        
        # Get total count
        total_query = f"SELECT COUNT(*) FROM {table_name}"
        total_result = await self.session.execute(text(total_query))
        total_count = total_result.scalar()
        
        # Get sample violations
        sample_violations = []
        if violation_count > 0:
            sample_query = f"""
                SELECT * FROM {table_name}
                WHERE {violation_condition}
                LIMIT {self.max_sample_violations}
            """
            sample_result = await self.session.execute(text(sample_query))
            sample_violations = [dict(row) for row in sample_result.mappings().all()]
        
        return violation_count, total_count, sample_violations
    
    async def validate_email_format(self) -> BusinessRuleResult:
        """Validate that all user emails follow proper format."""
        rule_name = "email_format_validation"
        description = "All user emails must follow valid email format"
        
        # PostgreSQL email validation regex
        email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        violation_condition = f"email !~* '{email_regex}'"
        
        violation_count, total_count, samples = await self._execute_rule_query(
            "", violation_condition, "users"
        )
        
        percentage = (violation_count / total_count * 100) if total_count > 0 else 0
        
        # Any invalid email is a critical issue
        status = 'PASS' if violation_count == 0 else 'FAIL'
        
        return BusinessRuleResult(
            rule_name=rule_name,
            rule_description=description,
            severity=RuleSeverity.CRITICAL,
            violation_count=violation_count,
            total_checked=total_count,
            violation_percentage=round(percentage, 4),
            status=status,
            sample_violations=samples,
            details=f"{violation_count} users have invalid email format"
        )
    
    async def validate_task_status_transitions(self) -> BusinessRuleResult:
        """Validate task status values are valid."""
        rule_name = "task_status_validation"
        description = "All tasks must have valid status values"
        
        valid_statuses = ['backlog', 'todo', 'in_progress', 'in_review', 'done', 'cancelled']
        status_list = ", ".join(f"'{s}'" for s in valid_statuses)
        violation_condition = f"status NOT IN ({status_list})"
        
        violation_count, total_count, samples = await self._execute_rule_query(
            "", violation_condition, "tasks"
        )
        
        percentage = (violation_count / total_count * 100) if total_count > 0 else 0
        status = 'PASS' if violation_count == 0 else 'FAIL'
        
        return BusinessRuleResult(
            rule_name=rule_name,
            rule_description=description,
            severity=RuleSeverity.HIGH,
            violation_count=violation_count,
            total_checked=total_count,
            violation_percentage=round(percentage, 4),
            status=status,
            sample_violations=samples,
            details=f"{violation_count} tasks have invalid status"
        )
    
    async def validate_task_priority(self) -> BusinessRuleResult:
        """Validate task priority values."""
        rule_name = "task_priority_validation"
        description = "All tasks must have valid priority values"
        
        valid_priorities = ['low', 'medium', 'high', 'urgent']
        priority_list = ", ".join(f"'{p}'" for p in valid_priorities)
        violation_condition = f"priority NOT IN ({priority_list})"
        
        violation_count, total_count, samples = await self._execute_rule_query(
            "", violation_condition, "tasks"
        )
        
        percentage = (violation_count / total_count * 100) if total_count > 0 else 0
        status = 'PASS' if violation_count == 0 else 'FAIL'
        
        return BusinessRuleResult(
            rule_name=rule_name,
            rule_description=description,
            severity=RuleSeverity.HIGH,
            violation_count=violation_count,
            total_checked=total_count,
            violation_percentage=round(percentage, 4),
            status=status,
            sample_violations=samples,
            details=f"{violation_count} tasks have invalid priority"
        )
    
    async def validate_due_dates(self) -> BusinessRuleResult:
        """Validate task due dates are not in the past for active tasks."""
        rule_name = "task_due_date_validation"
        description = "Active tasks should not have past due dates"
        
        violation_condition = """
            due_date IS NOT NULL 
            AND due_date < CURRENT_DATE
            AND status NOT IN ('done', 'cancelled')
        """
        
        violation_count, total_count, samples = await self._execute_rule_query(
            "", violation_condition, "tasks"
        )
        
        percentage = (violation_count / total_count * 100) if total_count > 0 else 0
        # Overdue tasks are a warning, not a failure
        status = 'PASS' if violation_count == 0 else 'WARNING'
        
        return BusinessRuleResult(
            rule_name=rule_name,
            rule_description=description,
            severity=RuleSeverity.MEDIUM,
            violation_count=violation_count,
            total_checked=total_count,
            violation_percentage=round(percentage, 4),
            status=status,
            sample_violations=samples,
            details=f"{violation_count} active tasks are past due"
        )
    
    async def validate_team_member_limits(self, max_members: int = 100) -> BusinessRuleResult:
        """Validate teams don't exceed member limits."""
        rule_name = "team_member_limit_validation"
        description = f"Teams should not exceed {max_members} members"
        
        violation_query = f"""
            SELECT team_id, COUNT(*) as member_count
            FROM team_members
            GROUP BY team_id
            HAVING COUNT(*) > {max_members}
        """
        
        violation_result = await self.session.execute(text(violation_query))
        violations = violation_result.mappings().all()
        violation_count = len(violations)
        
        # Get total team count
        total_query = "SELECT COUNT(DISTINCT team_id) FROM team_members"
        total_result = await self.session.execute(text(total_query))
        total_count = total_result.scalar()
        
        percentage = (violation_count / total_count * 100) if total_count > 0 else 0
        status = 'PASS' if violation_count == 0 else 'WARNING'
        
        return BusinessRuleResult(
            rule_name=rule_name,
            rule_description=description,
            severity=RuleSeverity.MEDIUM,
            violation_count=violation_count,
            total_checked=total_count,
            violation_percentage=round(percentage, 4),
            status=status,
            sample_violations=[dict(v) for v in violations[:self.max_sample_violations]],
            details=f"{violation_count} teams exceed {max_members} members"
        )
    
    async def validate_board_column_order(self) -> BusinessRuleResult:
        """Validate board columns have valid position ordering."""
        rule_name = "board_column_order_validation"
        description = "Board columns should have unique sequential positions"
        
        violation_query = """
            SELECT board_id, position, COUNT(*) as count
            FROM columns
            GROUP BY board_id, position
            HAVING COUNT(*) > 1
        """
        
        violation_result = await self.session.execute(text(violation_query))
        violations = violation_result.mappings().all()
        violation_count = len(violations)
        
        # Get total board count
        total_query = "SELECT COUNT(DISTINCT board_id) FROM columns"
        total_result = await self.session.execute(text(total_query))
        total_count = total_result.scalar()
        
        percentage = (violation_count / total_count * 100) if total_count > 0 else 0
        status = 'PASS' if violation_count == 0 else 'FAIL'
        
        return BusinessRuleResult(
            rule_name=rule_name,
            rule_description=description,
            severity=RuleSeverity.HIGH,
            violation_count=violation_count,
            total_checked=total_count,
            violation_percentage=round(percentage, 4),
            status=status,
            sample_violations=[dict(v) for v in violations[:self.max_sample_violations]],
            details=f"{violation_count} boards have duplicate column positions"
        )
    
    async def validate_password_reset_tokens(self) -> BusinessRuleResult:
        """Validate password reset tokens are not expired."""
        rule_name = "password_reset_token_validation"
        description = "Password reset tokens should not be expired"
        
        # Tokens expire after 24 hours
        expiration_time = datetime.utcnow() - timedelta(hours=24)
        violation_condition = f"expires_at < '{expiration_time.isoformat()}'"
        
        violation_count, total_count, samples = await self._execute_rule_query(
            "", violation_condition, "password_reset_tokens"
        )
        
        percentage = (violation_count / total_count * 100) if total_count > 0 else 0
        # Expired tokens are a warning (cleanup needed)
        status = 'PASS' if violation_count == 0 else 'WARNING'
        
        return BusinessRuleResult(
            rule_name=rule_name,
            rule_description=description,
            severity=RuleSeverity.LOW,
            violation_count=violation_count,
            total_checked=total_count,
            violation_percentage=round(percentage, 4),
            status=status,
            sample_violations=samples,
            details=f"{violation_count} password reset tokens are expired"
        )
    
    async def validate_notification_preferences(self) -> BusinessRuleResult:
        """Validate notification preferences are valid JSON."""
        rule_name = "notification_preferences_validation"
        description = "Notification preferences should be valid JSON"
        
        violation_condition = """
            preferences IS NOT NULL 
            AND NOT (preferences::text)::jsonb IS NOT NULL
        """
        
        violation_count, total_count, samples = await self._execute_rule_query(
            "", violation_condition, "user_preferences"
        )
        
        percentage = (violation_count / total_count * 100) if total_count > 0 else 0
        status = 'PASS' if violation_count == 0 else 'FAIL'
        
        return BusinessRuleResult(
            rule_name=rule_name,
            rule_description=description,
            severity=RuleSeverity.HIGH,
            violation_count=violation_count,
            total_checked=total_count,
            violation_percentage=round(percentage, 4),
            status=status,
            sample_violations=samples,
            details=f"{violation_count} users have invalid notification preferences"
        )
    
    async def validate_user_roles(self) -> BusinessRuleResult:
        """Validate user roles are valid."""
        rule_name = "user_role_validation"
        description = "All users must have valid role values"
        
        valid_roles = ['admin', 'manager', 'member', 'viewer']
        role_list = ", ".join(f"'{r}'" for r in valid_roles)
        violation_condition = f"role NOT IN ({role_list})"
        
        violation_count, total_count, samples = await self._execute_rule_query(
            "", violation_condition, "users"
        )
        
        percentage = (violation_count / total_count * 100) if total_count > 0 else 0
        status = 'PASS' if violation_count == 0 else 'FAIL'
        
        return BusinessRuleResult(
            rule_name=rule_name,
            rule_description=description,
            severity=RuleSeverity.CRITICAL,
            violation_count=violation_count,
            total_checked=total_count,
            violation_percentage=round(percentage, 4),
            status=status,
            sample_violations=samples,
            details=f"{violation_count} users have invalid roles"
        )
    
    async def validate_all_rules(self) -> List[BusinessRuleResult]:
        """Run all business rule validations."""
        logger.info("Starting business rule validation")
        
        rules = [
            self.validate_email_format(),
            self.validate_task_status_transitions(),
            self.validate_task_priority(),
            self.validate_due_dates(),
            self.validate_team_member_limits(),
            self.validate_board_column_order(),
            self.validate_password_reset_tokens(),
            self.validate_notification_preferences(),
            self.validate_user_roles(),
        ]
        
        self.results = await asyncio.gather(*rules)
        return self.results
    
    def get_summary(self) -> Dict:
        """Get summary of all business rule validations."""
        if not self.results:
            return {
                'total': 0, 'passed': 0, 'failed': 0, 'warnings': 0,
                'critical_violations': 0, 'high_violations': 0
            }
        
        return {
            'total': len(self.results),
            'passed': sum(1 for r in self.results if r.status == 'PASS'),
            'failed': sum(1 for r in self.results if r.status == 'FAIL'),
            'warnings': sum(1 for r in self.results if r.status == 'WARNING'),
            'critical_violations': sum(
                r.violation_count for r in self.results 
                if r.severity == RuleSeverity.CRITICAL
            ),
            'high_violations': sum(
                r.violation_count for r in self.results 
                if r.severity == RuleSeverity.HIGH
            ),
            'rules_with_issues': [
                r.rule_name for r in self.results if r.status in ('FAIL', 'WARNING')
            ]
        }
    
    def has_failures(self) -> bool:
        """Check if any business rule validations failed."""
        return any(r.status == 'FAIL' for r in self.results)
    
    def get_critical_violations(self) -> List[str]:
        """Get list of rules with critical violations."""
        return [
            r.rule_name for r in self.results 
            if r.severity == RuleSeverity.CRITICAL and r.violation_count > 0
        ]


# Import at end to avoid circular dependency
import asyncio