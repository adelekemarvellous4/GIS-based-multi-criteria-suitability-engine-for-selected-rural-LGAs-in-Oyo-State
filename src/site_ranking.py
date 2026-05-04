"""
site_ranking.py
---------------
Extract and rank candidate sites from suitability rasters.

Steps:
  1. Threshold suitability raster to extract high-suitability zones
  2. Vectorise zones to polygons
  3. Filter by minimum area
  4. Attach ranking attributes (score, area, access, demand, uncertainty)
  5. Rank and export top-N candidate sites
"""

import numpy as np
import rasterio
from rasterio.features import shapes
import geopandas as gpd
from shapely.geometry import shape
from pathlib import Path
from typing import Optional
from utils import setup_logger

logger = setup_logger(__name__)


def extract_candidate_sites(suitability_path: str | Path,
                             min_score: float = 0.65,
                             min_area_ha: float = 0.5,
                             study_area_gdf: Optional[gpd.GeoDataFrame] = None,
                             output_path: Optional[str | Path] = None) -> gpd.GeoDataFrame:
    """
    Extract contiguous high-suitability zones as candidate site polygons.

    Args:
        suitability_path: Continuous suitability raster (0-1).
        min_score: Minimum suitability score to include as candidate.
        min_area_ha: Minimum polygon area (hectares).
        study_area_gdf: Optional mask to clip results to study area.
        output_path: If given, save result as GeoPackage.

    Returns:
        GeoDataFrame of candidate site polygons with suitability stats.
    """
    suitability_path = Path(suitability_path)

    with rasterio.open(suitability_path) as src:
        arr = src.read(1).astype("float32")
        transform = src.transform
        crs = src.crs
        pixel_area_m2 = abs(transform.a * transform.e)
        pixel_area_ha = pixel_area_m2 / 10_000

    # Binary mask of high suitability
    binary = (arr >= min_score).astype("uint8")
    binary = np.where(np.isnan(arr), 0, binary)

    # Vectorise contiguous patches
    results = []
    for geom, val in shapes(binary, mask=binary, transform=transform):
        if val == 1:
            polygon = shape(geom)
            area_ha = polygon.area / 10_000
            if area_ha >= min_area_ha:
                # Extract suitability stats for this patch
                from rasterio.mask import mask as rmask
                try:
                    patch_arr, _ = rmask(
                        rasterio.open(suitability_path),
                        [geom], crop=True, nodata=np.nan)
                    patch_vals = patch_arr[~np.isnan(patch_arr)]
                    mean_score = float(np.mean(patch_vals)) if len(patch_vals) > 0 else 0
                    max_score = float(np.max(patch_vals)) if len(patch_vals) > 0 else 0
                except Exception:
                    mean_score = max_score = min_score

                results.append({
                    "geometry": polygon,
                    "mean_suitability": round(mean_score, 4),
                    "max_suitability": round(max_score, 4),
                    "area_ha": round(area_ha, 2),
                    "n_pixels": int(area_ha / pixel_area_ha),
                })

    if not results:
        logger.warning(f"No candidate sites found above score={min_score}, area={min_area_ha}ha")
        return gpd.GeoDataFrame(columns=["geometry", "mean_suitability",
                                         "max_suitability", "area_ha"])

    gdf = gpd.GeoDataFrame(results, crs=crs)
    gdf = gdf.reset_index(drop=True)

    if study_area_gdf is not None:
        gdf = gdf.clip(study_area_gdf.to_crs(crs))

    logger.info(f"Extracted {len(gdf)} candidate site polygons "
                f"(score>={min_score}, area>={min_area_ha}ha)")

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(output_path, driver="GPKG")
        logger.info(f"Candidate sites saved: {output_path}")

    return gdf


def rank_candidate_sites(sites_gdf: gpd.GeoDataFrame,
                          ranking_criteria: list[str],
                          uncertainty_path: Optional[Path] = None,
                          population_path: Optional[Path] = None,
                          roads_gdf: Optional[gpd.GeoDataFrame] = None,
                          top_n: int = 20) -> gpd.GeoDataFrame:
    """
    Rank candidate sites by composite score across multiple criteria.

    Args:
        sites_gdf: GeoDataFrame of candidate site polygons.
        ranking_criteria: List of attribute names to rank by.
        uncertainty_path: Optional uncertainty std raster (lower = better).
        population_path: Optional population raster for demand score.
        roads_gdf: Optional road network for distance-to-road attribute.
        top_n: Number of top sites to return.

    Returns:
        Ranked GeoDataFrame with 'rank' and 'composite_score' columns.
    """
    gdf = sites_gdf.copy()

    # Attach uncertainty score (mean CV within patch centroid)
    if uncertainty_path and Path(uncertainty_path).exists():
        centroids = gdf.geometry.centroid
        with rasterio.open(uncertainty_path) as src:
            coords = [(pt.x, pt.y) for pt in centroids]
            uncertainty_vals = [x[0] for x in src.sample(coords)]
        gdf["uncertainty_score"] = [round(v, 4) for v in uncertainty_vals]
    else:
        gdf["uncertainty_score"] = 0.0

    # Attach distance to nearest road
    if roads_gdf is not None:
        roads_union = roads_gdf.to_crs(gdf.crs).unary_union
        gdf["distance_to_road"] = gdf.geometry.centroid.distance(roads_union).round(1)
    elif "distance_to_road" not in gdf.columns:
        gdf["distance_to_road"] = np.nan

    # Composite rank score using available criteria
    # Normalise each criterion to 0-1 then average
    score_cols = []
    for col in ["mean_suitability", "area_ha"]:
        if col in gdf.columns:
            col_norm = f"_norm_{col}"
            rng = gdf[col].max() - gdf[col].min()
            gdf[col_norm] = (gdf[col] - gdf[col].min()) / rng if rng > 0 else 0.5
            score_cols.append(col_norm)

    # Lower uncertainty = better
    if "uncertainty_score" in gdf.columns and gdf["uncertainty_score"].notna().any():
        col_norm = "_norm_certainty"
        rng = gdf["uncertainty_score"].max() - gdf["uncertainty_score"].min()
        gdf[col_norm] = 1 - ((gdf["uncertainty_score"] - gdf["uncertainty_score"].min())
                             / rng) if rng > 0 else 0.5
        score_cols.append(col_norm)

    if score_cols:
        gdf["composite_score"] = gdf[score_cols].mean(axis=1).round(4)
    else:
        gdf["composite_score"] = gdf["mean_suitability"]

    gdf = gdf.sort_values("composite_score", ascending=False).head(top_n)
    gdf["rank"] = range(1, len(gdf) + 1)

    # Clean up normalisation columns
    gdf = gdf[[c for c in gdf.columns if not c.startswith("_norm_")]]
    gdf = gdf.reset_index(drop=True)

    logger.info(f"Ranked top {len(gdf)} candidate sites.")
    return gdf
