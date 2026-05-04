"""
suitability_model.py
--------------------
Weighted Linear Combination (WLC) suitability model engine.

Combines standardised criteria rasters with AHP-derived weights,
applies constraint masks, and produces final suitability rasters.
"""

import numpy as np
import rasterio
from pathlib import Path
from typing import Optional
from utils import setup_logger

logger = setup_logger(__name__)

# Suitability classification thresholds
SUITABILITY_CLASSES = {
    5: ("Very High", (0.80, 1.01)),
    4: ("High",      (0.60, 0.80)),
    3: ("Moderate",  (0.40, 0.60)),
    2: ("Low",       (0.20, 0.40)),
    1: ("Very Low",  (0.00, 0.20)),
}


def weighted_linear_combination(criteria_raster_paths: dict[str, Path],
                                 weights: dict[str, float],
                                 output_path: str | Path,
                                 constraint_mask_path: Optional[Path] = None,
                                 nodata: float = np.nan) -> Path:
    """
    Compute WLC suitability raster from standardised criteria rasters.

    S = Σ (w_i × c_i)  for all criteria i, subject to constraint mask.

    Args:
        criteria_raster_paths: Dict {criterion_name: Path to standardised raster}.
        weights: Dict {criterion_name: weight}. Must sum to ~1.0.
        output_path: Path for output suitability raster.
        constraint_mask_path: Optional binary mask raster (1=valid, 0=excluded).
        nodata: NoData value for output.

    Returns:
        Path to output suitability raster.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Validate weights sum
    total_weight = sum(weights.values())
    if abs(total_weight - 1.0) > 0.01:
        logger.warning(f"Weights sum to {total_weight:.4f}, normalising to 1.0")
        weights = {k: v / total_weight for k, v in weights.items()}

    # Read reference raster for profile
    ref_path = next(iter(criteria_raster_paths.values()))
    with rasterio.open(ref_path) as ref:
        profile = ref.profile.copy()
        profile.update(dtype="float32", count=1, nodata=nodata)
        shape = (ref.height, ref.width)

    # Accumulate weighted sum
    suitability = np.zeros(shape, dtype="float32")
    valid_mask = np.ones(shape, dtype=bool)

    for name, raster_path in criteria_raster_paths.items():
        if name not in weights:
            logger.warning(f"No weight for criterion '{name}', skipping.")
            continue
        with rasterio.open(raster_path) as src:
            arr = src.read(1).astype("float32")
        nan_mask = np.isnan(arr)
        valid_mask &= ~nan_mask
        arr = np.where(nan_mask, 0, arr)
        suitability += weights[name] * arr
        logger.info(f"  Applied {name}: weight={weights[name]:.4f}")

    # Apply constraint mask
    if constraint_mask_path and Path(constraint_mask_path).exists():
        with rasterio.open(constraint_mask_path) as cm:
            constraint = cm.read(1)
        suitability = np.where(constraint == 0, nodata, suitability)
        valid_mask &= (constraint == 1)
        logger.info("Constraint mask applied.")

    # Set invalid pixels to nodata
    suitability = np.where(valid_mask, suitability, nodata)

    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(suitability, 1)

    valid_vals = suitability[valid_mask]
    logger.info(f"Suitability raster saved: {output_path}")
    logger.info(f"  Valid pixels: {valid_mask.sum():,} | "
                f"Min: {valid_vals.min():.3f} | Max: {valid_vals.max():.3f} | "
                f"Mean: {valid_vals.mean():.3f}")
    return output_path


def classify_suitability(suitability_path: str | Path,
                          output_path: str | Path) -> Path:
    """
    Classify continuous suitability raster into 5 ordinal classes.

    Classes: 1=Very Low, 2=Low, 3=Moderate, 4=High, 5=Very High.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(suitability_path) as src:
        arr = src.read(1).astype("float32")
        profile = src.profile.copy()
        profile.update(dtype="uint8", nodata=0)

    classified = np.zeros(arr.shape, dtype="uint8")
    for cls_id, (_, (low, high)) in SUITABILITY_CLASSES.items():
        classified = np.where((arr >= low) & (arr < high), cls_id, classified)

    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(classified, 1)

    logger.info(f"Classified suitability saved: {output_path}")
    for cls_id, (label, (low, high)) in SUITABILITY_CLASSES.items():
        count = (classified == cls_id).sum()
        pct = count / (classified > 0).sum() * 100
        logger.info(f"  Class {cls_id} ({label:10s}) [{low:.2f}-{high:.2f}]: "
                    f"{count:,} pixels ({pct:.1f}%)")
    return output_path


def build_constraint_mask(constraint_rasters: dict[str, tuple[Path, str, float]],
                          ref_path: str | Path,
                          output_path: str | Path) -> Path:
    """
    Build a binary constraint mask from exclusion rasters.

    Args:
        constraint_rasters: Dict {name: (raster_path, operator, threshold)}
            operator: 'gt', 'lt', 'eq', 'binary'
            e.g. ('slope.tif', 'gt', 20) -> exclude where slope > 20
        ref_path: Reference raster for grid.
        output_path: Output mask path.

    Returns:
        Path to binary mask raster (1=suitable, 0=excluded).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(ref_path) as ref:
        profile = ref.profile.copy()
        shape = (ref.height, ref.width)

    profile.update(dtype="uint8", count=1, nodata=255)
    mask = np.ones(shape, dtype="uint8")

    for name, (raster_path, operator, threshold) in constraint_rasters.items():
        with rasterio.open(raster_path) as src:
            arr = src.read(1).astype("float32")

        if operator == "gt":
            exclude = arr > threshold
        elif operator == "lt":
            exclude = arr < threshold
        elif operator == "eq":
            exclude = arr == threshold
        elif operator == "binary":
            exclude = arr == 1
        else:
            raise ValueError(f"Unknown operator '{operator}'")

        excluded_count = exclude.sum()
        mask = np.where(exclude, 0, mask)
        logger.info(f"  Constraint '{name}': excluded {excluded_count:,} pixels")

    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(mask, 1)

    total = mask.size
    excluded = (mask == 0).sum()
    logger.info(f"Constraint mask saved: {output_path} | "
                f"Excluded: {excluded:,} / {total:,} ({excluded/total*100:.1f}%)")
    return output_path
