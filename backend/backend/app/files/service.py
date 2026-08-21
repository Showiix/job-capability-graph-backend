from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.errors import APIError
from app.files.models import FileAccessLog, StoredFile
from app.recruitment.models import RecruitmentCandidate, RecruitmentProject
from app.resumes.models import Resume


async def get_visible_file(
    db: AsyncSession,
    file_id: UUID,
    actor: User,
) -> StoredFile:
    stored_file = await db.get(StoredFile, file_id)
    if stored_file is None or stored_file.status in {"archived", "deleted"}:
        raise APIError(404, "FILE_NOT_FOUND", "文件不存在")
    visible = actor.role == "admin" or (
        stored_file.status == "uploaded" and stored_file.uploaded_by_user_id == actor.id
    )
    if not visible and stored_file.category == "resume":
        owner_resume_id = await db.scalar(
            select(Resume.id).where(
                Resume.file_id == stored_file.id,
                Resume.owner_user_id == actor.id,
            )
        )
        visible = owner_resume_id is not None
    if not visible and stored_file.category == "jd" and actor.role == "hr":
        owner_project_id = await db.scalar(
            select(RecruitmentProject.id).where(
                RecruitmentProject.jd_file_id == stored_file.id,
                RecruitmentProject.owner_user_id == actor.id,
            )
        )
        visible = owner_project_id is not None
    if not visible and stored_file.category == "resume" and actor.role == "hr":
        owner_candidate_id = await db.scalar(
            select(RecruitmentCandidate.id)
            .join(
                RecruitmentProject,
                RecruitmentProject.id == RecruitmentCandidate.project_id,
            )
            .where(
                RecruitmentCandidate.file_id == stored_file.id,
                RecruitmentProject.owner_user_id == actor.id,
            )
        )
        visible = owner_candidate_id is not None
    if not visible:
        raise APIError(404, "RESOURCE_NOT_OWNED", "文件不存在")
    return stored_file


async def log_access(
    db: AsyncSession,
    stored_file: StoredFile,
    actor: User,
    action: Literal["preview", "download"],
    request_id: str,
) -> None:
    db.add(
        FileAccessLog(
            file_id=stored_file.id,
            user_id=actor.id,
            action=action,
            request_id=request_id,
        )
    )
    await db.commit()
