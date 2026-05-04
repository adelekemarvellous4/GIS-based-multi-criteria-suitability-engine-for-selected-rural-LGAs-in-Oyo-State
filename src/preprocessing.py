"""
preprocessing.py
----------------
Spatial data preprocessing for the Oyo Rural Suitability Engine.

Handles:
  - CRS reprojection (vector and raster)
  - Raster clipping to study area
  - Raster resampling to common resolution
  - Raster alignment (snapping to common grid)
  - Vector cleaning and preparation
  - DEM-derived layers (slope, aspect)
  - Proximity / distance rasters
"""

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling, calculate_default_transform
from rasterio.mask import mask as rasterio_mask
from rasterio.features import rasterize
from rasterio.transform import from_bounds
import geopandas as gpd
from pathlib import Path
from utils import setup_logger

logger = setup_logger(__name__)


# ─── Raster Preprocessing ────────────────────────────────────────────────────

def reproject_raster(src_path: str | Path, dst_path: str | Path,
                     dst_crs: str, resampling=Resampling.bilinear) -> Path:
    """Reproject a raster to a target CRS."""
    src_path, dst_path = Path(src_path), Path(dst_path)
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(src_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds)
        profile = src.profile.copy()
        profile.update(crs=dst_crs, transform=transform,
                       width=width, height=height)
        with rasterio.open(dst_path, "w", **profile) as dst:
            for i in range(1, src.count + 1):
                reproject(source=rasterio.band(src, i),
                          destination=rasterio.band(dst, i),
                          src_transform=src.transform, src_crs=src.crs,
                          dst_transform=transform, dst_crs=dst_crs,
                          resampling=resampling)
    logger.info(f"Reprojected raster saved: {dst_path}")
    return dst_path


def clip_raster_to_boundary(src_path: str | Path, boundary_gdf: gpd.GeoDataFrame,
                             dst_path: str | Path) -> Path:
    """Clip a raster to a vector boundary."""
    src_path, dst_path = Path(src_path), Path(dst_path)
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(src_path) as src:
        boundary = boundary_gdf.to_crs(src.crs)
        shapes = [geom.__geo_interface__ for geom in boundary.geometry]
        out_image, out_transform = rasterio_mask(src, shapes, crop=True)
        profile = src.profile.copy()
        profile.update(transform=out_transform,
                       height=out_image.shape[1],
                       width=out_image.shape[2])
        with rasterio.open(dst_path, "w", **profile) as dst:
            dst.write(out_image)
    logger.info(f"Clipped raster saved: {dst_path}")
    return dst_path


def resample_raster(src_path: str | Path, dst_path: str | Path,
                    target_res_m: float, resampling=Resampling.bilinear) -> Path:
    """Resample raster to a target pixel resolution (in projected metres)."""
    src_path, dst_path = Path(src_path), Path(dst_path)
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(src_path) as src:
        scale = src.res[0] / target_res_m
        new_width = int(src.width * scale)
        new_height = int(src.height * scale)
        new_transform = src.transform * src.transform.scale(
            src.width / new_width, src.height / new_height)
        profile = src.profile.copy()
        profile.update(width=new_width, height=new_height,
                       transform=new_transform)
        data = src.read(
            out_shape=(src.count, new_height, new_width),
            resampling=resampling)
        with rasterio.open(dst_path, "w", **profile) as dst:
            dst.write(data)
    logger.info(f"Resampled raster saved: {dst_path}")
    return dst_path


