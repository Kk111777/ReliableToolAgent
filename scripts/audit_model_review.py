"""Recount a public model-review record without raw trajectories or model calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


FIELDS = (
    "reference_write_occurrences",
    "successful_exact_reference_matches",
    "unmatched_reference_occurrences_at_final_user",
    "final_user_terminal_marker",
    "assistant_observed_after_terminal_user",
    "terminal_with_unmatched_reference_occurrences",
)
COUNTS = FIELDS[:3]
FLAGS = FIELDS[4:]
CLIPS = [f"B{i:02d}" for i in range(1, 13)] + [f"S{i:02d}" for i in range(1, 9)]


def payload_digest(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


@dataclass(frozen=True)
class ModelReviewAudit:
    record: dict

    @classmethod
    def load(cls, path: Path) -> ModelReviewAudit:
        return cls(json.loads(path.read_text(), object_pairs_hook=unique_object))

    @staticmethod
    def validate_labels(labels: dict) -> None:
        if not isinstance(labels, dict) or set(labels) != set(FIELDS):
            raise ValueError("unexpected review label fields")
        for field in COUNTS:
            value = labels[field]
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("invalid count; Boolean is not a count")
        for field in FLAGS:
            if labels[field] is not None and type(labels[field]) is not bool:
                raise ValueError("invalid Boolean label")
        if labels[FIELDS[3]] not in (None, "NONE", "STOP", "TRANSFER"):
            raise ValueError("invalid terminal marker")

    def recompute(self) -> dict:
        record = self.record
        expected_fields = {
            "schema_version",
            "review_material_version",
            "measurement_version",
            "reviewer",
            "selection",
            "source_sha256",
            "rows",
            "summary",
            "payload_sha256",
        }
        if not isinstance(record, dict) or set(record) != expected_fields:
            raise ValueError("unexpected public record fields")
        if type(record["schema_version"]) is not int or record["schema_version"] != 1:
            raise ValueError("unknown review schema")
        if type(record["review_material_version"]) is not int or record["review_material_version"] != 3:
            raise ValueError("unknown review material version")
        if record["measurement_version"] != "retail-reference-events-v2":
            raise ValueError("unknown review protocol")
        if record["payload_sha256"] != payload_digest({k: v for k, v in record.items() if k != "payload_sha256"}):
            raise ValueError("payload digest mismatch")
        reviewer = record["reviewer"]
        if payload_digest(reviewer) != payload_digest(
            {
                "type": "separate_codex_conversation",
                "exact_model_version": "unknown",
                "reports_hidden_key_seen": False,
                "reports_analyzer_outputs_seen": False,
                "automatic_project_context_disclosed": True,
                "strict_independent_blind_review": False,
                "human_annotation": False,
            }
        ):
            raise ValueError("unsupported reviewer provenance or independence claim")
        if record["selection"] != {"method": "purposeful", "development_clips": 12, "primary_clips": 8}:
            raise ValueError("unexpected selection; no population accuracy claim")
        sources = record["source_sha256"]
        if not isinstance(sources, dict) or set(sources) != {
            "first_reply",
            "reviewer_archive",
            "prelabels",
            "measurement_source",
            "review_instructions",
        }:
            raise ValueError("missing source fingerprints")
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in sources.values()):
            raise ValueError("invalid source fingerprint")
        rows = record["rows"]
        if not isinstance(rows, list) or [row.get("clip_id") for row in rows if isinstance(row, dict)] != CLIPS:
            raise ValueError("missing, duplicate, or reordered clip identities")
        differences = []
        agreements = {field: 0 for field in FIELDS}
        known_agreements = known_compared = 0
        uncertain = []
        for row in rows:
            if set(row) != {"clip_id", "reference_available", "first_labels", "protocol_labels", "uncertain"}:
                raise ValueError("unexpected excerpt fields")
            if type(row["reference_available"]) is not bool or type(row["uncertain"]) is not bool:
                raise ValueError("invalid availability or uncertainty flag")
            first, protocol = row["first_labels"], row["protocol_labels"]
            self.validate_labels(first)
            self.validate_labels(protocol)
            if not row["reference_available"] and any(protocol[field] is not None for field in COUNTS):
                raise ValueError("missing references cannot yield protocol counts")
            if row["reference_available"] and any(protocol[field] is None for field in COUNTS[:2]):
                raise ValueError("available references need full-trace counts")
            if row["reference_available"] and protocol[COUNTS[1]] > protocol[COUNTS[0]]:
                raise ValueError("matches exceed reference occurrences")
            if protocol[FIELDS[3]] in ("STOP", "TRANSFER"):
                if type(protocol[FLAGS[0]]) is not bool:
                    raise ValueError("terminal User requires an activity flag")
                missing = protocol[COUNTS[2]]
                if row["reference_available"]:
                    if missing is None or missing > protocol[COUNTS[0]] or protocol[FLAGS[1]] is not (missing > 0):
                        raise ValueError("inconsistent terminal reference counts")
                elif missing is not None or protocol[FLAGS[1]] is not None:
                    raise ValueError("missing references cannot yield terminal completion")
            if protocol[FIELDS[3]] == "NONE" and (
                protocol[COUNTS[2]] is not None or protocol[FLAGS[0]] is not None or protocol[FLAGS[1]] is not False
            ):
                raise ValueError("nonterminal User cannot yield terminal counts")
            if row["uncertain"]:
                uncertain.append(row["clip_id"])
            for field in FIELDS:
                same = type(first[field]) is type(protocol[field]) and first[field] == protocol[field]
                agreements[field] += int(same)
                if row["reference_available"]:
                    known_compared += 1
                    known_agreements += int(same)
                if not same:
                    differences.append(
                        {
                            "clip_id": row["clip_id"],
                            "field": field,
                            "first_label": first[field],
                            "protocol_label": protocol[field],
                        }
                    )
        summary = {
            "clips": len(rows),
            "labels_compared": len(rows) * len(FIELDS),
            "labels_agreeing": sum(agreements.values()),
            "labels_disagreeing": len(differences),
            "known_reference_labels_compared": known_compared,
            "known_reference_labels_agreeing": known_agreements,
            "uncertain_clips": uncertain,
            "agreements_by_field": agreements,
            "differences": differences,
        }
        if payload_digest(record["summary"]) != payload_digest(summary):
            raise ValueError("recorded summary differs from row recount")
        return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    summary = ModelReviewAudit.load(args.input).recompute()
    print(
        json.dumps(
            {
                "passed": True,
                **summary,
                "boundary": "Compact-record consistency, not raw-semantic authentication or accuracy.",
            }
        )
    )


if __name__ == "__main__":
    main()
