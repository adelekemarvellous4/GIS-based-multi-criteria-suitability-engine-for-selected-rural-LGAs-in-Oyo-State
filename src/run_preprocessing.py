"""
run_preprocessing.py
--------------------
Phase 5 — Full preprocessing pipeline.
Runs all preprocessing steps in the correct order.

Usage (from project root):
    conda activate gis_env
    cd oyo-rural-suitability-engine
    python src/run_preprocessing.py

Steps:
    1.  Scan data/raw/ and report what was found
    2.  Load + filter LGA boundaries -> study area
    3.  Mosaic DEM tiles if needed
    4.  Reproject + clip + resample DEM -> 30m reference grid
    5.  Derive slope from DEM
    6.  Reproject + clip + resample land cover (nearest-neighbour)
    7.  Reproject + clip + resample population (bilinear)
    8.  Reproject + clip + resample NDVI (bilinear)
    9.  Roads proximity raster
    10. Health facilities proximity raster
    11. Water proximity raster
    12. Settlements proximity raster
    13. Align ALL rasters to reference grid
    14. Reclassify land cover for healthcare and agriculture
    15. Convert population to density (p/km2)
    16. Final inventory check
"""

import sys
import os
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
ROOT_DIR = THIS_DIR.parent
sys.path.insert(0, str(THIS_DIR))

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.enums import Resampling
from utils import setup_logger, load_config

logger = setup_logger("preprocessing")

# ── Paths ────────────────────────────────────────────────────────────────────
RAW       = ROOT_DIR / "data/raw"
INTERIM   = ROOT_DIR / "data/interim"
PROC      = ROOT_DIR / "data/processed"
INTERIM.mkdir(exist_ok=True)
PROC.mkdir(exist_ok=True)

# ── Config ───────────────────────────────────────────────────────────────────
sa_cfg = load_config(ROOT_DIR / "config/study_area_config.yml")["study_area"]
CRS     = sa_cfg["crs_projected"]   # EPSG:32631
RES     = sa_cfg["raster_resolution"]  # 30
LGA_NAMES = [l["name"] for l in sa_cfg["lgas"]]
# Verified 14 LGAs from oyo_rural_lgas.gpkg (column: LGA):
# Irepo, Olorunsogo, Orelope, Saki East, Saki West, Ori-Ire,
# Atiba, Atisbo, Itesiwaju, Iwajowa, Kajola, Oyo West, Iseyin, Ibarapa North

print("\n" + "="*60)
print("  OYO SUITABILITY ENGINE — Preprocessing Pipeline")
print("="*60)
print(f"  Target CRS : {CRS}")
print(f"  Resolution : {RES}m")
print(f"  LGAs       : {len(LGA_NAMES)}")
print(f"  Interim    : {INTERIM}")
print()


# ════════════════════════════════════════════════════════════════════════════
# STEP 1 — Scan raw data directory
# ════════════════════════════════════════════════════════════════════════════
def step1_scan():
    print("[1/16] Scanning data/raw/ ...")
    report = {}
    scan_dirs = {
        "boundaries":   RAW / "boundaries",
        "dem":          RAW / "dem",
        "land_cover":   RAW / "land_cover",
        "population":   RAW / "population",
        "ndvi":         RAW / "ndvi",
        "health_facilities": RAW / "health_facilities",
        "roads":        RAW / "roads",
        "water":        RAW / "water",
        "settlements":  RAW / "settlements",
    }
    all_ok = True
    for name, d in scan_dirs.items():
        if not d.exists():
            print(f"  [MISS] {name}/  — directory not found")
            report[name] = []
            all_ok = False
            continue
        files = [f for f in d.rglob("*") if f.is_file() and not f.name.startswith(".")]
        if files:
            print(f"  [OK  ] {name}/")
            for f in files:
                size_mb = f.stat().st_size / 1_048_576
                print(f"           {f.name}  ({size_mb:.1f} MB)")
            report[name] = files
        else:
            print(f"  [EMPT] {name}/  — no files found")
            report[name] = []
            all_ok = False
    print()
    return report


