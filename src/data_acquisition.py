"""
data_acquisition.py
-------------------
Functions for downloading and sourcing raw spatial datasets for the
Oyo Rural Suitability Engine.

Run from the PROJECT ROOT (not from src/):
    cd oyo-rural-suitability-engine
    python src/data_acquisition.py
"""

import os
import sys
from pathlib import Path

# ── Fix import path ──────────────────────────────────────────────────────────
# Works whether you run from project root OR from src/
THIS_DIR = Path(__file__).resolve().parent          # .../src/
ROOT_DIR = THIS_DIR.parent                          # .../oyo-rural-suitability-engine/
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

# ── Fix working-directory-relative paths ────────────────────────────────────
# All data paths are relative to project root, not wherever you run from
def _root_path(rel: str) -> Path:
    return ROOT_DIR / rel

import requests
import osmnx as ox
import geopandas as gpd
from utils import setup_logger

logger = setup_logger(__name__)


# ─── Administrative Boundaries ──────────────────────────────────────────────

def download_lga_boundaries(state: str = "Oyo",
                             output_dir: str = "data/raw/boundaries",
                             source: str = "geoboundaries") -> Path:
    """
    Download LGA-level administrative boundaries for Oyo State.
    Filters to only the 19 confirmed project LGAs.
    """
    out_dir = _root_path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "oyo_lga_boundaries.gpkg"

    if out_path.exists():
        logger.info(f"LGA boundaries already exist: {out_path}")
        return out_path

    # Confirmed 19 LGA names
    TARGET_LGAS = [
        "Afijio","Atiba","Oyo East","Oyo West",
        "Atisbo","Irepo","Iseyin","Itesiwaju","Iwajowa",
        "Kajola","Olorunsogo","Oriire","Saki East","Saki West","Surulere",
        "Ibarapa Central","Ibarapa East","Ibarapa North","Ido",
    ]

    logger.info("Downloading Nigeria ADM2 boundaries from geoBoundaries...")
    print("  Contacting geoBoundaries API...")

    api_url = "https://www.geoboundaries.org/api/current/gbOpen/NGA/ADM2/"
    resp = requests.get(api_url, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    gjson_url = data.get("gjDownloadURL")
    if not gjson_url:
        raise ValueError("geoBoundaries did not return a download URL. Try again.")

    print(f"  Downloading GeoJSON from {gjson_url[:60]}...")
    gdf = gpd.read_file(gjson_url)
    print(f"  Total Nigeria LGAs: {len(gdf)}")

    # Filter to Oyo State — geoBoundaries uses shapeName field
    # Try common column variations
    name_col = next(
        (c for c in gdf.columns if c.lower() in ["shapename","name","lga_name","lganame"]),
        gdf.columns[0]
    )
    # First filter to Oyo state using state-level name or ISO code
    state_col = next(
        (c for c in gdf.columns if "state" in c.lower() or "adm1" in c.lower()),
        None
    )

    if state_col:
        oyo_gdf = gdf[gdf[state_col].str.contains("Oyo", case=False, na=False)]
    else:
        # Fall back: filter by known LGA names
        oyo_gdf = gdf[gdf[name_col].isin(TARGET_LGAS)]

    print(f"  Oyo State LGAs found: {len(oyo_gdf)}")

    # Further filter to our 19 target LGAs
    target_gdf = oyo_gdf[oyo_gdf[name_col].isin(TARGET_LGAS)].copy()
    print(f"  Target LGAs matched: {len(target_gdf)} of 19")

    if len(target_gdf) < 19:
        missing = set(TARGET_LGAS) - set(target_gdf[name_col].tolist())
        print(f"  WARNING — LGAs not matched: {missing}")
        print(f"  Available names sample: {oyo_gdf[name_col].tolist()[:10]}")

    target_gdf.to_file(out_path, driver="GPKG")
    logger.info(f"Saved {len(target_gdf)} LGA boundaries to: {out_path}")
    return out_path


# ─── Roads (OSM via OSMnx) ──────────────────────────────────────────────────

def download_roads_osm(study_area_gdf: gpd.GeoDataFrame,
                       network_type: str = "all",
                       output_dir: str = "data/raw/roads") -> Path:
    """Download road network for the study area from OpenStreetMap."""
    out_dir = _root_path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "roads_osm.gpkg"

    if out_path.exists():
        logger.info(f"Roads already exist: {out_path}")
        return out_path

    logger.info("Downloading road network from OSM (this may take a few minutes)...")
    polygon = study_area_gdf.to_crs("EPSG:4326").unary_union
    G = ox.graph_from_polygon(polygon, network_type=network_type)
    edges = ox.graph_to_gdfs(G, nodes=False)
    edges.to_file(out_path, driver="GPKG")
    logger.info(f"Saved roads to {out_path}")
    return out_path


# ─── Health Facilities (OSM) ────────────────────────────────────────────────

def download_health_facilities_osm(study_area_gdf: gpd.GeoDataFrame,
                                    output_dir: str = "data/raw/health_facilities") -> Path:
    """Download health facility locations from OpenStreetMap."""
    out_dir = _root_path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "health_facilities_osm.gpkg"

    if out_path.exists():
        logger.info(f"Health facilities already exist: {out_path}")
        return out_path

    logger.info("Downloading health facilities from OSM...")
    polygon = study_area_gdf.to_crs("EPSG:4326").unary_union
    tags = {"amenity": ["hospital", "clinic", "health_post",
                        "doctors", "pharmacy", "nursing_home"]}
    gdf = ox.features_from_polygon(polygon, tags=tags)
    gdf = gdf.copy()
    gdf["geometry"] = gdf.geometry.centroid
    gdf.to_file(out_path, driver="GPKG")
    logger.info(f"Saved health facilities to {out_path}")
    return out_path


# ─── Water Bodies (OSM) ─────────────────────────────────────────────────────

def download_water_bodies_osm(study_area_gdf: gpd.GeoDataFrame,
                               output_dir: str = "data/raw/water") -> Path:
    """Download water bodies and rivers from OpenStreetMap."""
    out_dir = _root_path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "water_bodies_osm.gpkg"

    if out_path.exists():
        logger.info(f"Water bodies already exist: {out_path}")
        return out_path

    logger.info("Downloading water bodies from OSM...")
    polygon = study_area_gdf.to_crs("EPSG:4326").unary_union
    tags = {"natural": ["water", "wetland"], "waterway": ["river", "stream"]}
    gdf = ox.features_from_polygon(polygon, tags=tags)
    gdf.to_file(out_path, driver="GPKG")
    logger.info(f"Saved water bodies to {out_path}")
    return out_path


# ─── Settlements (OSM) ──────────────────────────────────────────────────────

def download_settlements_osm(study_area_gdf: gpd.GeoDataFrame,
                              output_dir: str = "data/raw/settlements") -> Path:
    """Download settlement/place locations from OpenStreetMap."""
    out_dir = _root_path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "settlements_osm.gpkg"

    if out_path.exists():
        logger.info(f"Settlements already exist: {out_path}")
        return out_path

    logger.info("Downloading settlements from OSM...")
    polygon = study_area_gdf.to_crs("EPSG:4326").unary_union
    tags = {"place": ["city","town","village","hamlet","suburb","neighbourhood"]}
    gdf = ox.features_from_polygon(polygon, tags=tags)
    gdf = gdf.copy()
    gdf["geometry"] = gdf.geometry.centroid   # ensure all are points
    gdf.to_file(out_path, driver="GPKG")
    logger.info(f"Saved settlements to {out_path}")
    return out_path


# ─── Manual Download Reference ──────────────────────────────────────────────

def print_data_sources():
    sources = {
        "SRTM DEM 30m":          ("https://earthexplorer.usgs.gov/",               "data/raw/dem/"),
        "WorldPop population":   ("https://hub.worldpop.org/geodata/listing?id=29","data/raw/population/"),
        "ESA WorldCover 2021":   ("https://worldcover2021.esa.int/downloader",      "data/raw/land_cover/"),
        "NDVI via GEE":          ("https://code.earthengine.google.com/",           "data/raw/ndvi/"),
        "GRID3 health facilities":("https://grid3.org/resources/health-facilities", "data/raw/health_facilities/"),
        "HydroRIVERS Africa":    ("https://www.hydrosheds.org/products/hydrorivers","data/raw/water/"),
        "WDPA protected areas":  ("https://www.protectedplanet.net/",               "data/raw/constraints/protected/"),
    }
    print("\n" + "="*60)
    print("MANUAL DOWNLOADS REQUIRED")
    print("="*60)
    for name, (url, path) in sources.items():
        print(f"\n  {name}\n  URL  : {url}\n  Save : {path}")
    print()


# ─── Main — run all auto-downloads ──────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*55)
    print("  OYO SUITABILITY ENGINE — Data Acquisition")
    print("="*55)
    print(f"  Project root : {ROOT_DIR}")
    print(f"  Working dir  : {Path.cwd()}")

    # Step 1: LGA boundaries
    print("\n[1/4] Downloading LGA boundaries...")
    try:
        lga_path = download_lga_boundaries()
        print(f"  Done: {lga_path}")
    except Exception as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    # Step 2: Load boundaries for spatial queries
    print("\n[2/4] Loading study area for OSM queries...")
    study_area = gpd.read_file(lga_path)
    print(f"  Loaded {len(study_area)} LGA polygons")

    # Step 3: Roads
    print("\n[3/4] Downloading roads from OSM (may take 2-5 min)...")
    try:
        roads_path = download_roads_osm(study_area)
        print(f"  Done: {roads_path}")
    except Exception as e:
        print(f"  ERROR: {e}")

    # Step 4: Water + Settlements
    print("\n[4/4] Downloading water bodies and settlements from OSM...")
    try:
        water_path = download_water_bodies_osm(study_area)
        print(f"  Done (water): {water_path}")
        settle_path = download_settlements_osm(study_area)
        print(f"  Done (settlements): {settle_path}")
    except Exception as e:
        print(f"  ERROR: {e}")

    # Manual download reminder
    print_data_sources()

    print("="*55)
    print("  Auto-downloads complete.")
    print("  Now download the manual datasets listed above.")
    print("="*55 + "\n")


# ─── Manual boundary loading (use when API download fails) ──────────────────

def load_lga_boundaries_from_file(filepath: str,
                                   output_dir: str = "data/raw/boundaries") -> Path:
    """
    Load LGA boundaries from a manually downloaded file and filter to
    the 19 project LGAs.

    Use this if download_lga_boundaries() fails (API blocked, no internet, etc.)

    Supported formats: .gpkg, .shp, .geojson, .json

    Args:
        filepath: Path to your downloaded Nigeria ADM2 boundary file.
        output_dir: Where to save the filtered GeoPackage.

    Returns:
        Path to saved filtered GeoPackage.

    Manual download options:
        GADM  : https://gadm.org/download_country.html  (select Nigeria, GeoPackage)
        HDX   : https://data.humdata.org/dataset/cod-ab-nga
               -> download nga_admbnda_adm2_osgof_20190417.zip
    """
    TARGET_LGAS = [
        "Afijio","Atiba","Oyo East","Oyo West",
        "Atisbo","Irepo","Iseyin","Itesiwaju","Iwajowa",
        "Kajola","Olorunsogo","Oriire","Saki East","Saki West","Surulere",
        "Ibarapa Central","Ibarapa East","Ibarapa North","Ido",
    ]

    out_dir = _root_path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "oyo_lga_boundaries.gpkg"

    print(f"Loading boundaries from: {filepath}")
    gdf = gpd.read_file(filepath)
    print(f"Columns: {list(gdf.columns)}")
    print(f"Total features: {len(gdf)}")

    # Try to find the LGA name column
    name_col = next(
        (c for c in gdf.columns
         if any(kw in c.lower() for kw in ["lga","adm2","name","shapename"])),
        None
    )
    if not name_col:
        print("Could not auto-detect name column. Available columns:")
        for c in gdf.columns:
            print(f"  {c}")
        raise ValueError("Set name_col manually and rerun.")

    print(f"Using name column: '{name_col}'")
    print(f"Sample values: {gdf[name_col].dropna().head(10).tolist()}")

    # Filter to Oyo State LGAs
    matched = gdf[gdf[name_col].isin(TARGET_LGAS)].copy()
    print(f"Matched {len(matched)} of 19 target LGAs")

    if len(matched) < 19:
        found = set(matched[name_col].tolist())
        missing = set(TARGET_LGAS) - found
        print(f"Missing: {missing}")
        print("Check the name spellings in your file vs TARGET_LGAS list above.")

    matched.to_file(out_path, driver="GPKG")
    print(f"Saved to: {out_path}")
    return out_path
