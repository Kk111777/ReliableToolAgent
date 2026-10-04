# Measurement review: separate model session

**English** | [简体中文](README.zh-CN.md) · [Project](../../README.md)

A separate Codex conversation reviewed 20 purposefully selected excerpts: 12 from the historical development panel and 8 from retained first attempts in the frozen primary study. It received reviewer instructions, excerpts and an empty form. The first response was saved before comparison with the analyzer author's prelabels.

## First response and comparison

| Scope | Agreement with retained protocol labels |
|---|---|
| All 20 excerpts, six fields each | **117/120** |
| 17 excerpts with available reference actions | **102/102** |
| B08, S02, S06 | One disagreement each: successful reference matches were filled as `0`; the existing protocol uses `null`. |

The [compact record](summary.json) preserves both initial and protocol labels. It includes availability flags, uncertainty, comparison counts and source fingerprints, with no raw messages or business arguments.

The three excerpts have missing reference information and no observed WRITE window. The reviewer interpreted this as zero observed successful matches and marked uncertainty. The instructions did not explicitly specify availability for that count. The retained protocol defines a *reference-match count*, requiring reference information; it keeps `null` even when the observed call list is empty. An available, explicitly empty reference list instead yields `0`.

That clarification was written after receipt of the first response. The first judgments, original reviewer archive, prelabels and old experiment scores were preserved. This record does not substitute corrected labels for the first response or claim the reviewer subsequently agreed with the clarification.

## What was checked

The receiving author checked the saved JSON against the conversation's first final response, rejoined all 20 excerpts to retained source hashes, and recounted the six protocol fields from call/response windows and terminal markers. The public command below checks the compact record's schema, payload hash and row-derived counts; it cannot authenticate the unseen raw evidence or the reviewer's context.

```bash
.venv/bin/python scripts/audit_model_review.py \
  --input reports/model-review-v1/summary.json
```

The reviewer reported no exposure to the hidden key or analyzer outputs but disclosed automatically supplied project context. The exact model version is unknown. This is a separate-session model review, not strict independent blind review, independent human annotation or cross-model validation. The selected excerpts are not a random accuracy sample, and label agreement is not measurement accuracy.

The review also noted literal STOP markers accompanying requests to continue, and successful exchanges that do not match return references. These are diagnostic observations; they do not establish official task failure, database state or component causality. [Measurement definitions and limits](../../docs/engineering_v2.md#measurement-v2-retain-partial-completion).