# ════════════════════════════════════════════════════════════════════════════
# STEP 2 — Study area boundary
# ════════════════════════════════════════════════════════════════════════════
def step2_study_area(report):
    print("[2/16] Building study area boundary ...")
    out = INTERIM / "study_area.gpkg"
    if out.exists():
        print(f"  [SKIP] Already exists: {out.name}")
        return gpd.read_file(out)

    # Find boundary file
    files = report.get("boundaries", [])
    if not files:
        # Try alternate common download locations
        alt = list((RAW / "boundaries").glob("**/*.gpkg")) + \
              list((RAW / "boundaries").glob("**/*.shp")) + \
              list((RAW / "boundaries").glob("**/*.geojson"))
        files = alt

    if not files:
        print("  [FAIL] No boundary file found in data/raw/boundaries/")
        print("  Download from: https://gadm.org/download_country.html")
        print("  Save to: data/raw/boundaries/")
        return None

    bnd_file = files[0]
    print(f"  Loading: {bnd_file.name}")
    gdf = gpd.read_file(bnd_file)
    print(f"  Features: {len(gdf)} | CRS: {gdf.crs}")
    print(f"  All columns: {list(gdf.columns)}")

    # ── LGA name column is 'LGA' in oyo_rural_lgas.gpkg ──────────────────
    name_col = "LGA"
    print(f"  Using name column: '{name_col}'")
    print(f"  LGAs in file: {sorted(gdf[name_col].dropna().tolist())}")

    # Use all features in the file — already filtered to project LGAs
    matched = gdf.copy()
    print(f"  Using all {len(matched)} LGAs from boundary file as study area.")

    # Update LGA_NAMES to match what is actually in the file
    # so downstream filters work correctly
    global LGA_NAMES
    LGA_NAMES = sorted(matched[name_col].dropna().tolist())
    print(f"  Updated LGA_NAMES to: {LGA_NAMES}")

    study_area = matched.to_crs(CRS)
    study_area.to_file(out, driver="GPKG")
    print(f"  [OK  ] Saved: {out.name}  ({len(study_area)} polygons)")
    return study_area


# ════════════════════════════════════════════════════════════════════════════
# STEP 3 — Mosaic DEM tiles
# ════════════════════════════════════════════════════════════════════════════
def step3_mosaic_dem(report):
    print("[3/16] Mosaicking DEM tiles ...")
    out = INTERIM / "dem_mosaic.tif"
    if out.exists():
        print(f"  [SKIP] Already exists: {out.name}")
        return out

    tiles = report.get("dem", [])
    tiles = [f for f in tiles if f.suffix.lower() in [".tif",".tiff",".hgt"]]
    if not tiles:
        print("  [FAIL] No DEM files in data/raw/dem/")
        return None

    if len(tiles) == 1:
        print(f"  Single tile — no mosaic needed: {tiles[0].name}")
        return tiles[0]

    from rasterio.merge import merge
    print(f"  Mosaicking {len(tiles)} tiles...")
    datasets = [rasterio.open(t) for t in tiles]
    mosaic, transform = merge(datasets)
    profile = datasets[0].profile.copy()
    profile.update(transform=transform,
                   height=mosaic.shape[1], width=mosaic.shape[2],
                   count=1)
    [d.close() for d in datasets]
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(mosaic[0], 1)
    print(f"  [OK  ] Saved: {out.name}")
    return out


# ════════════════════════════════════════════════════════════════════════════
# STEP 4 — Reproject + clip + resample DEM -> reference grid
# ════════════════════════════════════════════════════════════════════════════
def step4_dem_reference(dem_path, study_area):
    print("[4/16] Creating 30m reference grid from DEM ...")
    out = INTERIM / "dem_30m.tif"
    if out.exists():
        print(f"  [SKIP] Already exists: {out.name}")
        return out
    if dem_path is None or study_area is None:
        print("  [SKIP] DEM or study area not available")
        return None

    from preprocessing import reproject_raster, clip_raster_to_boundary, resample_raster
    reproj = reproject_raster(dem_path, INTERIM / "dem_reproj.tif", CRS)
    clipped = clip_raster_to_boundary(reproj, study_area, INTERIM / "dem_clipped.tif")
    resampled = resample_raster(clipped, out, RES)
    print(f"  [OK  ] {out.name}")
    return out


# ════════════════════════════════════════════════════════════════════════════
# STEP 5 — Slope
# ════════════════════════════════════════════════════════════════════════════
def step5_slope(dem_30m):
    print("[5/16] Deriving slope ...")
    out = INTERIM / "slope_degrees.tif"
    if out.exists():
        print(f"  [SKIP] Already exists: {out.name}")
        return out
    if dem_30m is None:
        print("  [SKIP] DEM not available")
        return None

    from preprocessing import compute_slope
    compute_slope(dem_30m, out)
    print(f"  [OK  ] {out.name}")
    return out


