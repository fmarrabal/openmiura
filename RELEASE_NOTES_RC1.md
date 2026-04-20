# openMiura RC1 release notes

Date: 2026-04-17

## Summary

This release candidate closes the final remate cycle defined after the technical audit of the final openMiura bundle.

RC1 consolidates six sprint outcomes:

1. release hygiene and artifact cleanup
2. canonical configuration profiles
3. secure-by-default posture
4. integrated validation and release quality gate
5. targeted refactor of critical monoliths
6. formal release-candidate freeze and product-closure documentation

## What changed since the audited final bundle

### Packaging and release

- release bundles are now expected to be clean, reproducible and easier to validate
- release-quality gate documentation and curated suites are included
- a dedicated RC-freeze script is included for creating a clean release-candidate bundle
- stale packaging and report artifacts are removed from the source tree snapshot

### Configuration and security

- configuration profiles are documented and grouped under `ops/env/`
- secure-by-default posture is the baseline expectation for release usage
- `openmiura doctor` is part of the documented go/no-go path

### Documentation and operator handoff

- new RC docs define support scope, quickstart, known limitations and closure criteria
- the installation and production guides now point to the RC material
- the enterprise alpha guide now uses the explicit config path `configs/openmiura.yaml`

### Source-tree cleanup

- removed duplicated config residue under `configs/configs/`
- removed generated `openmiura.egg-info/` from the frozen bundle
- removed captured report logs from the frozen bundle
- removed runtime voice assets from the frozen bundle

## Validated in this RC freeze

- documentation and packaging regression tests for Sprint 6
- alpha/release documentation link consistency
- explicit RC docs presence and references
- release-tree cleanliness checks for files that should not ship in the frozen candidate

## Known limitations

- this container does not provide the Python `build` package, so wheel/sdist generation cannot be fully revalidated here
- UI/admin/browser walkthroughs are validated through existing automated suites rather than an interactive browser session in this environment
- deeper structural refactors remain future work, but they are no longer release-blocking for RC1

## Intended positioning

RC1 is suitable for:

- controlled pilots
- controlled internal pilots
- investor/customer demos in managed environments
- technical evaluation of the governed-runtime thesis

RC1 is **not** yet positioned as a general-availability release.
