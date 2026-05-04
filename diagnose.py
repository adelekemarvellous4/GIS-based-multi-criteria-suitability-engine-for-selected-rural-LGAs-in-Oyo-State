"""
diagnose.py
-----------
Standalone diagnostic script — no imports from src/ needed.
Run this from the project root to find exactly what is failing.

    cd oyo-rural-suitability-engine
    python diagnose.py

Or from anywhere:
    python "C:/Users/Marvii/Documents/GIS_PROJECTS/oyo-rural-suitability-engine/diagnose.py"
"""

# ── Step 0: prove the script is actually running ─────────────────────────────
print("=" * 55)
print("  DIAGNOSTIC SCRIPT RUNNING")
print("=" * 55)

import sys
import os
from pathlib import Path

print(f"\n[INFO] Python  : {sys.version}")
print(f"[INFO] Exe     : {sys.executable}")
print(f"[INFO] CWD     : {Path.cwd()}")
print(f"[INFO] Script  : {Path(__file__).resolve()}")

ROOT = Path(__file__).resolve().parent
SRC  = ROOT / "src"
print(f"[INFO] Root    : {ROOT}")
print(f"[INFO] src/    : {SRC}  (exists={SRC.exists()})")

# ── Step 1: check sys.path ───────────────────────────────────────────────────
print("\n[1] Checking sys.path...")
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
    print(f"  Added to path: {SRC}")
else:
    print(f"  Already in path: {SRC}")

# ── Step 2: check src/ files exist ──────────────────────────────────────────
print("\n[2] Checking src/ files...")
expected = ["utils.py","data_acquisition.py","preprocessing.py",
            "fuzzy_standardisation.py","ahp.py","suitability_model.py"]
for f in expected:
    p = SRC / f
    status = "OK  " if p.exists() else "MISSING"
    print(f"  [{status}] {f}")

# ── Step 3: import each package individually ─────────────────────────────────
print("\n[3] Checking Python packages...")
packages = [
    ("os",          "built-in"),
    ("sys",         "built-in"),
    ("pathlib",     "built-in"),
    ("json",        "built-in"),
    ("requests",    "pip install requests"),
    ("yaml",        "pip install pyyaml"),
    ("numpy",       "pip install numpy"),
    ("pandas",      "pip install pandas"),
    ("geopandas",   "conda install geopandas  OR  pip install geopandas"),
    ("rasterio",    "conda install rasterio   OR  pip install rasterio"),
    ("shapely",     "pip install shapely"),
    ("pyproj",      "pip install pyproj"),
    ("osmnx",       "pip install osmnx"),
    ("whitebox",    "pip install whitebox"),
    ("scipy",       "pip install scipy"),
    ("matplotlib",  "pip install matplotlib"),
    ("tqdm",        "pip install tqdm"),
]

failed = []
for pkg, install_cmd in packages:
    try:
        mod = __import__(pkg)
        ver = getattr(mod, "__version__", getattr(mod, "Version", "?"))
        print(f"  [OK  ] {pkg:<15} {ver}")
    except ImportError as e:
        print(f"  [FAIL] {pkg:<15} NOT FOUND -> {install_cmd}")
        failed.append(pkg)
    except Exception as e:
        print(f"  [ERR ] {pkg:<15} {e}")
        failed.append(pkg)

# ── Step 4: import utils.py ──────────────────────────────────────────────────
print("\n[4] Importing utils.py from src/...")
try:
    import utils
    print("  [OK  ] utils imported")
    logger = utils.setup_logger("diagnose")
    print("  [OK  ] setup_logger works")
    cfg = utils.load_config(ROOT / "config" / "study_area_config.yml")
    print(f"  [OK  ] load_config works — {len(cfg)} keys")
except Exception as e:
    print(f"  [FAIL] {type(e).__name__}: {e}")

# ── Step 5: import data_acquisition.py ──────────────────────────────────────
print("\n[5] Importing data_acquisition.py...")
try:
    import data_acquisition as da
    print("  [OK  ] data_acquisition imported")
    print(f"  [OK  ] ROOT_DIR = {da.ROOT_DIR}")
    print(f"  [INFO] Functions available:")
    fns = [x for x in dir(da) if not x.startswith("_") and callable(getattr(da, x))]
    for fn in fns:
        print(f"           {fn}()")
except Exception as e:
    print(f"  [FAIL] {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

# ── Step 6: check data directories ──────────────────────────────────────────
print("\n[6] Checking data directories...")
dirs = [
    "data/raw/boundaries", "data/raw/dem", "data/raw/land_cover",
    "data/raw/health_facilities", "data/raw/population", "data/raw/roads",
    "data/raw/water", "data/raw/ndvi", "data/raw/settlements",
    "data/interim", "data/processed",
    "outputs/rasters", "outputs/vectors", "outputs/maps",
]
for d in dirs:
    p = ROOT / d
    files = [f.name for f in p.iterdir() if not f.name.startswith(".")] if p.exists() else []
    status = "OK  " if p.exists() else "MISSING — run setup.py"
    data_str = f"  ({len(files)} file(s): {files[:3]})" if files else ""
    print(f"  [{status}] {d}{data_str}")

# ── Step 7: check configs ────────────────────────────────────────────────────
print("\n[7] Checking config files...")
import yaml
for cfg_name in ["study_area_config.yml","healthcare_config.yml","agriculture_config.yml"]:
    p = ROOT / "config" / cfg_name
    if p.exists():
        with open(p) as f:
            data = yaml.safe_load(f)
        print(f"  [OK  ] {cfg_name} — {list(data.keys())[:4]}")
    else:
        print(f"  [MISS] {cfg_name}")

# ── Summary ──────────────────────────────────────────────────────────────────
print("\n" + "=" * 55)
if failed:
    print(f"  {len(failed)} PACKAGE(S) MISSING: {failed}")
    print("  Fix: conda activate gis_env")
    print("  Then: pip install " + " ".join(failed))
else:
    print("  All packages OK.")
    print("  If data_acquisition.py still fails silently, run:")
    print("  python src/data_acquisition.py 2>&1")
    print("  (the 2>&1 captures stderr — paste full output here)")
print("=" * 55 + "\n")
