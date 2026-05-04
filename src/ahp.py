"""
ahp.py
------
Analytic Hierarchy Process (AHP) implementation for criteria weighting.

Provides:
  - Pairwise comparison matrix input and validation
  - Priority vector (weights) derivation via eigenvector method
  - Consistency Ratio (CR) check
  - Interactive matrix builder helper
"""

import numpy as np
from utils import setup_logger

logger = setup_logger(__name__)

# Saaty's Random Consistency Index (RI) lookup for n=1..10
RI_TABLE = {1: 0.00, 2: 0.00, 3: 0.58, 4: 0.90, 5: 1.12,
            6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}


class AHP:
    """
    Analytic Hierarchy Process weight calculator.

    Usage:
        # Define pairwise comparison matrix (upper triangle only)
        # Values: 1=equal, 3=moderate, 5=strong, 7=very strong, 9=extreme
        comparisons = {
            ('distance_to_health_facility', 'population_density'): 1.5,
            ('distance_to_health_facility', 'distance_to_roads'): 2,
            ...
        }
        ahp = AHP(criteria_names, comparisons)
        weights = ahp.weights       # dict: {name: weight}
        print(ahp.consistency_report())
    """

    def __init__(self, criteria: list[str],
                 comparisons: dict[tuple, float] | np.ndarray):
        """
        Initialise AHP with criteria names and pairwise comparisons.

        Args:
            criteria: List of criterion names.
            comparisons: Either:
                - dict {(name_i, name_j): value} for upper triangle, OR
                - n×n numpy array (full comparison matrix).
        """
        self.criteria = criteria
        self.n = len(criteria)
        self._matrix = self._build_matrix(comparisons)
        self._weights, self._lambda_max, self._ci, self._cr = self._compute()

    def _build_matrix(self, comparisons) -> np.ndarray:
        if isinstance(comparisons, np.ndarray):
            return comparisons.astype(float)
        n = self.n
        idx = {name: i for i, name in enumerate(self.criteria)}
        matrix = np.ones((n, n))
        for (a, b), val in comparisons.items():
            i, j = idx[a], idx[b]
            matrix[i, j] = val
            matrix[j, i] = 1.0 / val
        return matrix

    def _compute(self):
        matrix = self._matrix
        n = self.n
        # Normalise columns
        col_sums = matrix.sum(axis=0)
        norm = matrix / col_sums
        # Priority vector
        priority = norm.mean(axis=1)
        # Lambda max
        weighted_sum = matrix @ priority
        lambda_max = np.mean(weighted_sum / priority)
        # Consistency Index
        ci = (lambda_max - n) / (n - 1) if n > 1 else 0
        # Consistency Ratio
        ri = RI_TABLE.get(n, 1.49)
        cr = ci / ri if ri > 0 else 0
        return priority, lambda_max, ci, cr

    @property
    def weights(self) -> dict[str, float]:
        """Return criteria weights as a dict."""
        return dict(zip(self.criteria, self._weights))

    @property
    def weights_array(self) -> np.ndarray:
        return self._weights

    @property
    def consistency_ratio(self) -> float:
        return self._cr

    @property
    def is_consistent(self) -> bool:
        return self._cr < 0.10

    def consistency_report(self) -> str:
        lines = [
            "=" * 50,
            "AHP CONSISTENCY REPORT",
            "=" * 50,
            f"  n criteria   : {self.n}",
            f"  λ_max        : {self._lambda_max:.4f}",
            f"  CI           : {self._ci:.4f}",
            f"  RI           : {RI_TABLE.get(self.n, 1.49):.2f}",
            f"  CR           : {self._cr:.4f}",
            f"  Acceptable   : {'YES ✓' if self.is_consistent else 'NO ✗  (CR must be < 0.10)'}",
            "",
            "  DERIVED WEIGHTS:",
        ]
        for name, w in self.weights.items():
            lines.append(f"    {name:<40} {w:.4f}  ({w*100:.1f}%)")
        lines.append("=" * 50)
        return "\n".join(lines)

    def to_config_weights(self) -> dict[str, float]:
        """Return weights rounded to 4 dp, ready to paste into YAML config."""
        return {k: round(v, 4) for k, v in self.weights.items()}


# ─── Healthcare AHP Template ─────────────────────────────────────────────────

def build_healthcare_ahp() -> AHP:
    """
    Default AHP for healthcare suitability.
    Pairwise comparisons based on literature and expert judgment.
    Modify values to reflect local expert input.
    """
    criteria = [
        "distance_to_health_facility",
        "population_density",
        "distance_to_roads",
        "distance_to_settlements",
        "slope",
        "land_cover_suitability",
    ]
    # Upper-triangle comparisons (row vs column)
    # Value > 1: row is more important than column
    comparisons = {
        ("distance_to_health_facility", "population_density"):       1.5,
        ("distance_to_health_facility", "distance_to_roads"):        2.0,
        ("distance_to_health_facility", "distance_to_settlements"):  3.0,
        ("distance_to_health_facility", "slope"):                    4.0,
        ("distance_to_health_facility", "land_cover_suitability"):   5.0,
        ("population_density",          "distance_to_roads"):        1.5,
        ("population_density",          "distance_to_settlements"):  2.5,
        ("population_density",          "slope"):                    3.0,
        ("population_density",          "land_cover_suitability"):   4.0,
        ("distance_to_roads",           "distance_to_settlements"):  2.0,
        ("distance_to_roads",           "slope"):                    2.5,
        ("distance_to_roads",           "land_cover_suitability"):   3.0,
        ("distance_to_settlements",     "slope"):                    1.5,
        ("distance_to_settlements",     "land_cover_suitability"):   2.0,
        ("slope",                       "land_cover_suitability"):   2.0,
    }
    return AHP(criteria, comparisons)


# ─── Agriculture AHP Template ────────────────────────────────────────────────

def build_agriculture_ahp() -> AHP:
    """
    Default AHP for agriculture suitability.
    Modify comparisons to reflect local expert input.
    """
    criteria = [
        "ndvi",
        "land_cover_suitability",
        "slope",
        "distance_to_water",
        "distance_to_roads",
        "distance_to_settlements",
    ]
    comparisons = {
        ("ndvi",                    "land_cover_suitability"):  1.5,
        ("ndvi",                    "slope"):                   2.0,
        ("ndvi",                    "distance_to_water"):       2.0,
        ("ndvi",                    "distance_to_roads"):       3.0,
        ("ndvi",                    "distance_to_settlements"): 3.0,
        ("land_cover_suitability",  "slope"):                   1.5,
        ("land_cover_suitability",  "distance_to_water"):       1.5,
        ("land_cover_suitability",  "distance_to_roads"):       2.5,
        ("land_cover_suitability",  "distance_to_settlements"): 2.5,
        ("slope",                   "distance_to_water"):       1.0,
        ("slope",                   "distance_to_roads"):       2.0,
        ("slope",                   "distance_to_settlements"): 2.0,
        ("distance_to_water",       "distance_to_roads"):       2.0,
        ("distance_to_water",       "distance_to_settlements"): 2.0,
        ("distance_to_roads",       "distance_to_settlements"): 1.0,
    }
    return AHP(criteria, comparisons)