def align_raster_to_reference(src_path: str | Path, ref_path: str | Path,
                               dst_path: str | Path,
                               resampling=Resampling.bilinear) -> Path:
    """
    Align src raster to the exact grid (extent, resolution, CRS) of a
    reference raster. Essential for consistent WLC inputs.
    """
    src_path, dst_path = Path(src_path), Path(dst_path)
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(ref_path) as ref:
        ref_meta = ref.meta.copy()
    with rasterio.open(src_path) as src:
        profile = ref_meta.copy()
        profile.update(count=src.count, dtype=src.dtypes[0])
        data = np.zeros((src.count, ref_meta["height"], ref_meta["width"]),
                        dtype=src.dtypes[0])
        with rasterio.open(dst_path, "w", **profile) as dst:
            reproject(source=rasterio.band(src, 1),
                      destination=data[0],
                      src_transform=src.transform, src_crs=src.crs,
                      dst_transform=ref_meta["transform"],
                      dst_crs=ref_meta["crs"],
                      resampling=resampling)
            dst.write(data)
    logger.info(f"Aligned raster saved: {dst_path}")
    return dst_path


# ─── DEM-Derived Layers ──────────────────────────────────────────────────────

def compute_slope(dem_path: str | Path, slope_path: str | Path) -> Path:
    """Compute slope (degrees) from a DEM using WhiteboxTools."""
    try:
        import whitebox
        wbt = whitebox.WhiteboxTools()
        wbt.slope(str(dem_path), str(slope_path), units="degrees")
        logger.info(f"Slope raster saved: {slope_path}")
    except Exception as e:
        logger.warning(f"WhiteboxTools unavailable, using numpy fallback: {e}")
        _slope_numpy(dem_path, slope_path)
    return Path(slope_path)


def _slope_numpy(dem_path: str | Path, slope_path: str | Path):
    """Numpy-based slope computation fallback."""
    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(float)
        res = src.res[0]
        dy, dx = np.gradient(dem, res, res)
        slope = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))
        profile = src.profile.copy()
        profile.update(dtype="float32")
        with rasterio.open(slope_path, "w", **profile) as dst:
            dst.write(slope.astype("float32"), 1)


# ─── Proximity Rasters ───────────────────────────────────────────────────────

def compute_proximity_raster(vector_path: str | Path, ref_raster_path: str | Path,
                              output_path: str | Path) -> Path:
    """
    Compute Euclidean distance raster from vector features.

    Args:
        vector_path: Input vector file (points, lines, or polygons).
        ref_raster_path: Reference raster for grid definition.
        output_path: Output distance raster path.

    Returns:
        Path to output distance raster.
    """
    from scipy.ndimage import distance_transform_edt

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(ref_raster_path) as ref:
        profile = ref.profile.copy()
        profile.update(dtype="float32", count=1)
        transform = ref.transform
        shape = (ref.height, ref.width)
        crs = ref.crs

    gdf = gpd.read_file(vector_path).to_crs(crs)
    burned = rasterize(
        ((geom, 1) for geom in gdf.geometry),
        out_shape=shape, transform=transform, fill=0, dtype="uint8")
    mask = burned == 0
    dist = distance_transform_edt(mask) * abs(transform.a)  # pixel_size * cells

    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(dist.astype("float32"), 1)
    logger.info(f"Proximity raster saved: {output_path}")
    return output_path


# ─── Vector Preprocessing ────────────────────────────────────────────────────

def prepare_study_area(lga_path: str | Path, lga_names: list[str],
                        target_crs: str) -> gpd.GeoDataFrame:
    """
    Filter and dissolve LGA boundaries to form the study area polygon.

    Args:
        lga_path: Path to LGA boundary file.
        lga_names: List of LGA names to include.
        target_crs: Target projected CRS.

    Returns:
        Dissolved GeoDataFrame of the study area.
    """
    gdf = gpd.read_file(lga_path)
    # Try common name field variations
    name_col = next((c for c in gdf.columns
                     if c.lower() in ["lganame", "name", "shapename", "lga_name"]),
                    gdf.columns[0])
    selected = gdf[gdf[name_col].isin(lga_names)].copy()
    if selected.empty:
        raise ValueError(f"No matching LGAs found. Check LGA names vs column '{name_col}'.")
    study_area = selected.dissolve().to_crs(target_crs)
    logger.info(f"Study area: {len(selected)} LGAs, CRS={target_crs}")
    return study_area
