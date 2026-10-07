"""作文专用投影；正式事实只由 Ledger 重放，和普通错题调度隔离。"""

import copy


class EssayProjection:
    def _init_essays(self):
        self.essay_prompts = {}
        self.essay_attempts = {}
        self.essay_versions = {}
        self.essay_evaluations = {}
        self.essay_notes = {}
        self.essay_classifications = {}

    @staticmethod
    def _essay_record(value, commit):
        return dict(copy.deepcopy(value), created_at=commit["created_at"],
                    updated_at=commit["created_at"], commit_id=commit["commit_id"],
                    source=value.get("source") or commit["source"], last_seq=commit["seq"])

    @staticmethod
    def _essay_touch(record, commit):
        record.update(updated_at=commit["created_at"], last_seq=commit["seq"])

    def _on_essay_prompt_create(self, payload, commit):
        record = self._essay_record(payload["prompt"], commit)
        record.update(attempt_ids=[], classification_ids=[])
        self.essay_prompts[record["id"]] = record

    def _on_essay_attempt_create(self, payload, commit):
        record = self._essay_record(payload["attempt"], commit)
        record.update(version_ids=[], note_ids=[], classification_ids=[])
        self.essay_attempts[record["id"]] = record
        prompt = self.essay_prompts.get(record["prompt_id"])
        if prompt:
            prompt["attempt_ids"].append(record["id"])
            self._essay_touch(prompt, commit)

    def _on_essay_version_create(self, payload, commit):
        record = self._essay_record(payload["version"], commit)
        record.update(status="uploaded", revision=1, raw_ocr_text="", raw_ocr_response="",
                      corrected_text="", text="", uncertainties=[], evaluation_ids=[], note_ids=[],
                      classification_ids=[], adopted_evaluation_id=None, error="", ocr_token=None,
                      ocr_attempts=0, confirmed_at=None)
        self.essay_versions[record["id"]] = record
        attempt = self.essay_attempts.get(record["attempt_id"])
        if attempt:
            attempt["version_ids"].append(record["id"])
            self._essay_touch(attempt, commit)

    def _essay_version_event(self, payload, commit, **changes):
        record = self.essay_versions.get(payload.get("version_id"))
        if record:
            record.update(copy.deepcopy(changes))
            record["revision"] += 1
            self._essay_touch(record, commit)

    def _on_essay_version_ocr_start(self, payload, commit):
        record = self.essay_versions.get(payload.get("version_id"))
        if record:
            self._essay_version_event(payload, commit, status="ocr_running", error="",
                                      ocr_token=payload["token"], ocr_attempts=record["ocr_attempts"] + 1)

    def _on_essay_version_ocr_result(self, payload, commit):
        self._essay_version_event(payload, commit, status="proofreading", error="", ocr_token=None,
                                  raw_ocr_text=payload["text"], corrected_text=payload["text"],
                                  raw_ocr_response=payload.get("raw_response", ""),
                                  uncertainties=payload.get("uncertainties", []),
                                  ocr_model=payload.get("model", ""))

    def _on_essay_version_ocr_failed(self, payload, commit):
        self._essay_version_event(payload, commit, status="ocr_failed", error=payload["error"], ocr_token=None)

    def _on_essay_version_correct(self, payload, commit):
        self._essay_version_event(payload, commit, status="proofreading", corrected_text=payload["text"])

    def _on_essay_version_confirm(self, payload, commit):
        self._essay_version_event(payload, commit, status="confirmed", text=payload["text"],
                                  corrected_text=payload["text"], confirmed_at=commit["created_at"], error="")

    def _on_essay_evaluation_add(self, payload, commit):
        record = self._essay_record(payload["evaluation"], commit)
        self.essay_evaluations[record["id"]] = record
        version = self.essay_versions.get(record["version_id"])
        if version:
            version["evaluation_ids"].append(record["id"])
            self._essay_touch(version, commit)

    def _on_essay_evaluation_adopt(self, payload, commit):
        version = self.essay_versions.get(payload.get("version_id"))
        if version:
            version["adopted_evaluation_id"] = payload["evaluation_id"]
            self._essay_touch(version, commit)

    def _on_essay_note_add(self, payload, commit):
        record = self._essay_record(payload["note"], commit)
        self.essay_notes[record["id"]] = record
        attempt = self.essay_attempts.get(record["attempt_id"])
        if attempt:
            attempt["note_ids"].append(record["id"])
            self._essay_touch(attempt, commit)
        version = self.essay_versions.get(record.get("version_id"))
        if version:
            version["note_ids"].append(record["id"])
            self._essay_touch(version, commit)

    def _on_essay_classification_create(self, payload, commit):
        record = self._essay_record(payload["classification"], commit)
        self.essay_classifications[record["id"]] = record

    def _on_essay_classification_assign(self, payload, commit):
        table = getattr(self, "essay_" + payload["target_type"] + "s", {})
        target = table.get(payload["target_id"])
        if target:
            target["classification_ids"] = list(dict.fromkeys(
                target["classification_ids"] + payload["classification_ids"]))
            self._essay_touch(target, commit)
