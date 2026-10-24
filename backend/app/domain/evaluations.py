from backend.app.db.models import Attempt, Evaluation, Version
from backend.app.errors import require

from .common import get


def validate(session, payload, actor):
    version = get(session, Version, payload["version_id"])
    attempt = get(session, Attempt, version.attempt_id)
    require(not version.voided_at, "state_conflict", "作废稿件不能评价", 409)
    require(payload["expected_manifest_hash"] == version.manifest_hash, "snapshot_conflict", "原稿清单哈希不匹配", 409)
    require(payload["expected_prompt_snapshot_hash"] == attempt.snapshot_hash, "snapshot_conflict", "题目快照哈希不匹配", 409)
    pages = {p["page_id"] for p in version.manifest}
    coverage = payload["coverage"]
    reviewed = set(coverage["reviewed_page_ids"])
    require(len(reviewed) == len(coverage["reviewed_page_ids"]) and reviewed <= pages, "validation_error", "覆盖范围包含错误或重复页面")
    require(coverage["scope"] != "full" or reviewed == pages, "validation_error", "完整评价必须覆盖本稿全部页面")
    require(coverage["scope"] != "partial" or bool(coverage["limitations"]), "validation_error", "部分评价需说明范围限制")
    for issue in payload["issues"]:
        require(issue["location"]["page_id"] in reviewed, "validation_error", "问题位置必须属于已评价页面")
    for identity in payload.get("compared_version_ids", []):
        compared = get(session, Version, identity)
        require(compared.attempt_id == attempt.id and compared.id != version.id, "validation_error", "比较稿需为同次练习的其他稿件")
    if payload.get("supersedes_id"):
        old = get(session, Evaluation, payload["supersedes_id"])
        require(old.version_id == version.id and not old.voided_at, "validation_error", "被修订评价需属于本稿")
    score = payload.get("score")
    if score:
        rubric = attempt.prompt_snapshot["rubric"]
        require(rubric is not None, "validation_error", "题目没有评分标准，请使用无分数评价")
        require(score["rubric_snapshot"] == rubric and score["max_value"] == rubric["max_score"], "snapshot_conflict", "评分标准或满分与题目快照不一致", 409)
        require(score["value"] <= score["max_value"], "validation_error", "分数不能超过满分")
        dims = score["dimensions"]
        require(len({d["name"] for d in dims}) == len(dims), "validation_error", "分项名称不能重复")
        if rubric["aggregation"] == "sum":
            expected = {d["name"]: d["max_score"] for d in rubric["dimensions"]}
            require({d["name"]: d["max_value"] for d in dims} == expected, "validation_error", "分项需与评分标准一致")
            require(abs(sum(d["value"] for d in dims) - score["value"]) < 1e-6, "validation_error", "分项加总需等于总分")
    return {"version_id": version.id, "manifest_hash": version.manifest_hash, "prompt_snapshot_hash": attempt.snapshot_hash,
            "prompt_snapshot": attempt.prompt_snapshot, "manifest": version.manifest}


def apply(session, payload, actor):
    validate(session, payload, actor)
    record = Evaluation(version_id=payload["version_id"], manifest_hash=payload["expected_manifest_hash"],
                        prompt_snapshot_hash=payload["expected_prompt_snapshot_hash"], payload=payload,
                        source=actor, supersedes_id=payload.get("supersedes_id"))
    session.add(record)
    session.flush()
    version = get(session, Version, record.version_id)
    attempt = get(session, Attempt, version.attempt_id)
    return {"id": record.id, "evaluation_id": record.id, "version_id": version.id, "attempt_id": attempt.id,
            "prompt_id": attempt.prompt_id, "path": f"/#/prompt/{attempt.prompt_id}?version={version.id}"}
