# Package Importability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare the non-deploy path that makes `python -m mikroclear` importable in the SELKS venv before switching `mikroclear.service` to the package entrypoint.

**Architecture:** Keep the production service and SELKS files unchanged in this stage. Build and inspect a local wheel artifact, then document an explicitly approved future install into the existing `/opt/mikroclear-venv`; the candidate systemd unit can only be used after a read-only importability check succeeds on SELKS.

**Tech Stack:** Python 3.11, setuptools, wheel artifact, unittest, systemd candidate text, SELKS SSH read-only checks.

## Global Constraints

- No push, no deploy, no SELKS file changes.
- Do not run `systemctl`.
- Do not start the real runtime loop.
- No RouterOS connection.
- Do not change the behavior of the existing `mikroclear.service`.
- Production service remains `mikroclear.service`.
- Current production ExecStart remains `/opt/mikroclear-venv/bin/python /usr/local/bin/mikroclear.py` until a separately approved deploy stage.
- Candidate ExecStart remains `/opt/mikroclear-venv/bin/python -m mikroclear`.

---

## Decision

Selected strategy: wheel install into `/opt/mikroclear-venv`.

This is the safest first package-entrypoint path because SELKS already runs the service with `/opt/mikroclear-venv/bin/python`, and the read-only preflight confirmed the venv has the runtime dependencies `librouteros`, `requests`, and `ujson`.

Rejected for the first switch:

- editable install as the first production switch, because it depends on a mutable source tree path on SELKS;
- `PYTHONPATH` in systemd, because it adds another runtime path knob and weakens the clarity of the package boundary;
- console script as the first switch, because `ExecStart=/opt/mikroclear-venv/bin/python -m mikroclear` is explicit and does not depend on `PATH`.

The future approved install command should use the existing venv:

```bash
/opt/mikroclear-venv/bin/python -m pip install --no-deps /var/tmp/mikroclear-deploy/mikro_clear-*.whl
```

The future candidate runtime command remains:

```bash
/opt/mikroclear-venv/bin/python -m mikroclear
```

## Current Blocker

The SELKS read-only preflight showed:

```text
ModuleNotFoundError: No module named 'mikroclear'
```

Therefore, switching `mikroclear.service` to:

```text
ExecStart=/opt/mikroclear-venv/bin/python -m mikroclear
```

is blocked until the package is installed into `/opt/mikroclear-venv` or a separately approved equivalent import strategy is in place.

## Artifact Checks

The local package artifact should be checked before any SELKS upload stage:

```bash
.venv/bin/python -m pip wheel --no-deps . -w dist
.venv/bin/python -m zipfile -l dist/mikro_clear-*.whl
```

Expected wheel contents include:

```text
mikroclear/__main__.py
mikroclear/cli.py
mikroclear/app.py
mikroclear/runtime.py
```

The package metadata should continue to expose:

```text
mikroclear = "mikroclear.cli:main"
```

The artifact check is local only. It must not install anything on SELKS.

## Read-Only Importability Preflight

After a separately approved package upload/install stage, run a read-only importability check before changing systemd:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikroclear-venv/bin/python -c "import mikroclear; print(mikroclear.__file__)"'
```

This command must not call `app.main()` and must not start the Telegram polling lifecycle.

Only after that import succeeds should the systemd candidate switch be considered.

## Rollback

Rollback constraints preserve:

```text
/usr/local/bin/mikroclear.py
/etc/systemd/system/mikroclear.service
/etc/mikrocata/mikrocataTZSP0.env
/var/lib/mikrocata
```

If a future package install needs rollback before the systemd switch, remove only the package from the existing venv:

```bash
/opt/mikroclear-venv/bin/python -m pip uninstall mikro-clear
```

If a future systemd switch also happened, restore:

```text
ExecStart=/opt/mikroclear-venv/bin/python /usr/local/bin/mikroclear.py
```

and verify `mikroclear.service` only after explicit deploy/rollback approval.

## Task 1: Lock The Importability Plan

**Files:**
- Create: `docs/superpowers/plans/2026-07-05-package-importability-plan.md`
- Create: `tests/test_package_importability_plan.py`

**Interfaces:**
- Consumes: `docs/superpowers/preflight/2026-07-05-selks-readonly-preflight.md`
- Produces: a test-covered decision that wheel install into `/opt/mikroclear-venv` is the next non-deploy preparation target.

- [ ] **Step 1: Write failing tests**

Create `tests/test_package_importability_plan.py` with assertions that:

```python
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "superpowers" / "plans" / "2026-07-05-package-importability-plan.md"


