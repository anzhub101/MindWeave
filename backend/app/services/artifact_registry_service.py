from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import ArtifactRecord, PromotionRecord
from app.models.artifacts import ArtifactPromotion, RegistryArtifact, SynthesizedProgramBundle


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


DEFAULT_EVALUATIONS = [
    {
        "artifact_id": "output_present",
        "version": "1.0.0",
        "name": "Output Present",
        "description": "Ensures that node execution returns a non-empty structured payload.",
        "payload": {
            "evaluation_id": "output_present",
            "description": "Validate that the node produced output.",
            "evaluator_type": "rule_based",
            "target_operation_types": ["generate", "analyze", "aggregate", "synthesize"],
            "success_rule": "output_present",
        },
    },
    {
        "artifact_id": "verification_gate",
        "version": "1.0.0",
        "name": "Verification Gate",
        "description": "Ensures verify nodes resolve to a terminal verification status.",
        "payload": {
            "evaluation_id": "verification_gate",
            "description": "Validate that verification nodes produce passed or failed status.",
            "evaluator_type": "rule_based",
            "target_operation_types": ["verify"],
            "success_rule": "verification_status_present",
        },
    },
    {
        "artifact_id": "final_output_schema",
        "version": "1.0.0",
        "name": "Final Output Schema",
        "description": "Ensures the final synthesis includes the required output schema keys.",
        "payload": {
            "evaluation_id": "final_output_schema",
            "description": "Validate that the final output contains required schema fields.",
            "evaluator_type": "rule_based",
            "target_operation_types": ["synthesize"],
            "success_rule": "final_output_required_fields_present",
        },
    },
    {
        "artifact_id": "reasoning_consistency_llm",
        "version": "1.0.0",
        "name": "Reasoning Consistency LLM",
        "description": "Uses an LLM judge to assess whether the node output is coherent and grounded.",
        "payload": {
            "evaluation_id": "reasoning_consistency_llm",
            "description": "Ask an LLM evaluator for a pass/fail consistency judgement.",
            "evaluator_type": "llm_based",
            "target_operation_types": ["analyze", "aggregate", "synthesize"],
            "prompt_template": (
                "You are an evaluation function for MindWeave. "
                "Assess whether the node output is coherent, grounded in the provided evidence, "
                "and materially responsive to the prompt. "
                "Return strict JSON with keys: passed (boolean), message (string)."
            ),
        },
    },
]


