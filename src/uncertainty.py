"""
uncertainty.py
--------------
Monte Carlo uncertainty and sensitivity analysis for suitability models.

Perturbs AHP weights randomly within a defined range across N iterations,
recomputes WLC each time, and derives:
  - Mean suitability raster
  - Standard deviation (uncertainty) raster
  - Coefficient of variation raster
  - Rank stability map
"""

import numpy as np
import rasterio
from pathlib import Path
from tqdm import tqdm
from utils import setup_logger

logger = setup_logger(__name__)


def monte_carlo_uncertainty(criteria_raster_paths: dict[str, Path],
                             base_weights: dict[str, float],
                             output_dir: str | Path,
                             prefix: str = "model",
                             n_iterations: int = 1000,
                             perturbation_pct: float = 0.10,
                             constraint_mask_path: Path = None,
                             seed: int = 42) -> dict[str, Path]:
    """
    Run Monte Carlo uncertainty analysis on suitability model.

    In each iteration:
      1. Perturb weights by ±perturbation_pct (uniform random)
      2. Renormalise to sum to 1
      3. Compute WLC suitability
      4. Store result

    Final outputs:
      - mean suitability raster
      - std deviation (uncertainty) raster
      - coefficient of variation raster

    Args:
        criteria_raster_paths: Dict {criterion: Path} of standardised rasters.
        base_weights: Dict {criterion: weight} from AHP.
        output_dir: Directory for uncertainty output rasters.
        prefix: Output filename prefix.
        n_iterations: Number of Monte Carlo iterations.
        perturbation_pct: Maximum fractional perturbation per weight.
        constraint_mask_path: Optional constraint mask.
        seed: Random seed for reproducibility.

    Returns:
        Dict of output raster paths: {mean, std, cv}.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    # ── Pre-load all criteria into a single stacked array for fast WLC ──────
    criteria_names = list(base_weights.keys())
    base_w = np.array([base_weights[k] for k in criteria_names], dtype="float32")
    n_crit = len(criteria_names)

    logger.info("Pre-loading criteria rasters into memory stack...")
    first_path = next(iter(criteria_raster_paths.values()))
    with rasterio.open(first_path) as src:
        profile = src.profile.copy()
        shape   = (src.height, src.width)

    profile.update(dtype="float32", count=1, nodata=np.nan)

    # Stack shape: (n_criteria, H, W) — load once, reuse every iteration
    crit_stack = np.zeros((n_crit, *shape), dtype="float32")
    for j, name in enumerate(criteria_names):
        with rasterio.open(criteria_raster_paths[name]) as src:
            arr = src.read(1).astype("float32")
        arr[np.isnan(arr)] = 0.0
        crit_stack[j] = arr

    # Valid pixel mask — pixels that have data in ALL criteria
    valid_mask = np.ones(shape, dtype=bool)
    for j in range(n_crit):
        valid_mask &= (crit_stack[j] > 0)

    # Load constraint mask
    if constraint_mask_path and Path(constraint_mask_path).exists():
        with rasterio.open(constraint_mask_path) as cm:
            constraint = cm.read(1)
        valid_mask &= (constraint == 1)

    logger.info(f"Valid pixels: {valid_mask.sum():,} / {valid_mask.size:,}")
    logger.info(f"Running {n_iterations} Monte Carlo iterations "
                f"(perturbation ±{perturbation_pct*100:.0f}%) — "
                f"vectorised NumPy, Welford algorithm...")

    # ── Welford online mean/variance — O(1) memory, fully vectorised ─────
    # Only operate on valid pixels (flattened 1D) for maximum speed
    valid_idx   = np.where(valid_mask.ravel())[0]
    crit_flat   = crit_stack.reshape(n_crit, -1)[:, valid_idx]  # (n_crit, n_valid)
    n_valid     = len(valid_idx)

    w_mean  = np.zeros(n_valid, dtype="float64")
    w_M2    = np.zeros(n_valid, dtype="float64")
    w_count = 0

    for i in tqdm(range(n_iterations), desc="MC Uncertainty"):
        # Perturb and renormalise weights — one line
        perturbed = base_w * rng.uniform(1 - perturbation_pct,
                                          1 + perturbation_pct,
                                          size=n_crit).astype("float32")
        perturbed /= perturbed.sum()

        # WLC: matrix multiply weights x criteria — single vectorised op
        # perturbed: (n_crit,)  crit_flat: (n_crit, n_valid) -> (n_valid,)
        suit = perturbed @ crit_flat   # shape: (n_valid,)

        # Welford update (scalar count — all valid pixels updated together)
        w_count += 1
        delta   = suit - w_mean
        w_mean += delta / w_count
        delta2  = suit - w_mean
        w_M2   += delta * delta2

    # ── Reconstruct full rasters from valid-pixel vectors ─────────────────
    mean_flat = np.full(valid_mask.size, np.nan, dtype="float32")
    std_flat  = np.full(valid_mask.size, np.nan, dtype="float32")
    cv_flat   = np.full(valid_mask.size, np.nan, dtype="float32")

    mean_flat[valid_idx] = w_mean.astype("float32")
    if w_count > 1:
        std_vals = np.sqrt(w_M2 / (w_count - 1)).astype("float32")
    else:
        std_vals = np.zeros(n_valid, dtype="float32")
    std_flat[valid_idx]  = std_vals
    with np.errstate(invalid="ignore"):
        cv_vals = np.where(w_mean > 0, std_vals / w_mean.astype("float32"), 0)
    cv_flat[valid_idx] = cv_vals

    mean_suit = mean_flat.reshape(shape)
    std_suit  = std_flat.reshape(shape)
    cv_suit   = cv_flat.reshape(shape)

    outputs = {}

    mean_path = output_dir / f"{prefix}_uncertainty_mean.tif"
    with rasterio.open(mean_path, "w", **profile) as dst:
        dst.write(mean_suit, 1)
    outputs["mean"] = mean_path
    logger.info(f"Mean suitability saved: {mean_path}")

    std_path = output_dir / f"{prefix}_uncertainty_std.tif"
    with rasterio.open(std_path, "w", **profile) as dst:
        dst.write(std_suit, 1)
    outputs["std"] = std_path
    logger.info(f"Std deviation saved: {std_path}")

    cv_path = output_dir / f"{prefix}_uncertainty_cv.tif"
    with rasterio.open(cv_path, "w", **profile) as dst:
        dst.write(cv_suit, 1)
    outputs["cv"] = cv_path
    logger.info(f"Coefficient of variation saved: {cv_path}")

    logger.info(f"Uncertainty summary: "
                f"mean_std={np.nanmean(std_suit):.4f} | "
                f"max_std={np.nanmax(std_suit):.4f} | "
                f"mean_cv={np.nanmean(cv_suit):.4f}")

    return outputs
