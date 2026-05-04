"""
fuzzy_standardisation.py
------------------------
Fuzzy membership functions to standardise criteria rasters to a
common [0, 1] suitability scale.

Supported functions:
  - linear_increase  : low -> 0, high -> 1
  - linear_decrease  : low -> 1, high -> 0
  - triangular       : peak at midpoint
  - trapezoidal      : flat top between b and c
"""

import numpy as np
import rasterio
from pathlib import Path
from utils import setup_logger

logger = setup_logger(__name__)


def fuzzy_linear_increase(arr: np.ndarray, low: float, high: float,
                           nodata=None) -> np.ndarray:
    """
    Linear increase membership: low -> 0, high -> 1.

         1 |          /-------
           |         /
         0 |--------/
               low  high
    """
    result = np.where(arr <= low, 0.0,
             np.where(arr >= high, 1.0,
                      (arr - low) / (high - low)))
    if nodata is not None:
        result = np.where(arr == nodata, np.nan, result)
    return result.astype("float32")


def fuzzy_linear_decrease(arr: np.ndarray, low: float, high: float,
                           nodata=None) -> np.ndarray:
    """
    Linear decrease membership: low -> 1, high -> 0.

         1 |---\
           |    \
         0 |     \-------
               low  high
    """
    result = np.where(arr <= low, 1.0,
             np.where(arr >= high, 0.0,
                      (high - arr) / (high - low)))
    if nodata is not None:
        result = np.where(arr == nodata, np.nan, result)
    return result.astype("float32")


def fuzzy_triangular(arr: np.ndarray, a: float, b: float, c: float,
                     nodata=None) -> np.ndarray:
    """
    Triangular membership: 0 at a and c, 1 at b.

         1 |     /\
           |    /  \
         0 |---/    \---
               a   b   c
    """
    result = np.where(arr <= a, 0.0,
             np.where(arr <= b, (arr - a) / (b - a),
             np.where(arr <= c, (c - arr) / (c - b),
                      0.0)))
    if nodata is not None:
        result = np.where(arr == nodata, np.nan, result)
    return result.astype("float32")


def fuzzy_trapezoidal(arr: np.ndarray, a: float, b: float, c: float, d: float,
                      nodata=None) -> np.ndarray:
    """
    Trapezoidal membership: 0 outside [a,d], 1 inside [b,c].

         1 |     /------\
           |    /        \
         0 |---/          \---
               a  b    c  d
    """
    result = np.where(arr <= a, 0.0,
             np.where(arr <= b, (arr - a) / (b - a),
             np.where(arr <= c, 1.0,
             np.where(arr <= d, (d - arr) / (d - c),
                      0.0))))
    if nodata is not None:
        result = np.where(arr == nodata, np.nan, result)
    return result.astype("float32")


# ─── Dispatcher ──────────────────────────────────────────────────────────────

FUZZY_FUNCTIONS = {
    "linear_increase": fuzzy_linear_increase,
    "linear_decrease": fuzzy_linear_decrease,
    "triangular": fuzzy_triangular,
    "trapezoidal": fuzzy_trapezoidal,
}


def standardise_raster(src_path: str | Path, dst_path: str | Path,
                        fuzzy_type: str, fuzzy_params: dict,
                        nodata: float = None) -> Path:
    """
    Apply fuzzy standardisation to a criteria raster.

    Args:
        src_path: Input criteria raster.
        dst_path: Output standardised raster (values 0-1).
        fuzzy_type: One of 'linear_increase', 'linear_decrease',
                    'triangular', 'trapezoidal'.
        fuzzy_params: Dict of control points for the membership function.
        nodata: NoData value to propagate.

    Returns:
        Path to output standardised raster.
    """
    src_path, dst_path = Path(src_path), Path(dst_path)
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    if fuzzy_type not in FUZZY_FUNCTIONS:
        raise ValueError(f"Unknown fuzzy_type '{fuzzy_type}'. "
                         f"Choose from: {list(FUZZY_FUNCTIONS.keys())}")

    func = FUZZY_FUNCTIONS[fuzzy_type]

    with rasterio.open(src_path) as src:
        arr = src.read(1).astype("float32")
        nd = nodata if nodata is not None else src.nodata
        profile = src.profile.copy()
        profile.update(dtype="float32", nodata=np.nan)

    standardised = func(arr, **fuzzy_params, nodata=nd)

    with rasterio.open(dst_path, "w", **profile) as dst:
        dst.write(standardised, 1)

    logger.info(f"Standardised raster saved: {dst_path} | "
                f"type={fuzzy_type} | "
                f"min={np.nanmin(standardised):.3f} max={np.nanmax(standardised):.3f}")
    return dst_path


def standardise_all_criteria(criteria_config: dict,
                              interim_dir: str | Path = "data/interim",
                              processed_dir: str | Path = "data/processed",
                              prefix: str = "") -> dict[str, Path]:
    """
    Standardise all criteria defined in a model config.

    Args:
        criteria_config: Dict of criterion definitions from YAML config.
        interim_dir: Directory containing input criteria rasters.
        processed_dir: Directory to save standardised rasters.
        prefix: Model prefix (e.g. 'healthcare' or 'agriculture').

    Returns:
        Dict mapping criterion name to output raster path.
    """
    processed_dir = Path(processed_dir)
    outputs = {}
    for name, cfg in criteria_config.items():
        src = Path(interim_dir) / f"{prefix}_{name}.tif"
        dst = processed_dir / f"{prefix}_{name}_std.tif"
        if not src.exists():
            logger.warning(f"Input raster not found, skipping: {src}")
            continue
        outputs[name] = standardise_raster(
            src_path=src,
            dst_path=dst,
            fuzzy_type=cfg["fuzzy_type"],
            fuzzy_params=cfg["fuzzy_params"])
    return outputs
