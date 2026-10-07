"""作文 HTTP 适配器；ROUTES 可直接并入统一 registry，不复制领域行为。"""

import mimetypes

from . import essays, essays_ocr

ROUTES = {}


def route(method, path):
    def register(handler):
        ROUTES[(method, path)] = handler
        return handler
    return register


@route("GET", "/api/essays")
def list_prompts(vault, q, body):
    return essays.list_prompts(vault, q.get("q", ""), q.get("classification_id", ""),
                               q.get("offset", 0), q.get("limit", 60))


@route("GET", "/api/essay/prompt")
def prompt(vault, q, body):
    return essays.prompt_detail(vault, q.get("id", ""))


@route("POST", "/api/essay/prompt")
def create_prompt(vault, q, body):
    return essays.create_prompt(vault, body.get("title"), body.get("text"), body.get("requirements", ""),
                                source="web", metadata=body.get("metadata"))


@route("GET", "/api/essay/attempt")
def attempt(vault, q, body):
    return essays.attempt_detail(vault, q.get("id", ""))


@route("POST", "/api/essay/attempt")
def create_attempt(vault, q, body):
    return essays.create_attempt(vault, body.get("prompt_id"), body.get("title", ""),
                                 source="web", metadata=body.get("metadata"))


@route("GET", "/api/essay/version")
def version(vault, q, body):
    return essays.version_detail(vault, q.get("id", ""))


@route("POST", "/api/essay/version")
def create_version(vault, q, body):
    return essays.create_version(vault, body.get("attempt_id"), body.get("images"),
                                 source="web", metadata=body.get("metadata"))


@route("POST", "/api/essay/ocr")
def ocr(vault, q, body):
    return essays_ocr.start_ocr(vault, body.get("version_id", body.get("id", "")))


@route("POST", "/api/essay/correct")
def correct(vault, q, body):
    return essays.correct_version(vault, body.get("version_id", body.get("id", "")),
                                  body.get("text"), body.get("revision"))


@route("POST", "/api/essay/confirm")
def confirm(vault, q, body):
    return essays.confirm_version(vault, body.get("version_id", body.get("id", "")),
                                  body.get("text"), body.get("revision"))


@route("POST", "/api/essay/evaluation")
def evaluate(vault, q, body):
    return essays.add_evaluation(vault, body.get("version_id"), body.get("total_score"),
                                 body.get("summary", ""), body.get("strengths"), body.get("issues"),
                                 body.get("suggestions"), body.get("dimensions"), evaluator=body.get("evaluator", "human"),
                                 source="web", model=body.get("model", ""), metadata=body.get("metadata"))


@route("POST", "/api/essay/evaluation/adopt")
def adopt(vault, q, body):
    return essays.adopt_evaluation(vault, body.get("version_id"), body.get("evaluation_id"))


@route("POST", "/api/essay/note")
def note(vault, q, body):
    return essays.add_note(vault, body.get("attempt_id"), body.get("text"), body.get("version_id"),
                           source="web", metadata=body.get("metadata"))


@route("GET", "/api/essay/classifications")
def classifications(vault, q, body):
    return {"classifications": essays.list_classifications(vault)}


@route("POST", "/api/essay/classification")
def create_classification(vault, q, body):
    return essays.create_classification(vault, body.get("name"), body.get("group", ""),
                                        source="web", metadata=body.get("metadata"))


@route("POST", "/api/essay/classify")
def classify(vault, q, body):
    return essays.classify(vault, body.get("target_type"), body.get("target_id"), body.get("classification_ids"),
                           body.get("names"), source="web", metadata=body.get("metadata"))


@route("GET", "/api/essay/compare")
def compare(vault, q, body):
    return essays.compare_versions(vault, q.get("before_id", ""), q.get("after_id", ""))


@route("GET", "/api/essay/image")
def image(vault, q, body):
    from .http_registry import Raw
    path = essays.version_image_path(vault, q.get("version_id", ""), q.get("image", ""))
    with open(path, "rb") as handle:
        return Raw(handle.read(), mimetypes.guess_type(path)[0] or "application/octet-stream",
                   {"Cache-Control": "private, no-store"})
