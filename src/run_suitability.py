"""
run_suitability.py
------------------
Phase 6 & 7 — Suitability modelling for healthcare and agriculture.

Usage:
    python src/run_suitability.py --model healthcare
    python src/run_suitability.py --model agriculture
    python src/run_suitability.py --model both
"""

import sys
import argparse
import numpy as np
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
ROOT_DIR = THIS_DIR.parent
sys.path.insert(0, str(THIS_DIR))

from utils import setup_logger, load_config
from fuzzy_standardisation import standardise_raster
from suitability_model import (weighted_linear_combination,
                                classify_suitability,
                                build_constraint_mask)

logger = setup_logger("suitability")

INTERIM  = ROOT_DIR / "data/interim"
PROC     = ROOT_DIR / "data/processed"
OUT_R    = ROOT_DIR / "outputs/rasters"
OUT_M    = ROOT_DIR / "outputs/maps"
PROC.mkdir(exist_ok=True)
OUT_R.mkdir(exist_ok=True)
OUT_M.mkdir(exist_ok=True)

# ── Raster map: config criterion key -> interim aligned raster ───────────────
HC_RASTER_MAP = {
    "distance_to_health_facility": INTERIM / "dist_health_facility_aligned.tif",
    "population_density":          INTERIM / "population_density.tif",
    "distance_to_roads":           INTERIM / "dist_roads_aligned.tif",
    "distance_to_settlements":     INTERIM / "dist_settlements_aligned.tif",
    "slope":                       INTERIM / "slope_degrees_aligned.tif",
    "land_cover_suitability":      INTERIM / "land_cover_hc_reclass.tif",
}

AG_RASTER_MAP = {
    "ndvi":                    INTERIM / "ndvi_30m_aligned.tif",
    "land_cover_suitability":  INTERIM / "land_cover_ag_reclass.tif",
    "slope":                   INTERIM / "slope_degrees_aligned.tif",
    "distance_to_water":       INTERIM / "dist_water_aligned.tif",
    "distance_to_roads":       INTERIM / "dist_roads_aligned.tif",
    "distance_to_settlements": INTERIM / "dist_settlements_aligned.tif",
}


def run_model(model_name: str):
    print(f"\n{'='*60}")
    print(f"  {model_name.upper()} SUITABILITY MODEL")
    print(f"{'='*60}")

    cfg = load_config(ROOT_DIR / f"config/{model_name}_config.yml")
    criteria = cfg["criteria"]
    raster_map = HC_RASTER_MAP if model_name == "healthcare" else AG_RASTER_MAP
    prefix = "hc" if model_name == "healthcare" else "ag"

    # ── Step 1: Check inputs ──────────────────────────────────────────────
    print(f"\n[1] Checking input rasters...")
    missing = []
    for name, path in raster_map.items():
        if path.exists():
            size = path.stat().st_size / 1_048_576
            print(f"  [OK  ] {name:<40} ({size:.1f} MB)")
        else:
            print(f"  [MISS] {name:<40} -> {path.name}")
            missing.append(name)

    if missing:
        print(f"\n  {len(missing)} input(s) missing. Run run_preprocessing.py first.")
        return False

    # ── Step 2: Fuzzy standardise all criteria ────────────────────────────
    print(f"\n[2] Fuzzy standardisation...")
    std_rasters = {}
    for name, cfg_c in criteria.items():
        src = raster_map.get(name)
        dst = PROC / f"{prefix}_{name}_std.tif"
        if dst.exists():
            print(f"  [SKIP] {name} — already standardised")
            std_rasters[name] = dst
            continue
        if src and src.exists():
            standardise_raster(src, dst,
                               cfg_c["fuzzy_type"],
                               cfg_c["fuzzy_params"])
            std_rasters[name] = dst
            print(f"  [OK  ] {name} -> {dst.name}")
        else:
            print(f"  [SKIP] {name} — source not found")

    print(f"  Standardised {len(std_rasters)} / {len(criteria)} criteria")

    # ── Step 3: Constraint mask ───────────────────────────────────────────
    print(f"\n[3] Building constraint mask...")
    mask_path = OUT_R / f"{model_name}_constraint_mask.tif"
    ref = INTERIM / "dem_30m.tif"

    constraints = {}
    slope_path = INTERIM / "slope_degrees_aligned.tif"
    lc_path    = INTERIM / "land_cover_30m_aligned.tif"

    if slope_path.exists():
        threshold = 20 if model_name == "healthcare" else 15
        constraints["steep_slope"] = (slope_path, "gt", threshold)
        print(f"  Slope > {threshold}° excluded")

    if lc_path.exists():
        constraints["water_bodies"] = (lc_path, "eq", 70)
        print(f"  Water bodies (class 70) excluded")
        if model_name == "agriculture":
            constraints["urban"] = (lc_path, "eq", 50)
            print(f"  Urban areas (class 50) excluded")

    if not mask_path.exists() and constraints:
        build_constraint_mask(constraints, ref, mask_path)
        print(f"  [OK  ] {mask_path.name}")
    elif mask_path.exists():
        print(f"  [SKIP] Already exists: {mask_path.name}")

    # ── Step 4: Weighted Linear Combination ───────────────────────────────
    print(f"\n[4] Weighted Linear Combination (WLC)...")
    weights = {name: c["weight"] for name, c in criteria.items()}
    print(f"  Weights:")
    for name, w in weights.items():
        print(f"    {name:<40} {w:.4f} ({w*100:.1f}%)")
    print(f"  Weight sum: {sum(weights.values()):.4f}")

    suit_path = OUT_R / f"{model_name}_suitability.tif"
    if not suit_path.exists():
        weighted_linear_combination(
            criteria_raster_paths=std_rasters,
            weights=weights,
            output_path=suit_path,
            constraint_mask_path=mask_path if mask_path.exists() else None,
        )
        print(f"  [OK  ] {suit_path.name}")
    else:
        print(f"  [SKIP] Already exists: {suit_path.name}")

    # ── Step 5: Classify ──────────────────────────────────────────────────
    print(f"\n[5] Classifying suitability (5 classes)...")
    cls_path = OUT_R / f"{model_name}_classified.tif"
    if not cls_path.exists():
        classify_suitability(suit_path, cls_path)
        print(f"  [OK  ] {cls_path.name}")
    else:
        print(f"  [SKIP] Already exists: {cls_path.name}")

    # ── Step 6: Summary statistics ────────────────────────────────────────
    print(f"\n[6] Suitability statistics...")
    import rasterio
    with rasterio.open(suit_path) as src:
        arr = src.read(1).astype(float)
        nodata = src.nodata
        pixel_area_ha = (abs(src.transform.a) * abs(src.transform.e)) / 10_000

    arr_valid = arr[arr != nodata] if nodata else arr[~np.isnan(arr)]
    arr_valid = arr_valid[arr_valid > 0]

    print(f"  Valid pixels    : {len(arr_valid):,}")
    print(f"  Total area (ha) : {len(arr_valid) * pixel_area_ha:,.0f}")
    print(f"  Min score       : {arr_valid.min():.4f}")
    print(f"  Max score       : {arr_valid.max():.4f}")
    print(f"  Mean score      : {arr_valid.mean():.4f}")
    print(f"  Std deviation   : {arr_valid.std():.4f}")

    # Class breakdown
    with rasterio.open(cls_path) as src:
        cls_arr = src.read(1)
    labels = {1:"Very Low", 2:"Low", 3:"Moderate", 4:"High", 5:"Very High"}
    print(f"\n  Class breakdown:")
    for cls_id, label in labels.items():
        count = (cls_arr == cls_id).sum()
        area  = count * pixel_area_ha
        pct   = count / len(arr_valid) * 100 if len(arr_valid) > 0 else 0
        print(f"    Class {cls_id} {label:<12} {count:>8,} px  {area:>10,.0f} ha  {pct:>5.1f}%")

    # ── Step 7: Quick map ─────────────────────────────────────────────────
    print(f"\n[7] Generating output map...")
    _plot_suitability(suit_path, cls_path, model_name)

    print(f"\n  {model_name.title()} model complete.")
    print(f"  Outputs saved to: outputs/rasters/ and outputs/maps/")
    return True


