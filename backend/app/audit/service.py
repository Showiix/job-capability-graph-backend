from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog


def record_audit(
    db: AsyncSession,
    *,
    action: str,
    resource_type: str,
    outcome: str,
    request_id: str | None,
    actor_user_id: UUID | None = None,
    resource_id: UUID | None = None,
    ip_address: str | None = None,
    metadata: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            request_id=request_id,
            ip_address=ip_address,
            metadata_=metadata or {},
        )
    )
