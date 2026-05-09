# Policy packs for regulated scientific workflows

The YAML files in this directory describe **policies for openMiura
to enforce on top of regulated scientific workflows**. Each pack is
self-contained and named after the workflow it governs.

## Format

Each pack follows this minimal schema:

```yaml
name: <slug>           # required, lowercase, kebab-case
version: "<semver>"    # required, semantic version
description: <string>  # required, one-line summary

applies_to:
  workflows: [<action-pattern>, ...]  # action prefixes the pack applies to
  scope:                              # optional scope restriction
    environment: [<env>, ...]

rules:
  - id: <slug>                       # required, unique within the pack
    on_action: <action-pattern>      # action this rule matches
    require_approval:                # optional, gates the action behind a signed approval
      role: <approver-role>          # required role of the signer
      meaning: <string>              # required signature meaning
      multi_party: <bool>            # optional, default false
    require_evidence:                # optional, required evidence pack ingredients
      include: [<artefact>, ...]
    deny_without_approval: <bool>    # if true, the action is denied when no gate is signed
    enforce_scope_match:             # optional, scope fields that must be present
      tenant: required|optional
      workspace: required|optional
      environment: required|optional

audit:                               # optional
  log_decisions: <bool>              # default true
  log_overrides: <bool>              # default true
```

The packs are validated against this schema by the test fixture
[`tests/test_regulated_policy_packs.py`](../../../tests/test_regulated_policy_packs.py).
The current policy engine reads YAML in a different (legacy) format;
binding these regulated packs to the engine is on the roadmap. For
now the packs serve as the **authoritative description** of the
governance the operating organisation should expect, and they can
be re-keyed into the engine's format mechanically when that
binding is implemented.

## Available packs

| File | Workflow | Risk class |
|---|---|---|
| [`lab_release.yaml`](lab_release.yaml) | Pharmaceutical batch release with QP signature | High |
| [`sop_review.yaml`](sop_review.yaml) | SOP authoring with two-party approval | Medium |
| [`ooc_investigation.yaml`](ooc_investigation.yaml) | OOS / OOT investigation closure | Medium-High |
| [`deviation_report.yaml`](deviation_report.yaml) | GMP deviation reporting | Medium |
| [`analytical_interpretation.yaml`](analytical_interpretation.yaml) | Analytical assignment under QA approval | Medium |

## Risk class reminder

(See [`mapping_gamp5.md`](../mapping_gamp5.md) for the full table.)

- **Low** — search assistant, FAQ. Logging only.
- **Medium** — drafting, hypothesis ranking. Single-party approval.
- **Medium-High / High** — batch release, OOS closure, clinical
  evidence. Two-party approval, full evidence pack, mandatory
  CAPA reference for closure.
