from __future__ import annotations

from pathlib import Path

from app.models.runtime import GraphReasoningState
from app.services.storage_service import StorageService


class AuditStore:
    def __init__(self, storage_root: Path, storage_service: StorageService | None = None) -> None:
        self.storage_root = storage_root
        self.storage_service = storage_service or StorageService(storage_root=storage_root)

    def snapshot(self, state: GraphReasoningState, label: str) -> Path:
        payload = state.model_dump(mode="json")
        snapshot_dir = self.storage_root / "snapshots" / state.task_id
        existing = sorted(snapshot_dir.glob("*.json")) if snapshot_dir.exists() else []
        relative_path = f"{state.task_id}/{len(existing) + 1:02d}_{label}.json"
        result = self.storage_service.store_json("snapshots", relative_path, payload)
        return result.local_path

    def build_audit_package(self, state: GraphReasoningState) -> dict:
        return {
            "task_id": state.task_id,
            "prompt": state.prompt,
            "program_id": state.program_id,
            "program_version": state.program_version,
            "status": state.status.value,
            "source_documents": [document.model_dump(mode="json") for document in state.source_documents],
            "final_output": state.final_output,
            "final_summary": state.final_summary,
            "grs": state.model_dump(mode="json"),
            "verification_logs": [entry.model_dump(mode="json") for entry in state.verification_logs],
            "review_history": [entry.model_dump(mode="json") for entry in state.review_history],
            "evaluation_logs": [entry.model_dump(mode="json") for entry in state.evaluation_logs],
            "schema_validation_logs": [entry.model_dump(mode="json") for entry in state.schema_validation_logs],
            "event_log": [entry.model_dump(mode="json") for entry in state.logs],
        }

    def persist_audit_package(self, state: GraphReasoningState) -> tuple[dict, Path]:
        package = self.build_audit_package(state)
        result = self.storage_service.store_json("audit_packages", f"{state.task_id}.json", package)
        package["storage_artifacts"] = {
            "backend": self.storage_service.backend,
            "audit_package_path": result.locator,
        }
        if result.bucket and result.key:
            package["storage_artifacts"]["bucket"] = result.bucket
            package["storage_artifacts"]["key"] = result.key
        # Persist the updated package payload after annotating storage metadata.
        result = self.storage_service.store_json("audit_packages", f"{state.task_id}.json", package)
        return package, result.local_path
