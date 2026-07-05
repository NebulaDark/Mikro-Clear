# Wheel Artifact Validation Plan

> **For agentic workers:** This is a non-deploy validation stage. Do not push, deploy, connect to SELKS, run `systemctl`, or install the wheel into any production venv.

**Goal:** Prove the local wheel artifact contains the package entrypoint modules needed for the future `python -m mikroclear` systemd switch.

**Architecture:** Build the wheel into `/tmp`, validate it as a zip archive, and keep build output out of the repository. The validator checks required runtime modules and the `mikroclear` console script metadata without importing or running the Mikro-Clear runtime.

**Tech Stack:** Python 3.11, setuptools wheel build, zipfile, unittest.

## Global Constraints

- No push, no deploy, no SELKS changes.
- Do not install the wheel into `/opt/mikroclear-venv` in this stage.
- Do not start `app.main()` or the Telegram polling lifecycle.
- Do not connect to RouterOS.
- Keep generated wheel artifacts outside the repository or remove them before commit.

## Validation Commands

Build the wheel locally:

```bash
rm -rf /tmp/mikroclear-wheel-validation
mkdir -p /tmp/mikroclear-wheel-validation
.venv/bin/python -m pip wheel --no-deps --no-build-isolation . -w /tmp/mikroclear-wheel-validation
```

Validate the artifact:

```bash
.venv/bin/python scripts/validate_wheel_artifact.py /tmp/mikroclear-wheel-validation/mikro_clear-0.1.0-py3-none-any.whl
```

Expected:

```text
wheel ok: /tmp/mikroclear-wheel-validation/mikro_clear-0.1.0-py3-none-any.whl
```

The validator requires:

```text
mikroclear/__main__.py
mikroclear/cli.py
mikroclear/app.py
mikroclear/runtime.py
mikroclear = mikroclear.cli:main
```

## Final Verification

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_wheel_artifact_validation
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
git ls-files '*.py' | xargs .venv/bin/python -m py_compile
git grep -n -I -E '(BEGIN (RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY|sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|[0-9]{6,}:[A-Za-z0-9_-]{30,})' -- .
git status --short
```
