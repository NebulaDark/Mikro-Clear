# Mikro-Clear

Local baseline and cleanup workspace for the Mikrocata TZSP0 service.

The production script currently runs on `selks` as:

```text
/usr/local/bin/mikrocataTZSP0.py
```

The copied baseline is stored at:

```text
src/mikrocata/legacy.py
```

This repository is intended to make changes testable before touching the running
service. The first extracted module is pure alert decision logic for target IP,
peer IP, port selection, and event deduplication.

## Checks

```bash
python -m unittest discover -s tests
python -m py_compile src/mikrocata/legacy.py src/mikrocata/alert_logic.py
```

## Local Logic Fixes

- When source IP is whitelisted and the destination is selected as the block
  target, local logic now uses `dest_port`.
- Alert deduplication is now keyed by the calculated block target, not only by
  `src_ip`, so one whitelisted source can report multiple destination targets.
