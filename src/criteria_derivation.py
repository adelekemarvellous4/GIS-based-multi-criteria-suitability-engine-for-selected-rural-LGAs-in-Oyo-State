"""
criteria_derivation.py
----------------------
High-level pipeline functions that orchestrate preprocessing steps
into the final criteria rasters needed by both suitability models.

Each function reads from data/interim/ and writes to data/interim/
as aligned, ready-to-standardise rasters.
"""

import numpy as np
import rasterio
import geopandas as gpd
from pathlib import Path
from utils import setup_logger, load_config
from preprocessing import (compute_proximity_raster, compute_slope,
                            align_raster_to_reference)

logger = setup_logger(__name__)


def derive_all_healthcare_criteria(interim_dir: Path, ref_raster: Path) -> dict:
    """
    Orchestrate derivation of all healthcare criteria rasters.

    Expects the following files already in interim_dir:
      - dem_30m.tif
      - dist_health_facility.tif  (from proximity raster step)
      - population_30m.tif
      - dist_roads.tif
      - dist_settlements.tif
      - slope_degrees.tif
      - land_cover_30m.tif        (reclassified)

    Returns dict {criterion_name: Path}
    """
    criteria = {
        "distance_to_health_facility": interim_dir / "dist_health_facility_aligned.tif",
        "population_density":          interim_dir / "population_30m_aligned.tif",
        "distance_to_roads":           interim_dir / "dist_roads_aligned.tif",
        "distance_to_settlements":     interim_dir / "dist_settlements_aligned.tif",
        "slope":                       interim_dir / "slope_degrees_aligned.tif",
        "land_cover_suitability":      interim_dir / "land_cover_hc_reclass_aligned.tif",
    }

    missing = [k for k, v in criteria.items() if not v.exists()]
    if missing:
        logger.warning(f"Missing criteria rasters: {missing}")
        logger.warning("Run notebook 02_data_preprocessing.ipynb first.")

    available = {k: v for k, v in criteria.items() if v.exists()}
    logger.info(f"Healthcare criteria ready: {len(available)} / {len(criteria)}")
    return criteria


def derive_all_agriculture_criteria(interim_dir: Path, ref_raster: Path) -> dict:
    """
    Orchestrate derivation of all agriculture criteria rasters.

    Expects:
      - ndvi_30m.tif
      - land_cover_ag_reclass.tif
      - slope_degrees.tif
      - dist_water.tif
      - dist_roads.tif
      - dist_settlements.tif
    """
    criteria = {
        "ndvi":                    interim_dir / "ndvi_30m_aligned.tif",
        "land_cover_suitability":  interim_dir / "land_cover_ag_reclass.tif",
        "slope":                   interim_dir / "slope_degrees_aligned.tif",
        "distance_to_water":       interim_dir / "dist_water_aligned.tif",
        "distance_to_roads":       interim_dir / "dist_roads_aligned.tif",
        "distance_to_settlements": interim_dir / "dist_settlements_aligned.tif",
    }

    missing = [k for k, v in criteria.items() if not v.exists()]
    if missing:
        logger.warning(f"Missing criteria rasters: {missing}")

    available = {k: v for k, v in criteria.items() if v.exists()}
    logger.info(f"Agriculture criteria ready: {len(available)} / {len(criteria)}")
    return criteria


def reclassify_land_cover(lc_path: Path, output_path: Path,
                           reclass_map: dict) -> Path:
    """
    Reclassify ESA WorldCover integer class raster to float suitability scores.

    Args:
        lc_path: Input land cover raster (integer class codes).
        output_path: Output float raster (0–1 suitability).
        reclass_map: Dict {class_code (int): suitability_score (float)}.

    Returns:
        Path to output reclassified raster.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(lc_path) as src:
        lc = src.read(1)
        profile = src.profile.copy()
        profile.update(dtype="float32", nodata=np.nan)

    reclass = np.full(lc.shape, np.nan, dtype="float32")
    for code, score in reclass_map.items():
        reclass = np.where(lc == int(code), float(score), reclass)

    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(reclass, 1)

    logger.info(f"Land cover reclassified: {output_path}")
    return output_path


def derive_population_density(pop_path: Path, output_path: Path,
                               pixel_size_m: float = 30.0) -> Path:
    """
    Convert WorldPop pixel count raster to persons per km².

    WorldPop provides estimated persons per pixel.
    Density (p/km²) = pixel_value / (pixel_area_km²)

    Args:
        pop_path: Input WorldPop raster (persons per pixel).
        output_path: Output density raster (p/km²).
        pixel_size_m: Pixel size in metres after resampling.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pixel_area_km2 = (pixel_size_m / 1000) ** 2  # convert m² to km²

    with rasterio.open(pop_path) as src:
        pop = src.read(1).astype("float32")
        nodata = src.nodata
        profile = src.profile.copy()
        profile.update(dtype="float32", nodata=np.nan)

    pop = np.where((pop == nodata) | (pop < 0), np.nan, pop)
    density = pop / pixel_area_km2

    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(density, 1)

    logger.info(f"Population density raster saved: {output_path} "
                f"(max={np.nanmax(density):.1f} p/km²)")
    return output_path
