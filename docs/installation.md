# Installation

This guide defines the **official minimum adoption path** for openMiura `1.0.0`. It is written for an external evaluator who wants to reach a serious first boot quickly and then run the canonical governed-runtime demo.

## Official route

**Recommended for first-time users, especially on Windows:**

1. download the **reproducible bundle zip** from the stable GitHub Release;
2. extract it to a short path such as `C:\openmiura` or `~/openmiura`;
3. create a virtual environment;
4. install with `pip install .` from the extracted bundle root;
5. copy `ops/env/local-secure.env` to `.env`;
6. run `openmiura doctor --config configs/openmiura.yaml`;
7. run `openmiura run --config configs/openmiura.yaml`;
8. verify `/health` and `/ui`.

This route is the most coherent one for external adoption because it ships the Python package **plus** the config files, environment profiles, and operational docs needed for a real first start. It is also the route used by the public narrative and media pack.

## Why this is the primary path

- the **wheel** is best for Python/package consumers, but it does not carry the full working tree layout used by `configs/openmiura.yaml`;
- the **sdist** is source-oriented and valid for reproducible Python packaging flows;
- the **reproducible bundle** is the cleanest external handoff for a governed local-first pilot.


## What this install path is preparing you for

The goal of the first install is not only to get `/health` running. It is to prepare you for the [canonical demo](demos/canonical_demo.md), where a sensitive runtime action is blocked by policy, approved by a human, and left behind as evidence.

If you want the shortest public evaluation path, follow this order:

1. install from the bundle;
2. validate with `openmiura doctor`;
3. start the service;
4. run the canonical demo;
5. inspect the walkthrough and screenshot plan.

## 1. Requirements

- Python 3.10, 3.11 or 3.12
- `pip`
- enough permission to bind to `127.0.0.1:8081`
- optional: Ollama running locally if you want a working local LLM immediately

## 2. Windows-first quickstart

### 2.1 Extract to a short path

Use a short folder to avoid path-length problems in Windows Explorer, for example:

```text
C:\openmiura
```

### 2.2 Create the virtual environment

```powershell
cd C:\openmiura
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install .
```

### 2.3 Choose the recommended first-start profile

```powershell
Copy-Item ops\env\local-secure.env .env
```

### 2.4 Validate the install

```powershell
openmiura doctor --config configs/openmiura.yaml
```

Expected minimum outcome:

- config file found
- gateway initializes
- SQLite is writable
- sandbox dir is writable
- `/health` can be served after startup
- an Ollama warning is acceptable if no local model server is running yet

### 2.5 Start the service

```powershell
openmiura run --config configs/openmiura.yaml
```

### 2.6 Confirm the key surfaces

- health: `http://127.0.0.1:8081/health`
- UI: `http://127.0.0.1:8081/ui`
- metrics: `http://127.0.0.1:8081/metrics`

## 3. Linux / macOS quickstart

```bash
cd ~/openmiura
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
cp ops/env/local-secure.env .env
openmiura doctor --config configs/openmiura.yaml
openmiura run --config configs/openmiura.yaml
```

## 4. Secondary artifact routes

### 4.1 Wheel

Use the wheel when you already manage your own config file and want a standard Python install.

```bash
python -m pip install openmiura-1.0.0-py3-none-any.whl
openmiura version
```

For wheel-based installs you must provide your own config path, for example:

```bash
openmiura doctor --config /path/to/openmiura.yaml
openmiura run --config /path/to/openmiura.yaml
```

### 4.2 sdist

Use the sdist when you want a source-oriented Python packaging path.

```bash
python -m pip install openmiura-1.0.0.tar.gz
openmiura version
```

As with the wheel route, you must provide your own config file or work from an extracted source tree.

## 5. Recommended first-start profile

`ops/env/local-secure.env` is the recommended profile for first-time external validation.

It keeps:

- local SQLite storage
- secure-by-default tool posture
- auth/admin/broker complexity out of the way for the first boot
- a clean path to validating `doctor`, `/health` and `/ui`

Other shipped profiles:

- `ops/env/insecure-dev.env`
- `ops/env/secure-default.env`
- `ops/env/local-dev.env`
- `ops/env/demo.env`
- `ops/env/production-like.env`

For the governed secure baseline used after first-start validation:

```bash
cp ops/env/secure-default.env .env
```

## 6. Minimal success checklist

A clean installation is considered successful when all of these are true:

- `openmiura version` prints `1.0.0`
- `openmiura doctor --config configs/openmiura.yaml` exits without critical errors
- `openmiura run --config configs/openmiura.yaml` starts the service
- `GET /health` returns `{"ok": true, ...}`
- `/ui` responds

## 7. Basic failure handling

If `doctor` fails:

- confirm you extracted the full bundle and are running from its root;
- confirm `.env` exists;
- confirm `configs/openmiura.yaml` exists;
- confirm Python can write to `data/` and `data/sandbox/`;
- if the only warning is that Ollama is unreachable, the install path is still valid.

## 8. Release linkage

For stable artifact publication rules, see [Stable release publication policy](release_publication.md).

## 9. Related public docs

- [Public narrative](public_narrative.md)
- [Canonical demo](demos/canonical_demo.md)
- [Canonical walkthrough](walkthroughs/canonical_runtime_governance_walkthrough.md)
- [Screenshot plan](media/screenshot_plan.md)

## 10. Related release docs

- [Self-hosted Enterprise Alpha](enterprise_alpha.md)
- [Alpha release checklist](alpha_release_checklist.md)
- [Release Candidate RC1](release_candidate.md)
- [Release support matrix](release_support_matrix.md)
- [RC1 quickstart](quickstarts/release_candidate.md)
- [Stable release publication policy](release_publication.md)
