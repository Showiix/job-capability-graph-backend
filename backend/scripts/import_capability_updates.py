import argparse
import asyncio
import json
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from anyio import Path as AsyncPath
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.auth.models import User
from app.auth.service import normalize_username
from app.infrastructure.database import SessionFactory
from app.reviews.models import GraphChangeCandidate

SOURCE_VERSION = "xiaotiao-2026-08-30"
BATCH_SIZE = 500
DEFAULT_INPUT = (
    Path(__file__).parents[2]
    / "data"
    / "delivery"
    / "2026-08-30"
    / "capability_updates_enriched.json"
)
CHANGE_TYPES = {
    "技能新增": "skill_added",
    "AI技能新增": "ai_skill_added",
    "技能衰退": "skill_declining",
    "技能权重上升": "weight_increased",
    "技能权重下降": "weight_decreased",
    "升级（加分→必备）": "promoted_to_required",
    "降级（必备→加分）": "demoted_to_bonus",
    "过时技能淘汰": "skill_obsoleted",
}
CONFIDENCE = {"高": Decimal("0.9000"), "中": Decimal("0.7000"), "低": Decimal("0.4000")}


class ImportInputError(Exception):
    pass


def candidate_rows(payload: object, actor_id: UUID) -> list[dict[str, object]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ImportInputError("输入必须包含 jobs 数组")
    rows: list[dict[str, object]] = []
    for job in payload["jobs"]:
        if not isinstance(job, dict) or not isinstance(job.get("changes"), list):
            raise ImportInputError("每个岗位必须包含 changes 数组")
        job_name = job.get("job_name")
        if not isinstance(job_name, str) or not job_name.strip():
            raise ImportInputError("岗位名称不能为空")
        for change in job["changes"]:
            if not isinstance(change, dict):
                raise ImportInputError("能力变化必须是对象")
            skill = change.get("skill")
            source_type = change.get("change_type")
            confidence = change.get("confidence")
            if not isinstance(skill, str) or not skill.strip():
                raise ImportInputError("能力名称不能为空")
            if source_type not in CHANGE_TYPES or confidence not in CONFIDENCE:
                raise ImportInputError(
                    f"不支持的变化类型或置信度: {source_type}/{confidence}"
                )
            change_type = CHANGE_TYPES[source_type]
            candidate_id = uuid5(
                NAMESPACE_URL,
                f"{SOURCE_VERSION}:{job_name}:{skill}:{change_type}",
            )
            evidence = change.get("evidence")
            controls = change.get("controls")
            rows.append(
                {
                    "id": candidate_id,
                    "source_candidate_id": None,
                    "change_type": change_type,
                    "proposed_payload": {
                        "job_name": job_name,
                        "capability_name": skill,
                        "action": change.get("action"),
                        "effect_size": change.get("effect_size"),
                        "source_change_type": source_type,
                        "source_version": SOURCE_VERSION,
                    },
                    "source_snapshot": {
                        "engine": payload.get("engine"),
                        "generated_at": payload.get("generated_at"),
                        "job_summary": job.get("change_summary", {}),
                        "controls": controls if isinstance(controls, dict) else {},
                    },
                    "evidence_summary": evidence if isinstance(evidence, dict) else {},
                    "confidence": CONFIDENCE[confidence],
                    "review_status": "pending",
                    "created_by_user_id": actor_id,
                }
            )
    return rows


async def import_updates(
    path: Path, username: str, *, dry_run: bool
) -> tuple[int, int]:
    try:
        payload = json.loads(await AsyncPath(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ImportInputError(f"无法读取能力演化文件: {path}") from error
    async with SessionFactory() as db:
        actor_id = await db.scalar(
            select(User.id).where(
                User.username_normalized == normalize_username(username),
                User.role == "admin",
                User.is_active.is_(True),
            )
        )
        if actor_id is None:
            raise ImportInputError("--actor 必须是现有 active admin")
        rows = candidate_rows(payload, actor_id)
        if dry_run:
            return len(rows), 0
        inserted = 0
        for start in range(0, len(rows), BATCH_SIZE):
            result = await db.execute(
                insert(GraphChangeCandidate)
                .values(rows[start : start + BATCH_SIZE])
                .on_conflict_do_nothing(index_elements=[GraphChangeCandidate.id])
            )
            inserted += result.rowcount or 0
        await db.commit()
        return len(rows), inserted


def main() -> int:
    parser = argparse.ArgumentParser(description="导入小挑能力演化候选")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        total, inserted = asyncio.run(
            import_updates(args.input, args.actor, dry_run=args.dry_run)
        )
    except ImportInputError as error:
        parser.exit(2, f"error: {error}\n")
    print(f"validated={total} inserted={inserted} skipped={total - inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