class PackageImportabilityPlanTests(TestCase):
    def test_plan_selects_wheel_install_into_existing_selks_venv(self):
        text = PLAN.read_text(encoding="utf-8")

        self.assertIn("Selected strategy: wheel install into `/opt/mikroclear-venv`", text)
        self.assertIn("/opt/mikroclear-venv/bin/python -m pip install", text)
        self.assertIn("/opt/mikroclear-venv/bin/python -m mikroclear", text)
```

- [ ] **Step 2: Run focused test to verify it fails**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_package_importability_plan
```

Expected: FAIL while the plan file does not exist.

- [ ] **Step 3: Add the plan document**

Create `docs/superpowers/plans/2026-07-05-package-importability-plan.md` with the strategy and guardrails above.

- [ ] **Step 4: Run focused test to verify it passes**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_package_importability_plan
```

Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-07-05-package-importability-plan.md tests/test_package_importability_plan.py
git commit -m "Plan package importability path"
```

## Task 2: Verify Package Artifact Locally

**Files:**
- Modify: `docs/superpowers/plans/2026-07-05-package-importability-plan.md`

**Interfaces:**
- Consumes: package metadata in `pyproject.toml`
- Produces: local evidence that the wheel contains the package entrypoint modules.

- [ ] **Step 1: Build a local wheel without dependencies**

Run:

```bash
rm -rf dist
.venv/bin/python -m pip wheel --no-deps . -w dist
```

Expected: one `dist/mikro_clear-0.1.0-py3-none-any.whl` artifact.

- [ ] **Step 2: Inspect the wheel contents**

Run:

```bash
.venv/bin/python -m zipfile -l dist/mikro_clear-0.1.0-py3-none-any.whl
```

Expected output includes:

```text
mikroclear/__main__.py
mikroclear/cli.py
mikroclear/app.py
mikroclear/runtime.py
```

- [ ] **Step 3: Do not commit build output**

Run:

```bash
git status --short
```

Expected: no tracked `dist/` artifact. If `dist/` appears as untracked output, remove it before commit.

## Task 3: Prepare Future Approved SELKS Install Checklist

**Files:**
- Create: `docs/superpowers/plans/2026-07-05-selks-package-install-checklist.md`
- Test: `tests/test_package_importability_plan.py`

**Interfaces:**
- Consumes: the wheel importability decision from this plan.
- Produces: a later deploy-stage checklist. It is not executed in this stage.

- [ ] **Step 1: Add tests for the checklist**

Add assertions that the checklist contains:

```text
backup current service and script
upload wheel to /var/tmp/mikroclear-deploy/
install wheel into /opt/mikroclear-venv
run import-only check
do not switch ExecStart until import succeeds
rollback with pip uninstall mikro-clear
```

- [ ] **Step 2: Create the checklist document**

Create `docs/superpowers/plans/2026-07-05-selks-package-install-checklist.md` with only commands that require explicit approval in a future stage.

- [ ] **Step 3: Verify**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_package_importability_plan
```

Expected: OK.

## Final Verification

Run before merging this stage:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
git ls-files '*.py' | xargs .venv/bin/python -m py_compile
git grep -n -I -E '(BEGIN (RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY|sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|[0-9]{6,}:[A-Za-z0-9_-]{30,})' -- .
git status --short
```