# ════════════════════════════════════════════════════════════════════════════
# STEPS 6-8 — Raster datasets (land cover, population, NDVI)
# ════════════════════════════════════════════════════════════════════════════
def step_raster(step_num, label, raw_key, out_name,
                report, study_area, interp="bilinear"):
    print(f"[{step_num}/16] Processing {label} ...")
    out = INTERIM / out_name
    if out.exists():
        print(f"  [SKIP] Already exists: {out.name}")
        return out

    files = report.get(raw_key, [])
    tifs = [f for f in files if f.suffix.lower() in [".tif",".tiff"]]
    if not tifs:
        print(f"  [SKIP] No .tif files found in data/raw/{raw_key}/")
        return None

    src_path = tifs[0]
    print(f"  Source: {src_path.name}")

    from preprocessing import reproject_raster, clip_raster_to_boundary, resample_raster
    resamp = Resampling.bilinear if interp == "bilinear" else Resampling.nearest
    reproj  = reproject_raster(src_path, INTERIM / f"_{raw_key}_reproj.tif", CRS, resamp)
    clipped = clip_raster_to_boundary(reproj, study_area, INTERIM / f"_{raw_key}_clipped.tif")
    resampled = resample_raster(clipped, out, RES, resamp)

    # Clean up temp files
    for tmp in [INTERIM / f"_{raw_key}_reproj.tif", INTERIM / f"_{raw_key}_clipped.tif"]:
        tmp.unlink(missing_ok=True)

    print(f"  [OK  ] {out.name}")
    return out


# ════════════════════════════════════════════════════════════════════════════
# STEPS 9-12 — Proximity rasters
# ════════════════════════════════════════════════════════════════════════════
def step_proximity(step_num, label, raw_key, out_name, report, ref_raster):
    print(f"[{step_num}/16] {label} proximity raster ...")
    out = INTERIM / out_name
    if out.exists():
        print(f"  [SKIP] Already exists: {out.name}")
        return out
    if ref_raster is None or not ref_raster.exists():
        print(f"  [SKIP] Reference raster not ready")
        return None

    files = report.get(raw_key, [])
    vectors = [f for f in files
               if f.suffix.lower() in [".gpkg",".shp",".geojson",".json"]]

    # Health facilities: also accept CSV with lat/lon
    if not vectors and raw_key == "health_facilities":
        csvs = [f for f in files if f.suffix.lower() == ".csv"]
        if csvs:
            import pandas as pd
            df = pd.read_csv(csvs[0])
            lat = next((c for c in df.columns if "lat" in c.lower()), None)
            lon = next((c for c in df.columns if "lon" in c.lower() or "lng" in c.lower()), None)
            if lat and lon:
                gdf = gpd.GeoDataFrame(df,
                    geometry=gpd.points_from_xy(df[lon], df[lat]),
                    crs="EPSG:4326")
                tmp_vec = INTERIM / "_health_facilities_tmp.gpkg"
                gdf.to_file(tmp_vec, driver="GPKG")
                vectors = [tmp_vec]

    if not vectors:
        print(f"  [SKIP] No vector files in data/raw/{raw_key}/")
        return None

    vec_path = vectors[0]
    print(f"  Source: {vec_path.name}")

    from preprocessing import compute_proximity_raster
    compute_proximity_raster(vec_path, ref_raster, out)
    print(f"  [OK  ] {out.name}")
    return out


# ════════════════════════════════════════════════════════════════════════════
# STEP 13 — Align all rasters to reference grid
# ════════════════════════════════════════════════════════════════════════════
def step13_align(ref_raster):
    print("[13/16] Aligning all rasters to reference grid ...")
    if ref_raster is None:
        print("  [SKIP] No reference raster")
        return {}

    to_align = {
        "slope_degrees.tif":         "slope_degrees_aligned.tif",
        "land_cover_30m.tif":        "land_cover_30m_aligned.tif",
        "population_30m.tif":        "population_30m_aligned.tif",
        "ndvi_30m.tif":              "ndvi_30m_aligned.tif",
        "dist_roads.tif":            "dist_roads_aligned.tif",
        "dist_health_facility.tif":  "dist_health_facility_aligned.tif",
        "dist_water.tif":            "dist_water_aligned.tif",
        "dist_settlements.tif":      "dist_settlements_aligned.tif",
    }

    from preprocessing import align_raster_to_reference
    aligned = {}
    for src_name, dst_name in to_align.items():
        src = INTERIM / src_name
        dst = INTERIM / dst_name
        if dst.exists():
            print(f"  [SKIP] {dst_name}")
            aligned[dst_name] = dst
            continue
        if not src.exists():
            print(f"  [MISS] {src_name} — not yet generated")
            continue
        align_raster_to_reference(src, ref_raster, dst)
        print(f"  [OK  ] {dst_name}")
        aligned[dst_name] = dst
    return aligned


