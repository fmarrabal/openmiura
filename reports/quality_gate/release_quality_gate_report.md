# Release quality gate report

- Generated at: 2026-04-18T08:18:03.840528+00:00
- Python: 3.11.15
- Platform: Windows-10-10.0.26200-SP0
- Collected tests: 520 across 172 files
- Required gate passed: True
- Full release gate passed: False

## Required suites

- Suite files: 15
- Command status: True
- Group count: 3
- First JUnit XML: `C:\Users\fmarr\Documents\openmiuraV2Bundle_tiny_ui - clean - github\reports\quality_gate\junit-required-1.xml`

## Packaging smoke

- Reproducible bundle smoke: True
- Full build stage skipped: False

## Extended suites

- Included: True
- Command status: True
- Group count: 1
- First JUnit XML: `C:\Users\fmarr\Documents\openmiuraV2Bundle_tiny_ui - clean - github\reports\quality_gate\junit-extended-1.xml`

## Doctor and inventory

- Doctor executed: True
- Doctor status: True

## Gate decision

- Required gate passed when doctor, curated suites and packaging smoke are all green.
- Full release gate additionally requires `python -m build` availability and a green artifact verification pass.
