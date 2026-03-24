# openMiura — release, branch protection and security setup

## Files included

- `.github/workflows/release.yml`
- `.github/workflows/dependency-review.yml`
- `.github/dependabot.yml`

## Suggested environments

Create two environments in GitHub:

- `staging`
- `production`

For `production`, require reviewer approval before the release job can proceed.

## Suggested required checks on `main`

- `Validate (Python 3.10)`
- `Validate (Python 3.11)`
- `Validate (Python 3.12)`
- `Package smoke`
- `Reproducible package`
- `Docker smoke`
- `Dependency Review`

## Suggested protection model for `main`

- Require pull requests before merging
- Require 1 approving review
- Dismiss stale approvals
- Require review from CODEOWNERS
- Require status checks above
- Require branches to be up to date before merging
- Block force pushes
- Restrict deletions
- Keep bypass list empty, or admins only for pull requests
- Optional once the repo is stable: require linear history
- Optional for public release maturity: require signed commits
- Optional if CodeQL is enabled: require code scanning results

## Suggested repository security settings

Enable in **Settings → Advanced Security** when available:

- Dependency graph
- Dependabot alerts
- Dependabot security updates
- Secret scanning
- Push protection
- Code scanning (prefer default setup first)
- Private vulnerability reporting

## Suggested release flow

1. Merge to `main` through PR.
2. Wait for CI green.
3. Create and push a version tag like `v0.1.0`.
4. `release.yml` builds wheel, sdist, reproducible package and checksums.
5. The publish job targets the `production` environment and waits for approval.
6. After approval, GitHub Release is created and artifacts are attached.
