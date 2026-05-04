"""
setup.py
--------
One-time project setup script for the Oyo Rural Suitability Engine.

Run this once after cloning the repository:
    python setup.py

What it does:
  1. Verifies Python version (>= 3.10)
  2. Checks all required packages are importable
  3. Creates all required data/output directories
  4. Validates all YAML config files
  5. Registers the Jupyter kernel for the project environment
  6. Prints a summary of what still needs to be done manually
"""

import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ─── 1. Python version ───────────────────────────────────────────────────────

def check_python():
    major, minor = sys.version_info[:2]
    ok = major == 3 and minor >= 10
    status = "OK" if ok else "FAIL"
    print(f"  [{'OK' if ok else 'FAIL'}] Python {major}.{minor}  (need >= 3.10)")
    if not ok:
        sys.exit("Python 3.10+ required. Activate your conda environment first.")

# ─── 2. Package check ────────────────────────────────────────────────────────

REQUIRED_PACKAGES = {
    "rasterio":    "rasterio",
    "geopandas":   "geopandas",
    "numpy":       "numpy",
    "scipy":       "scipy",
    "pandas":      "pandas",
    "matplotlib":  "matplotlib",
    "folium":      "folium",
    "yaml":        "pyyaml",
    "tqdm":        "tqdm",
    "shapely":     "shapely",
    "pyproj":      "pyproj",
    "osmnx":       "osmnx",
    "whitebox":    "whitebox",
    "reportlab":   "reportlab",
    "fpdf":        "fpdf2",
    "streamlit":   "streamlit",
}

def check_packages():
    failed = []
    for import_name, pip_name in REQUIRED_PACKAGES.items():
        try:
            mod = __import__(import_name)
            ver = getattr(mod, "__version__", getattr(mod, "Version", "?"))
            print(f"  [OK  ] {pip_name:<20} {ver}")
        except ImportError:
            print(f"  [MISS] {pip_name:<20} — run: pip install {pip_name}")
            failed.append(pip_name)
    if failed:
        print(f"\n  Missing: {', '.join(failed)}")
        print("  Run: pip install -r requirements.txt")
    return len(failed) == 0

# ─── 3. Directory structure ──────────────────────────────────────────────────

REQUIRED_DIRS = [
    "data/raw/boundaries",
    "data/raw/dem",
    "data/raw/land_cover",
    "data/raw/health_facilities",
    "data/raw/population",
    "data/raw/roads",
    "data/raw/water",
    "data/raw/ndvi",
    "data/raw/settlements",
    "data/raw/constraints/flood",
    "data/raw/constraints/protected",
    "data/interim",
    "data/processed",
    "data/external/soil",
    "data/external/ntl",
    "outputs/rasters",
    "outputs/vectors",
    "outputs/maps",
    "outputs/reports",
    "outputs/dashboards",
    "dashboard/assets",
    "docs",
]

def create_dirs():
    created = 0
    for d in REQUIRED_DIRS:
        p = ROOT / d
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            # Add .gitkeep so empty dirs are tracked
            (p / ".gitkeep").touch()
            print(f"  [NEW ] {d}")
            created += 1
        else:
            print(f"  [OK  ] {d}")
    print(f"  {created} new directories created.")

# ─── 4. Config validation ────────────────────────────────────────────────────

def validate_configs():
    import yaml
    config_dir = ROOT / "config"
    failed = []
    for cfg_file in sorted(config_dir.glob("*.yml")):
        try:
            with open(cfg_file) as f:
                data = yaml.safe_load(f)
            if data is None:
                raise ValueError("Empty config file")

            # Check weight sums for model configs
            if "criteria" in data:
                weights = [v["weight"] for v in data["criteria"].values()
                           if isinstance(v, dict) and "weight" in v]
                total = round(sum(weights), 4)
                if abs(total - 1.0) > 0.005:
                    raise ValueError(f"Weights sum to {total:.4f}, expected 1.0")
                print(f"  [OK  ] {cfg_file.name:<35} weights sum={total:.4f}")
            else:
                print(f"  [OK  ] {cfg_file.name}")
        except Exception as e:
            print(f"  [FAIL] {cfg_file.name} — {e}")
            failed.append(cfg_file.name)
    return len(failed) == 0

# ─── 5. Jupyter kernel ───────────────────────────────────────────────────────

def register_kernel():
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "ipykernel", "install",
             "--user", "--name", "oyo-suitability",
             "--display-name", "Python (oyo-suitability)"],
            capture_output=True, text=True)
        if result.returncode == 0:
            print("  [OK  ] Jupyter kernel registered: 'oyo-suitability'")
        else:
            print(f"  [WARN] Kernel registration failed: {result.stderr.strip()}")
    except Exception as e:
        print(f"  [WARN] Could not register kernel: {e}")

# ─── 6. Data checklist ───────────────────────────────────────────────────────

MANUAL_DATASETS = [
    ("data/raw/dem/",              "SRTM DEM tiles",           "https://earthexplorer.usgs.gov/"),
    ("data/raw/land_cover/",       "ESA WorldCover 2021",      "https://worldcover2021.esa.int/downloader"),
    ("data/raw/health_facilities/","GRID3 health facilities",  "https://grid3.org/resources/health-facilities"),
    ("data/raw/population/",       "WorldPop Nigeria 100m",    "https://hub.worldpop.org/geodata/listing?id=29"),
    ("data/raw/ndvi/",             "NDVI via GEE export",      "https://code.earthengine.google.com/"),
    ("data/raw/water/",            "HydroRIVERS Africa",       "https://www.hydrosheds.org/products/hydrorivers"),
    ("data/raw/constraints/flood/","FATHOM flood zones",       "https://www.fathom.global/"),
    ("data/raw/constraints/protected/","WDPA protected areas", "https://www.protectedplanet.net/"),
]

def check_data():
    print("\n  Manual download checklist:")
    missing = 0
    for rel_path, name, url in MANUAL_DATASETS:
        p = ROOT / rel_path
        files = [f for f in p.iterdir() if not f.name.startswith(".")] if p.exists() else []
        if files:
            print(f"  [OK  ] {name:<35} ({len(files)} file(s))")
        else:
            print(f"  [    ] {name:<35} {url}")
            missing += 1
    if missing:
        print(f"\n  {missing} dataset(s) still needed. See docs/data_inventory.md for instructions.")
    else:
        print("\n  All datasets present. Ready for Phase 5 preprocessing!")

# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 60)
    print("  OYO RURAL SUITABILITY ENGINE — SETUP")
    print("=" * 60)

    print("\n[1] Python version")
    check_python()

    print("\n[2] Package check")
    pkgs_ok = check_packages()

    print("\n[3] Directory structure")
    create_dirs()

    print("\n[4] Config validation")
    configs_ok = validate_configs()

    print("\n[5] Jupyter kernel")
    register_kernel()

    print("\n[6] Data inventory")
    check_data()

    print("\n" + "=" * 60)
    if pkgs_ok and configs_ok:
        print("  Setup complete. Next step: download datasets (see step 6 above),")
        print("  then open notebooks/02_data_preprocessing.ipynb to begin.")
    else:
        print("  Setup completed with warnings. Fix issues above before proceeding.")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    main()
