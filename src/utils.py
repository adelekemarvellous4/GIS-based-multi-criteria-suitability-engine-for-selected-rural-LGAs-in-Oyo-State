"""
utils.py
--------
Shared utility functions for the Oyo Rural Suitability Engine.
"""

import os
import yaml
import logging
from pathlib import Path


# ─── Logging ────────────────────────────────────────────────────────────────

def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Return a configured logger."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                                datefmt="%Y-%m-%d %H:%M:%S")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


# ─── Config Loading ──────────────────────────────────────────────────────────

def load_config(config_path: str | Path) -> dict:
    """Load a YAML configuration file and return as dict."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def load_all_configs(config_dir: str | Path = "config") -> dict:
    """Load all YAML configs from the config directory."""
    config_dir = Path(config_dir)
    configs = {}
    for yml_file in config_dir.glob("*.yml"):
        key = yml_file.stem
        configs[key] = load_config(yml_file)
    return configs


# ─── Path Helpers ────────────────────────────────────────────────────────────

def ensure_dirs(paths: list[str | Path]) -> None:
    """Create directories if they do not already exist."""
    for p in paths:
        Path(p).mkdir(parents=True, exist_ok=True)


def project_root() -> Path:
    """Return the project root directory (parent of src/)."""
    return Path(__file__).resolve().parent.parent


# ─── Raster Helpers ─────────────────────────────────────────────────────────

def get_raster_info(raster_path: str | Path) -> dict:
    """Return basic metadata for a raster file."""
    import rasterio
    with rasterio.open(raster_path) as src:
        return {
            "crs": src.crs.to_string(),
            "transform": src.transform,
            "width": src.width,
            "height": src.height,
            "count": src.count,
            "dtype": src.dtypes[0],
            "nodata": src.nodata,
            "bounds": src.bounds,
        }


# ─── Vector Helpers ──────────────────────────────────────────────────────────

def reproject_vector(gdf, target_crs: str):
    """Reproject a GeoDataFrame to target CRS."""
    return gdf.to_crs(target_crs)