def _plot_suitability(suit_path, cls_path, model_name):
    try:
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
        import rasterio
        import numpy as np

        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        cmap_suit = "RdYlGn" if model_name == "healthcare" else "YlGn"

        # Continuous
        with rasterio.open(suit_path) as src:
            arr  = src.read(1).astype(float)
            nd   = src.nodata
            ext  = [src.bounds.left, src.bounds.right,
                    src.bounds.bottom, src.bounds.top]
        arr_m = np.where((arr == nd) | (arr <= 0), np.nan, arr)
        im1 = axes[0].imshow(arr_m, cmap=cmap_suit, vmin=0, vmax=1,
                              extent=ext, origin="upper")
        axes[0].set_title("Continuous suitability score", fontsize=11)
        axes[0].set_xlabel("Easting (m)")
        axes[0].set_ylabel("Northing (m)")
        plt.colorbar(im1, ax=axes[0], fraction=0.03, label="Score [0–1]")

        # Classified
        with rasterio.open(cls_path) as src:
            cls  = src.read(1)
            ext2 = [src.bounds.left, src.bounds.right,
                    src.bounds.bottom, src.bounds.top]
        cmap5 = mcolors.ListedColormap(
            ["#d73027","#fc8d59","#fee090","#91cf60","#1a9850"])
        norm5 = mcolors.BoundaryNorm([0.5,1.5,2.5,3.5,4.5,5.5], 5)
        im2 = axes[1].imshow(cls, cmap=cmap5, norm=norm5,
                              extent=ext2, origin="upper")
        axes[1].set_title("Classified suitability (5 classes)", fontsize=11)
        axes[1].set_xlabel("Easting (m)")
        cbar2 = plt.colorbar(im2, ax=axes[1], fraction=0.03, ticks=[1,2,3,4,5])
        cbar2.set_ticklabels(["Very Low","Low","Moderate","High","Very High"])

        title = ("Healthcare" if model_name == "healthcare" else "Agriculture")
        plt.suptitle(
            f"{title} Suitability — 14 Rural LGAs, Oyo State, Nigeria",
            fontsize=13, fontweight="bold")
        plt.tight_layout()

        out_map = ROOT_DIR / f"outputs/maps/{model_name}_suitability_map.png"
        fig.savefig(out_map, dpi=200, bbox_inches="tight")
        plt.close()
        print(f"  [OK  ] Map saved: {out_map.name}")
    except Exception as e:
        print(f"  [WARN] Could not generate map: {e}")


# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=["healthcare","agriculture","both"],
                        default="both", help="Which model to run")
    args = parser.parse_args()

    models = (["healthcare","agriculture"] if args.model == "both"
              else [args.model])

    for m in models:
        ok = run_model(m)
        if not ok:
            print(f"\n  Stopping — fix missing inputs before continuing.")
            sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  All models complete.")
    print(f"  Next: python src/run_uncertainty.py --model both")
    print(f"{'='*60}\n")
