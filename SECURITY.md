# Security Policy

## Supported versions

This repository should define exactly which release lines receive security updates.

For an initial baseline, use the following policy:

| Version line | Supported |
| --- | --- |
| main | Yes |
| latest tagged release | Yes |
| older releases | No |

Adjust this table when you begin publishing stable releases.

## Reporting a vulnerability

Please **do not** report security vulnerabilities through public GitHub issues, discussions, or pull requests.

Instead, report them privately to the project maintainers using one of the following channels:

- security email: `security@your-domain.example`
- private vulnerability reporting in GitHub, if enabled
- internal security reporting workflow, if this repository is private

When reporting a vulnerability, include:

- affected component or file
- version / commit hash / branch
- environment and deployment context
- reproduction steps
- expected vs actual behavior
- severity assessment, if known
- proof-of-concept only when necessary and safe

## Response targets

Recommended baseline targets:

- acknowledgement: within **3 business days**
- triage decision: within **7 business days**
- remediation plan or workaround: within **14 business days** for confirmed high-severity issues

These are targets, not guarantees.

## Disclosure policy

The project follows a **coordinated disclosure** model:

1. report privately
2. validate and triage
3. prepare fix or mitigation
4. publish advisory when remediation is ready or risk requires disclosure

Please avoid public disclosure until maintainers have had a reasonable opportunity to investigate and fix the issue.

## Security expectations for contributors

Contributors should:

- avoid committing secrets, credentials, or private certificates
- use `.env.example` instead of real `.env` files
- prefer least privilege when adding new integrations
- keep tenant/workspace isolation intact
- audit any new terminal, subprocess, webhook, or file-handling surface
- add tests for sensitive authorization and policy boundaries

## High-sensitivity areas in openMiura

Pay special attention to:

- admin routes and broker/admin surfaces
- release governance and promotion flows
- canary routing and environment targeting
- voice command confirmation paths
- secrets exposure in overlays and traces
- packaging and artifact publication flows
- extensions and SDK loading mechanisms

## Security hardening recommendations

Before public release or production deployment:

- enable branch protection / rulesets
- require CI checks before merge
- enable secret scanning and push protection
- enable dependency review / Dependabot alerts
- enable code scanning where available
- restrict admin credentials and rotate tokens
- review logs, traces, and stored artifacts for sensitive data handling

## Out of scope for public reports

You may define exclusions here. A sensible starting point is:

- issues requiring privileged internal access not available to real attackers
- self-hosted misconfigurations outside repository defaults
- reports based solely on missing headers without practical impact
- speculative issues without a reproducible path

Adjust as needed.
