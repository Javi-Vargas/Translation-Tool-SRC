# About Python Wheels — What They Are and How This Project Uses Them

## What is a wheel?

A `.whl` file (wheel) is a pre-built Python package — a zip archive containing
compiled code and metadata that `pip` can install directly without needing to
compile anything. The filename encodes exactly what it's compatible with:

```
llama_cpp_python-0.3.4-cp312-cp312-manylinux_2_17_x86_64.whl
│               │      │     │    └─ Linux x86_64, glibc ≥ 2.17
│               │      │     └────── CPython 3.12 ABI
│               │      └──────────── CPython 3.12
│               └─────────────────── package version
└─────────────────────────────────── package name
```

Pure-Python packages (no C extensions) produce platform-neutral wheels:
```
fastapi-0.136.3-py3-none-any.whl    ← works on any Python 3, any OS
```

---

## Why this project bundles wheels

The backend VMs are **air-gapped** — they have no internet access and cannot
reach PyPI. `pip install` normally downloads packages on the fly; in an
air-gapped environment that fails immediately.

The solution is to download all required wheels on an internet-connected
**staging machine**, copy the entire `wheels/` directory to the VMs alongside
the app code, and then install offline:

```bash
pip install --no-index --find-links=wheels/ -r requirements_v3.txt
```

- `--no-index` tells pip to never reach out to PyPI.
- `--find-links=wheels/` tells pip to look for packages in this directory.

If the right wheel for every package is present, installation succeeds with no
network access at all.

---

## What's in this directory

After running `staging/build_offline_bundle.sh` on the staging machine, this
directory contains one `.whl` file per dependency (direct + transitive) listed
in `backend/requirements_v3.txt`. The build script:

1. Creates a clean virtualenv and installs all packages.
2. Pins exact versions to `requirements_v3.txt` via `pip freeze`.
3. Downloads every wheel into this directory with `pip download`.
4. Verifies a fully offline install succeeds before finishing.

The wheels are **not committed to git** (they are binary and large). They must
be (re)built on the staging machine whenever dependencies change.

---

## When to (re)build the wheels

| Situation | Action |
|-----------|--------|
| First-time setup | Run `staging/build_offline_bundle.sh` |
| A dependency version is updated in `requirements_v3.txt` | Re-run `staging/build_offline_bundle.sh` |
| A new package is added to `requirements_v3.txt` | Re-run `staging/build_offline_bundle.sh` |
| Upgrading to a newer Python on the VMs | Re-run on a staging host running the new Python version |
| A wheel is accidentally deleted from this directory | Re-run `staging/build_offline_bundle.sh` |

> **Platform lock:** wheels are compiled for a specific OS, CPU architecture,
> and Python version. The staging machine **must match the VMs** (Ubuntu 24 LTS,
> Python 3.12, x86_64). Wheels built on macOS or Windows will not install on
> the Linux VMs.

---

## The special case: llama-cpp-python

`llama-cpp-python` is a C extension that wraps the `llama.cpp` inference
library. Pre-built wheels are published to PyPI for common platforms.
`pip download --only-binary=:all:` will grab one if it exists.

If no pre-built wheel is found for your exact platform, you need to **build
it from source on the staging host** (which must match the VMs):

```bash
pip wheel llama-cpp-python -w wheels/
```

This compiles the C++ code on the staging machine and produces a wheel
compatible with that machine — which, since it matches the VMs, will also
install correctly offline on the VMs.

See `DOWNLOAD_INSTRUCTIONS.md` in this directory for the full step-by-step
procedure and the general fallback for any package that lacks a pre-built wheel.

---

## Quick reference

| Task | Command |
|------|---------|
| Build the full wheel bundle | `cd staging && ./build_offline_bundle.sh` |
| Install offline on a VM | `pip install --no-index --find-links=wheels/ -r requirements_v3.txt` |
| Check what's in this directory | `ls -lh wheels/*.whl \| wc -l` |
| Verify an offline install works | See `REQUIREMENTS.md` § 5 |
| Handle a missing pre-built wheel | See `DOWNLOAD_INSTRUCTIONS.md` step 3 |
