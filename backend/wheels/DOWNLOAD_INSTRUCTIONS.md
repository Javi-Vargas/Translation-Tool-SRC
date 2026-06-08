# Downloading Wheels for Offline Install

The backend VMs are air-gapped. All Python packages must be installed from local
`.whl` files placed in **this** `wheels/` directory. Build that bundle on an
**internet-connected** machine, then copy the whole `backend/` folder (wheels
included) to each backend VM.

> Easiest path: run `../staging/build_offline_bundle.sh`, which performs every
> step below automatically (pin versions, download CPU-only torch + wheels,
> verify offline install). The manual steps are documented here for transparency
> and recovery.
>
> **Platform:** target is Ubuntu 24 LTS => **Python 3.12**, linux x86_64. Stage
> on a machine matching that. **torch is CPU-only** (the VMs have no GPU) — this
> avoids ~5 GB of unused NVIDIA CUDA wheels.

## 1. Pin exact versions first

Reproducible offline installs require pinned versions. On the staging machine:

```bash
python3.11 -m venv /tmp/pinvenv
source /tmp/pinvenv/bin/activate
pip install -r requirements.txt        # uses the unpinned list
pip freeze > requirements.txt          # overwrite with exact pins
deactivate
```

## 2. Download all wheels

```bash
pip download -r requirements.txt -d wheels/ \
  --platform manylinux2014_x86_64 \
  --python-version 3.11 \
  --only-binary=:all:
```

This fetches every dependency (including transitive ones) as a binary wheel
matching the target VM platform (Python 3.11, linux x86_64).

## 3. Handle packages with no binary wheel

Some packages occasionally lack a prebuilt wheel for the target platform. If
`pip download` fails on a package with `--only-binary=:all:`:

1. Re-run **without** `--only-binary` for just that package to allow an sdist:
   ```bash
   pip download <package> -d wheels/ \
     --platform manylinux2014_x86_64 --python-version 3.11
   ```
2. If an sdist is pulled, it must be built into a wheel on a machine matching the
   target architecture (same Python, same OS family), then placed in `wheels/`:
   ```bash
   pip wheel <package> -w wheels/
   ```
3. Verify nothing is missing by doing a dry offline install on the staging box:
   ```bash
   python3.11 -m venv /tmp/verifyvenv
   source /tmp/verifyvenv/bin/activate
   pip install --no-index --find-links=wheels/ -r requirements.txt
   ```
   If this succeeds with no network, the bundle is complete.

## 4. (Optional) bundle pip itself

The backend `setup.sh` tries to upgrade pip from `wheels/`. To support that on a
VM with an old pip, also download a pip wheel:

```bash
pip download pip -d wheels/ --only-binary=:all:
```

## Result

After these steps `wheels/` contains every `.whl` needed. The backend
`setup.sh` installs them with:

```bash
pip install --no-index --find-links=wheels/ -r requirements.txt
```

`--no-index` guarantees pip never reaches out to the internet.
