from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_max_length=30000)


class PageRef(Strict):
    page_id: str = Field(min_length=1, max_length=80)
    rotation: Literal[0, 90, 180, 270] = 0


class RubricDimension(Strict):
    name: str = Field(min_length=1, max_length=200)
    max_score: float = Field(gt=0)


class Rubric(Strict):
    max_score: float = Field(gt=0)
    criteria: str = ""
    aggregation: Literal["none", "sum"] = "none"
    dimensions: list[RubricDimension] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_sum(self):
        if self.aggregation == "sum" and abs(sum(d.max_score for d in self.dimensions) - self.max_score) > 1e-6:
            raise ValueError("加总评分维度的满分必须等于总满分")
        if len({d.name for d in self.dimensions}) != len(self.dimensions):
            raise ValueError("评分维度名称不能重复")
        return self


class CategoryCreate(Strict):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    language_scope: Literal["zh", "en", "all"] = "all"
    sort_order: int = Field(default=0, ge=-10000, le=10000)


class CategoryChange(Strict):
    action: Literal["create", "update", "archive"]
    category_id: str | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    language_scope: Literal["zh", "en", "all"] | None = None
    sort_order: int | None = Field(default=None, ge=-10000, le=10000)
    archived: bool | None = None


class PromptCreate(Strict):
    title: str = Field(default="", max_length=200)
    language: Literal["zh", "en"]
    instructions: str = ""
    requirements: str = ""
    source_note: str = ""
    category_ids: list[str] = Field(default_factory=list, max_length=100)
    rubric: Rubric | None = None
    materials: list[PageRef] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def has_material(self):
        if not self.instructions.strip() and not self.materials:
            raise ValueError("题目说明或题目附件至少提供一种")
        return self


class PromptChange(Strict):
    action: Literal["create", "update"]
    prompt_id: str | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, max_length=200)
    language: Literal["zh", "en"] | None = None
    instructions: str | None = None
    requirements: str | None = None
    source_note: str | None = None
    category_ids: list[str] | None = Field(default=None, max_length=100)
    rubric: Rubric | None = None
    materials: list[PageRef] | None = Field(default=None, max_length=100)


class Submission(Strict):
    prompt_id: str | None = None
    prompt: PromptCreate | None = None
    inline_categories: list[CategoryCreate] = Field(default_factory=list, max_length=20)
    pages: list[PageRef] = Field(min_length=1, max_length=100)
    written_at: str | None = Field(default=None, max_length=40)
    duration_minutes: int | None = Field(default=None, ge=0, le=10000)
    reflection: str = ""
    change_note: str = ""

    @model_validator(mode="after")
    def one_prompt(self):
        if bool(self.prompt_id) == bool(self.prompt):
            raise ValueError("已有题目ID与新题目二选一")
        if self.inline_categories and not self.prompt:
            raise ValueError("内联分类只能和新题目一起创建")
        return self


class Revision(Strict):
    attempt_id: str
    parent_version_id: str
    pages: list[PageRef] = Field(min_length=1, max_length=100)
    change_note: str = ""


class Reflection(Strict):
    attempt_id: str
    expected_revision: int = Field(ge=1)
    reflection: str


class Coverage(Strict):
    reviewed_page_ids: list[str] = Field(min_length=1, max_length=100)
    scope: Literal["full", "partial"]
    limitations: list[str] = Field(default_factory=list, max_length=30)


class Location(Strict):
    page_id: str
    description: str = Field(min_length=1, max_length=1000)
    bbox: tuple[float, float, float, float] | None = None

    @model_validator(mode="after")
    def valid_bbox(self):
        if self.bbox:
            x0, y0, x1, y1 = self.bbox
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                raise ValueError("位置坐标必须在0–1范围内")
        return self


class Issue(Strict):
    kind: Literal["error", "improvement", "uncertain"]
    dimension: str = Field(min_length=1, max_length=200)
    location: Location
    quote: str | None = None
    reason: str = Field(min_length=1)
    suggestion: str = ""


class DimensionScore(Strict):
    name: str = Field(min_length=1, max_length=200)
    value: float = Field(ge=0)
    max_value: float = Field(gt=0)

    @model_validator(mode="after")
    def in_range(self):
        if self.value > self.max_value:
            raise ValueError("分项分数不能超过满分")
        return self


class Score(Strict):
    value: float = Field(ge=0)
    max_value: float = Field(gt=0)
    rubric_snapshot: Rubric
    dimensions: list[DimensionScore] = Field(default_factory=list, max_length=30)


class EvaluationInput(Strict):
    schema_version: Literal[1] = 1
    version_id: str
    expected_manifest_hash: str = Field(min_length=64, max_length=64)
    expected_prompt_snapshot_hash: str = Field(min_length=64, max_length=64)
    coverage: Coverage
    summary: str = Field(min_length=1)
    strengths: list[str] = Field(default_factory=list, max_length=100)
    score: Score | None = None
    issues: list[Issue] = Field(default_factory=list, max_length=200)
    next_actions: list[str] = Field(default_factory=list, max_length=3)
    commentary_markdown: str = ""
    declared_model: str | None = Field(default=None, max_length=200)
    compared_version_ids: list[str] = Field(default_factory=list, max_length=10)
    supersedes_id: str | None = None


SCHEMAS = {"category": CategoryChange, "prompt": PromptChange, "submission": Submission,
           "revision": Revision, "evaluation": EvaluationInput, "reflection": Reflection}