# ════════════════════════════════════════════════════════════════════════════
# STEP 14 — Land cover reclassification
# ════════════════════════════════════════════════════════════════════════════
def step14_reclass():
    print("[14/16] Reclassifying land cover ...")
    from criteria_derivation import reclassify_land_cover

    lc_aligned = INTERIM / "land_cover_30m_aligned.tif"
    if not lc_aligned.exists():
        print("  [SKIP] Aligned land cover not ready")
        return

    hc_cfg = load_config(ROOT_DIR / "config/healthcare_config.yml")
    ag_cfg = load_config(ROOT_DIR / "config/agriculture_config.yml")

    out_hc = INTERIM / "land_cover_hc_reclass.tif"
    out_ag = INTERIM / "land_cover_ag_reclass.tif"

    if not out_hc.exists():
        reclassify_land_cover(lc_aligned, out_hc, hc_cfg["land_cover_reclass"])
        print(f"  [OK  ] {out_hc.name}")
    else:
        print(f"  [SKIP] {out_hc.name}")

    if not out_ag.exists():
        reclassify_land_cover(lc_aligned, out_ag, ag_cfg["land_cover_reclass"])
        print(f"  [OK  ] {out_ag.name}")
    else:
        print(f"  [SKIP] {out_ag.name}")


# ════════════════════════════════════════════════════════════════════════════
# STEP 15 — Population density conversion
# ════════════════════════════════════════════════════════════════════════════
def step15_pop_density():
    print("[15/16] Converting population to density (p/km²) ...")
    from criteria_derivation import derive_population_density

    pop_aligned = INTERIM / "population_30m_aligned.tif"
    out = INTERIM / "population_density.tif"

    if out.exists():
        print(f"  [SKIP] Already exists: {out.name}")
        return
    if not pop_aligned.exists():
        print("  [SKIP] Aligned population raster not ready")
        return

    derive_population_density(pop_aligned, out, pixel_size_m=RES)
    print(f"  [OK  ] {out.name}")


# ════════════════════════════════════════════════════════════════════════════
# STEP 16 — Final inventory
# ════════════════════════════════════════════════════════════════════════════
def step16_inventory():
    print("[16/16] Final interim raster inventory ...")

    expected = [
        ("dem_30m.tif",                    "DEM reference grid"),
        ("slope_degrees_aligned.tif",      "Slope (both models)"),
        ("land_cover_30m_aligned.tif",     "Land cover raw"),
        ("land_cover_hc_reclass.tif",      "Land cover — healthcare"),
        ("land_cover_ag_reclass.tif",      "Land cover — agriculture"),
        ("population_30m_aligned.tif",     "Population count"),
        ("population_density.tif",         "Population density (p/km²)"),
        ("ndvi_30m_aligned.tif",           "NDVI"),
        ("dist_roads_aligned.tif",         "Distance to roads"),
        ("dist_health_facility_aligned.tif","Distance to health facility"),
        ("dist_water_aligned.tif",         "Distance to water"),
        ("dist_settlements_aligned.tif",   "Distance to settlements"),
        ("study_area.gpkg",                "Study area boundary"),
    ]

    ready = 0
    print()
    print(f"  {'File':<45} {'Description':<35} Status")
    print(f"  {'-'*45} {'-'*35} ------")
    for fname, desc in expected:
        p = INTERIM / fname
        if p.exists():
            size_mb = p.stat().st_size / 1_048_576
            print(f"  {fname:<45} {desc:<35} OK ({size_mb:.1f} MB)")
            ready += 1
        else:
            print(f"  {fname:<45} {desc:<35} MISSING")

    print()
    print(f"  {ready} / {len(expected)} files ready")
    if ready == len(expected):
        print("  All preprocessing complete — ready for suitability modelling!")
    else:
        print(f"  {len(expected)-ready} file(s) still needed.")
    print()


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    report      = step1_scan()
    study_area  = step2_study_area(report)
    dem_mosaic  = step3_mosaic_dem(report)
    dem_30m     = step4_dem_reference(dem_mosaic, study_area)
    step5_slope(dem_30m)

    step_raster("6",  "Land cover", "land_cover",  "land_cover_30m.tif",
                report, study_area, interp="nearest")
    step_raster("7",  "Population", "population",  "population_30m.tif",
                report, study_area, interp="bilinear")
    step_raster("8",  "NDVI",       "ndvi",         "ndvi_30m.tif",
                report, study_area, interp="bilinear")

    step_proximity("9",  "Roads",            "roads",             "dist_roads.tif",            report, dem_30m)
    step_proximity("10", "Health facilities","health_facilities", "dist_health_facility.tif",  report, dem_30m)
    step_proximity("11", "Water bodies",     "water",             "dist_water.tif",            report, dem_30m)
    step_proximity("12", "Settlements",      "settlements",       "dist_settlements.tif",      report, dem_30m)

    step13_align(dem_30m)
    step14_reclass()
    step15_pop_density()
    step16_inventory()

    print("="*60)
    print("  Preprocessing complete.")
    print("  Next: open notebooks/03_healthcare_suitability.ipynb")
    print("="*60 + "\n")