class ArtifactRegistryService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def ensure_seeded(self) -> None:
        if self.db.query(ArtifactRecord.id).first() is not None:
            return

        mappings = {
            "program": self.settings.artifact_root / "programs",
            "policy": self.settings.artifact_root / "policies",
            "template": self.settings.artifact_root / "templates",
            "schema": self.settings.artifact_root / "schemas",
        }
        for kind, directory in mappings.items():
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.json")):
                payload = json.loads(path.read_text(encoding="utf-8"))
                record = self._build_registry_artifact(kind, payload, path)
                self.upsert(record, commit=False)

        for payload in DEFAULT_EVALUATIONS:
            self.upsert(
                RegistryArtifact(
                    kind="evaluation",
                    artifact_id=payload["artifact_id"],
                    version=payload["version"],
                    name=payload["name"],
                    description=payload["description"],
                    payload=payload["payload"],
                    source="system",
                    status="active",
                ),
                commit=False,
            )

        self.db.commit()

    def list(self, kind: str) -> list[RegistryArtifact]:
        kind = self._normalize_kind(kind)
        self.ensure_seeded()
        records = (
            self.db.query(ArtifactRecord)
            .filter(ArtifactRecord.kind == kind)
            .order_by(ArtifactRecord.artifact_id.asc(), ArtifactRecord.version.desc())
            .all()
        )
        return [self._to_model(record) for record in records]

    def get(self, kind: str, artifact_id: str, version: str | None = None) -> RegistryArtifact:
        kind = self._normalize_kind(kind)
        self.ensure_seeded()
        query = self.db.query(ArtifactRecord).filter(
            ArtifactRecord.kind == kind,
            ArtifactRecord.artifact_id == artifact_id,
        )
        if version is not None:
            query = query.filter(ArtifactRecord.version == version)
        else:
            query = query.order_by(ArtifactRecord.version.desc())

        record = query.first()
        if record is None:
            raise ValueError(f"{kind} artifact {artifact_id} not found.")
        return self._to_model(record)

    def upsert(self, artifact: RegistryArtifact, commit: bool = True) -> RegistryArtifact:
        artifact.kind = self._normalize_kind(artifact.kind)
        existing = (
            self.db.query(ArtifactRecord)
            .filter(
                ArtifactRecord.kind == artifact.kind,
                ArtifactRecord.artifact_id == artifact.artifact_id,
                ArtifactRecord.version == artifact.version,
            )
            .one_or_none()
        )
        if existing is None:
            existing = ArtifactRecord(
                kind=artifact.kind,
                artifact_id=artifact.artifact_id,
                version=artifact.version,
                name=artifact.name,
                description=artifact.description,
                payload=artifact.payload,
                status=artifact.status,
                source=artifact.source,
                justification=artifact.justification,
            )
            self.db.add(existing)
        else:
            existing.name = artifact.name
            existing.description = artifact.description
            existing.payload = artifact.payload
            existing.status = artifact.status
            existing.source = artifact.source
            existing.justification = artifact.justification
        if commit:
            self.db.commit()
            self.db.refresh(existing)
        return self._to_model(existing)

    def promote(self, kind: str, artifact_id: str, version: str, justification: str) -> RegistryArtifact:
        kind = self._normalize_kind(kind)
        self.ensure_seeded()
        records = (
            self.db.query(ArtifactRecord)
            .filter(ArtifactRecord.kind == kind, ArtifactRecord.artifact_id == artifact_id)
            .all()
        )
        target = next((record for record in records if record.version == version), None)
        if target is None:
            raise ValueError(f"{kind} artifact {artifact_id}@{version} not found.")
        for record in records:
            if record.id != target.id and record.status == "promoted":
                record.status = "archived"
        target.status = "promoted"
        self.db.add(
            PromotionRecord(
                kind=kind,
                artifact_id=artifact_id,
                version=version,
                justification=justification,
            )
        )
        self.db.commit()
        self.db.refresh(target)
        return self._to_model(target)

    def list_versions(self, kind: str, artifact_id: str) -> list[RegistryArtifact]:
        kind = self._normalize_kind(kind)
        self.ensure_seeded()
        records = (
            self.db.query(ArtifactRecord)
            .filter(
                ArtifactRecord.kind == kind,
                ArtifactRecord.artifact_id == artifact_id,
            )
            .order_by(ArtifactRecord.version.desc(), ArtifactRecord.updated_at.desc())
            .all()
        )
        if not records:
            raise ValueError(f"{kind} artifact {artifact_id} not found.")
        return [self._to_model(record) for record in records]

    def list_promotions(self, kind: str, artifact_id: str) -> list[ArtifactPromotion]:
        kind = self._normalize_kind(kind)
        self.ensure_seeded()
        if (
            self.db.query(ArtifactRecord.id)
            .filter(
                ArtifactRecord.kind == kind,
                ArtifactRecord.artifact_id == artifact_id,
            )
            .first()
            is None
        ):
            raise ValueError(f"{kind} artifact {artifact_id} not found.")
        records = (
            self.db.query(PromotionRecord)
            .filter(
                PromotionRecord.kind == kind,
                PromotionRecord.artifact_id == artifact_id,
            )
            .order_by(PromotionRecord.created_at.desc(), PromotionRecord.version.desc())
            .all()
        )
        return [
            ArtifactPromotion(
                kind=record.kind,
                artifact_id=record.artifact_id,
                version=record.version,
                justification=record.justification,
                promoted_at=record.created_at,
            )
            for record in records
        ]

    def register_bundle(self, bundle: SynthesizedProgramBundle) -> list[RegistryArtifact]:
        self.ensure_seeded()
        artifacts: list[RegistryArtifact] = []

        artifacts.append(
            self.upsert(
                RegistryArtifact(
                    kind="program",
                    artifact_id=bundle.program.program_id,
                    version=bundle.program.version,
                    name=bundle.program.program_id,
                    description=bundle.program.goal or f"Reasoning program for {bundle.domain}.",
                    payload=bundle.program.model_dump(mode="json", by_alias=True),
                    source="generated",
                ),
                commit=False,
            )
        )
        artifacts.append(
            self.upsert(
                RegistryArtifact(
                    kind="template",
                    artifact_id=bundle.template_id,
                    version=bundle.program.version,
                    name=bundle.template_name,
                    description=f"Generated template for {bundle.domain}.",
                    payload={
                        "template_id": bundle.template_id,
                        "name": bundle.template_name,
                        "description": f"Generated template for {bundle.domain}.",
                        "reasoning_program": bundle.program.model_dump(mode="json", by_alias=True),
                        "policy": bundle.program.policy,
                        "budgets": bundle.program.budget.model_dump(mode="json"),
                        "verification_rules": {
                            "guarded_nodes": [
                                {"node_id": node.id, "guarded_by": node.guarded_by}
                                for node in bundle.program.nodes
                                if node.guarded_by
                            ]
                        },
                        "output_schema": bundle.program.output_schema,
                    },
                    source="generated",
                ),
                commit=False,
            )
        )

        self.db.commit()
        return artifacts

    @staticmethod
    def _build_registry_artifact(kind: str, payload: dict, path: Path) -> RegistryArtifact:
        artifact_id = (
            payload.get("program_id")
            or payload.get("policy_id")
            or payload.get("template_id")
            or payload.get("title")
            or path.stem
        )
        version = payload.get("version") or payload.get("program_version") or "1.0.0"
        name = payload.get("name") or payload.get("template_id") or payload.get("program_id") or artifact_id
        description = payload.get("description") or payload.get("goal") or f"{kind.title()} artifact {artifact_id}"
        return RegistryArtifact(
            kind=kind,
            artifact_id=str(artifact_id),
            version=str(version),
            name=str(name),
            description=str(description),
            payload=payload,
            source="static",
            status="active",
        )

    @staticmethod
    def _to_model(record: ArtifactRecord) -> RegistryArtifact:
        return RegistryArtifact(
            kind=record.kind,
            artifact_id=record.artifact_id,
            version=record.version,
            name=record.name,
            description=record.description,
            payload=record.payload,
            status=record.status,
            source=record.source,
            justification=record.justification,
            created_at=record.created_at or record.updated_at or utcnow(),
            updated_at=record.updated_at or record.created_at or utcnow(),
        )

    @staticmethod
    def _normalize_kind(kind: str) -> str:
        normalized = kind.strip().lower()
        if normalized.endswith("ies"):
            return normalized[:-3] + "y"
        if normalized.endswith("s"):
            return normalized[:-1]
        return normalized
