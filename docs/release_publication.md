# Stable release publication policy

This guide closes the gap between the RC1 validation checkpoint and the first stable `1.0.0` release with official downloadable artifacts. It also defines the public download story that the README, installation guide, canonical demo, and release notes should all follow.

## 1. Policy

Use a single publication policy:

- **RC / pre-release** entries remain validation checkpoints.
- Stable releases are the first GitHub Releases that carry the official downloadable artifact set.

This policy is intentional for the current line because the RC1 tag is `v1.0.0-rc1` while the package version is already `1.0.0`. Publishing the RC as the canonical wheel/sdist line would create naming ambiguity with the stable `1.0.0` assets.

## 2. What gets attached where

### RC / pre-release

RC releases are for validation, controlled pilots and review.

Use them to publish:

- release notes and support posture
- the standard GitHub source archives
- workflow artifacts from the `release` job when deeper inspection is required

Do **not** treat RC GitHub Release assets as the canonical downloadable package line.

### Stable release

Stable releases are the official downloadable handoff.

Attach these assets to the GitHub Release:

- `openmiura-<version>-py3-none-any.whl`
- `openmiura-<version>.tar.gz`
- `openmiura-<target>-<version>-<digest>.zip`
- `openmiura-<target>-<version>-<digest>.manifest.json`
- `RELEASE_MANIFEST.json`
- `SHA256SUMS.txt`

This is the minimum official artifact set for `1.0.0` and later stable releases.

## 3. Traceability model

Stable publication must be traceable across:

- Git tag
- release commit
- package version in `pyproject.toml`
- package version in `openmiura/__init__.py`
- wheel
- sdist
- reproducible bundle zip
- reproducible bundle manifest
- `RELEASE_MANIFEST.json`
- `SHA256SUMS.txt`

The stable release workflow enforces tag/package-version alignment before uploading official assets.

## 4. Workflow behavior

`.github/workflows/release.yml` now has two modes:

1. **`release.published`**
   - always runs the quality gate
   - always builds and verifies release artifacts
   - uploads workflow artifacts for auditability
   - uploads official assets to GitHub Release **only when the release is stable**

2. **`workflow_dispatch`**
   - can be used for manual rebuild/verification
   - can publish to GitHub Release only when an explicit stable tag such as `v1.0.0` is supplied

## 5. Stable publication procedure

### 5.1 Prepare and validate

Run locally before creating the stable release:

```bash
python -m pip install ".[dev]"
python scripts/run_release_quality_gate.py --include-extended --output-dir reports/quality_gate
python scripts/build_release_artifacts.py --dist-dir dist --tag v1.0.0 --target desktop --strict
python scripts/verify_release_artifacts.py --dist-dir dist
openmiura doctor --config configs/openmiura.yaml
```

### 5.2 Publish

1. Ensure the repository state and documentation are the intended stable state.
2. Create the stable tag `v1.0.0` from the validated commit.
3. Publish the GitHub Release for `v1.0.0`.
4. Let the `release` workflow complete.
5. Confirm that the six official assets are attached to the GitHub Release.

### 5.3 Re-run if needed

If the workflow must be re-run manually for the same stable release, use `workflow_dispatch` with:

- `release_tag = v1.0.0`
- `publish_to_release = true`

The workflow uses `gh release upload --clobber`, so existing assets with the same name are replaced.

## 6. What an external user should download

For a first serious evaluation or installation, or the first external install (recommended), the external user should download:

- the reproducible bundle zip
- the reproducible bundle manifest
- `RELEASE_MANIFEST.json`
- `SHA256SUMS.txt`

The wheel and sdist remain official assets, but they are secondary routes for Python-package-oriented consumers who already manage their own config layout.

## 7. Post-download checks

At minimum verify:

- the release tag is the intended stable tag
- the package filename version matches the stable tag
- `SHA256SUMS.txt` matches the downloaded files
- `RELEASE_MANIFEST.json` lists all required artifact kinds
- the reproducible bundle and its manifest are both present when reproducibility evidence is required

## 8. Decision boundary

Use this rule consistently:

- **RC** = validation checkpoint
- **Stable** = official downloadable artifact line

For the current state of openMiura, `v1.0.0-rc1` stays as the validation checkpoint and `v1.0.0` becomes the first stable GitHub Release with official downloadable assets.

## 9. Public-facing messaging boundary

Use the same wording everywhere:

- `v1.0.0-rc1` validated the line.
- `v1.0.0` is the first stable public release with official downloadable assets.
- the recommended first-time evaluation path is the reproducible bundle plus the installation guide.
- the canonical product proof is the governed runtime demo, not a generic assistant conversation.

Supporting public material:

- [Public narrative](public_narrative.md)
- [Installation](installation.md)
- [Canonical demo](demos/canonical_demo.md)
- [Stable release text pack](media/stable_release_text_pack.md)
