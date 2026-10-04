# Usage and cost accounting

**English** | [简体中文](budget_accounting.zh-CN.md) · [Technical appendix](../technical_appendix.md)

This record covers the completed retail cohort. Request/token accounting was retained for reproducibility.

## Frozen primary cohort

This cohort includes 210 formal first attempts and four reused smoke attempts, counted once: 214 attempts and 3747 observed HTTP requests. Known list-price usage totals **RMB 21.929163**; reserving 27 missing-usage requests raises the conservative debit to **RMB 23.0958958**. At the user-confirmed 50% discount these estimates are **RMB 10.9645815** and **RMB 11.5479479**, respectively. They cover this bundle only; earlier preflight and other account activity are excluded. These are estimates, not verified provider invoices.

The generated report separates Agent/User/evaluator requests, known input/output tokens and unknown-usage reserves. Reasoning is already included in output tokens. The manifest's original budget field is historical plan metadata, superseded during execution; it is neither the actual bill nor an authorization to spend that amount.

Source: [compact evidence](../../reports/frozen_study/retail-holdout-v1/public_evidence.json) · [generated report](../../reports/frozen_study/retail-holdout-v1/report.md).
