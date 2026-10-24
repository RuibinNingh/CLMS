from pydantic import ValidationError

from backend.app.db.models import Attempt
from backend.app.errors import DomainError

from . import categories, evaluations, prompts, versions
from .common import cas, get
from .schemas import SCHEMAS


def parsed(kind, payload):
    if kind not in SCHEMAS:
        raise DomainError("validation_error", "不支持的提案类型")
    try:
        model = SCHEMAS[kind].model_validate(payload)
        # Update schemas retain explicit null fields (e.g. clearing rubric).
        return model.model_dump(mode="json", exclude_unset=kind in ("category", "prompt"))
    except ValidationError as error:
        raise DomainError("validation_error", "字段校验失败", 422, error.errors(include_context=False)) from error


def validate(session, kind, payload, actor):
    payload = parsed(kind, payload)
    if kind == "reflection":
        target = get(session, Attempt, payload["attempt_id"])
        cas(target, payload["expected_revision"])
        return {"attempt_id": target.id, "expected_revision": target.revision, "before": {"reflection": target.reflection}}
    methods = {"category": categories.validate, "prompt": prompts.validate,
               "submission": versions.validate_submission, "revision": versions.validate_revision,
               "evaluation": evaluations.validate}
    return methods[kind](session, payload, actor)


def apply(session, kind, payload, actor):
    payload = parsed(kind, payload)
    methods = {"category": categories.apply, "prompt": prompts.apply, "submission": versions.submission,
               "revision": versions.revision, "evaluation": evaluations.apply, "reflection": versions.reflection}
    return methods[kind](session, payload, actor)
