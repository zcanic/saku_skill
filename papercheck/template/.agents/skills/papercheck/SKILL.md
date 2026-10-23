---
name: papercheck
description: Track and fact-check a Markdown research manuscript using immutable papercheck snapshots, atomic propositions, precise source evidence and a paragraph-to-evidence inspection website. Use for manuscript-wide or section-scoped fact checks, evidence audits, revision tracking, or updating an existing papercheck workspace.
---

# Papercheck

Work in the manuscript workspace containing PROJECT.md and paper.md. In the tool development repository, scaffold a separate workspace first; never initialize the developer repository as a paper. Read PROJECT.md, AGENTS.md and the applicable workflow files in that workspace. This project-level skill requires the papercheck Python package, not a model service or a specific agent harness.

## Evidence-first loop

1. Read workflow/01-intake.md and 02-text-and-claims.md. Establish requested scope and edit authority. Default manuscript access is read-only.
2. Obtain fresh `python -m papercheck context --output context.json`. Read every in-scope statement, not just numbers; split compound statements into independently checkable claims. Preserve exact UTF-8 ranges, unknowns, exclusions and untracked material.
3. Read workflow/03-evidence-and-checks.md and 05-semantic-contract.md before authoring proposals. Locate evidence in actual study artifacts or source literature with exact quotation and page/line/pointer. Record DOI/URL when verified. A citation or nearby reference alone is not evidence of a specific proposition. Missing material remains a task; never invent quotes, results, identifiers or completed checks.
4. Use explicit relations to inspect local windows and then wider connected claims as required by scope. Reconcile repeated statements, definitions, causal links, qualifiers and numbers against primary artifacts. Distinguish direct contradiction, partial support and absent evidence. Follow the author's requested conflict criterion without inflating uncertainty into an error.
5. Read workflow/04-commit-and-report.md. Validate the proposal, commit, verify, and inspect workflow/report. Re-freeze context if manuscript or CURRENT changes. Do not edit immutable states or index tables directly. Do not call a pending workflow complete.

## Visual inspection

Read workflow/06-visual-inspection.md. Create the inspector once, then export the newly registered snapshot after each checked revision. Explain that the page is a read-only ledger projection and human notes are separate. Preserve unbound/untracked text and historical checks, but use only active checks for current status. Keep Motion selection transitions and evidence collapsed by default.

For new papers, use the generic assets shipped in the package. Never copy another author's manuscript, evidence, local paths, metrics or notes into the template. Source files require configured allowlisted roots. Do not execute evidence code or SQL merely to preview it.

Package or deploy only when the user requests it. Use version ZIP validation and atomic activation/rollback from UPDATE_SOP.md; do not overwrite server notes or credentials. Do not globally install this skill or change user settings without a request.
