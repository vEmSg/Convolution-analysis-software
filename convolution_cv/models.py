from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import hashlib


@dataclass(frozen=True)
class SourceSnapshot:
    """The exact bytes parsed for a calculation, independent of later file edits."""

    path: Path
    content: bytes = field(repr=False)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    def current_status(self) -> str:
        try:
            return "unchanged" if self.path.read_bytes() == self.content else "changed"
        except OSError:
            return "unavailable"


SegmentMap = Dict[Tuple[int, int], str]
BACKGROUND_CAPACITANCE = "double_layer_capacitance"
BACKGROUND_CV = "background_cv"


@dataclass
class CVInspection:
    """Validated CV input and metadata used by the Import stage."""

    input_path: Path
    columns: List[str]
    potential_column: str
    current_column: str
    total_rows: int
    valid_rows: int
    discarded_rows: int
    potential: np.ndarray
    current: np.ndarray
    segments: SegmentMap
    warnings: List[str] = field(default_factory=list)
    source: SourceSnapshot | None = None

    @property
    def complete_cycles(self) -> int:
        return len(self.segments) // 2


@dataclass
class PreprocessingPreview:
    """Raw and processed traces displayed before the full analysis."""

    input_path: Path
    potential: np.ndarray
    raw_current: np.ndarray
    corrected_current: np.ndarray
    smoothed_current: np.ndarray
    delta_e: float
    delta_t: float
    segments: SegmentMap
    warnings: List[str] = field(default_factory=list)
    source: SourceSnapshot | None = None
    background_source: SourceSnapshot | None = None
    smoothing_enabled: bool = True
    smoothing_window_mv: float = 20.0
    smoothing_order: int = 2
    smoothing_points: int = 0
    smoothing_effective_mv: float = 0.0
    background_current: np.ndarray | None = None


@dataclass(frozen=True)
class KsResult:
    """Current-code standard rate constant evaluated near E0."""

    e0: float
    nearest_potential: float
    index: int
    lgk_r: float
    lgk_o: float
    lgk_s: float
    k_s: float
    method: str = "geometric mean of kO and kR at the reverse-scan point nearest E0"


@dataclass(frozen=True)
class KsError:
    """Conservative envelope from the four branch bounds at the fixed k_s sample."""

    status: str
    index: int | None = None
    lower_cm_per_s: float | None = None
    upper_cm_per_s: float | None = None
    symmetric_error_cm_per_s: float | None = None
    log10_lower: float | None = None
    log10_upper: float | None = None
    reason: str = ""
    method: str = "four-bound geometric-mean envelope; symmetric error is the larger deviation"


@dataclass(frozen=True)
class AnalysisConfig:
    """Validated numerical inputs for one convolution analysis."""

    n_e: int
    diameter: float
    cv_cycles_n: int
    diffusion_o: float
    diffusion_r: float
    double_layer_capacity: float
    temperature: float
    scan_rate: float
    lgk_error_limit: float
    sigma_current: float
    sigma_cdl: float
    sigma_diameter: float
    sigma_diffusion_o: float
    sigma_diffusion_r: float
    background_mode: str = BACKGROUND_CAPACITANCE
    background_cv_path: str = ""
    smoothing_enabled: bool = True
    smoothing_window_mv: float = 20.0
    smoothing_order: int = 2
    uncertainty_configured: bool = True

    def validate(self) -> None:
        if not isinstance(self.uncertainty_configured, (bool, np.bool_)):
            raise ValueError("Uncertainty configuration state must be a boolean.")
        if not isinstance(self.smoothing_enabled, (bool, np.bool_)):
            raise ValueError("Smoothing enabled must be a boolean.")
        if self.smoothing_enabled:
            if not np.isfinite(self.smoothing_window_mv) or self.smoothing_window_mv <= 0:
                raise ValueError("SG potential window must be positive and finite (mV).")
            if (isinstance(self.smoothing_order, bool)
                    or not isinstance(self.smoothing_order, (int, np.integer)) or self.smoothing_order < 0):
                raise ValueError("SG order must be a non-negative integer.")
        if self.background_mode not in {BACKGROUND_CAPACITANCE, BACKGROUND_CV}:
            raise ValueError("Background correction mode is not recognized.")
        if self.background_mode == BACKGROUND_CV and not str(self.background_cv_path).strip():
            raise ValueError("Choose a background CV file for background subtraction.")
        if isinstance(self.n_e, bool) or not isinstance(self.n_e, (int, np.integer)) or self.n_e <= 0:
            raise ValueError("N_electron must be a positive integer.")
        if (
            isinstance(self.cv_cycles_n, bool)
            or not isinstance(self.cv_cycles_n, (int, np.integer))
            or self.cv_cycles_n <= 0
        ):
            raise ValueError("N_CV_cycles must be a positive integer.")

        positive_values = {
            "electrode diameter": self.diameter,
            "Do": self.diffusion_o,
            "Dr": self.diffusion_r,
            "temperature": self.temperature,
            "Scan rate": self.scan_rate,
        }
        for name, value in positive_values.items():
            if not np.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite value.")

        nonnegative_values = {
            "double layer capacitance": self.double_layer_capacity,
            "error limit in lgk": self.lgk_error_limit,
            "error_I": self.sigma_current,
            "error_Cdl": self.sigma_cdl,
            "error_diameter": self.sigma_diameter,
            "error_Do": self.sigma_diffusion_o,
            "error_Dr": self.sigma_diffusion_r,
        }
        for name, value in nonnegative_values.items():
            if not np.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a non-negative finite value.")


@dataclass
class ConcentrationError:
    reference_index: int
    current: np.ndarray
    capacitance: np.ndarray
    parameters: np.ndarray
    non_multiD: np.ndarray
    multiD: np.ndarray
    total: np.ndarray


@dataclass
class ErrorAnalysisDetails:
    model_version: str
    estimated_bulk_concentration: float
    effective_diffusion: float
    e0_error: float
    zero_current_index: int
    concentrations: dict[str, ConcentrationError]


@dataclass
class AnalysisResult:
    """All numerical products from a single in-memory analysis."""

    input_path: Path
    potential_column: str
    current_column: str
    config: AnalysisConfig
    delta_e: float
    segments: SegmentMap
    potential: np.ndarray
    processed_current: np.ndarray
    original_conc_o: np.ndarray
    original_conc_r: np.ndarray
    original_sigma_o: np.ndarray
    original_sigma_r: np.ndarray
    forward_potential: np.ndarray
    forward_current: np.ndarray
    forward_conc_o: np.ndarray
    forward_conc_r: np.ndarray
    forward_sigma_o: np.ndarray
    forward_sigma_r: np.ndarray
    backward_potential: np.ndarray
    backward_current: np.ndarray
    backward_conc_o: np.ndarray
    backward_conc_r: np.ndarray
    backward_sigma_o: np.ndarray
    backward_sigma_r: np.ndarray
    e0: float
    forward_lgk_r: np.ndarray
    forward_lgk_o: np.ndarray
    forward_lgk_r_min: np.ndarray
    forward_lgk_r_max: np.ndarray
    forward_lgk_o_min: np.ndarray
    forward_lgk_o_max: np.ndarray
    chosen_forward_indices: np.ndarray
    backward_lgk_r_original: np.ndarray
    backward_lgk_o_original: np.ndarray
    backward_lgk_r: np.ndarray
    backward_lgk_r_min: np.ndarray
    backward_lgk_r_max: np.ndarray
    backward_lgk_o: np.ndarray
    backward_lgk_o_min: np.ndarray
    backward_lgk_o_max: np.ndarray
    chosen_backward_indices: np.ndarray
    warnings: List[str] = field(default_factory=list)
    source: SourceSnapshot | None = None
    background_source: SourceSnapshot | None = None

    error_analysis: ErrorAnalysisDetails | None = None
    concentration_reference_indices: dict[str, int] = field(default_factory=dict)
    normalization_version: str = "legacy-minimum-v1"
    # Snapshot before optional SG smoothing, retained for independent comparisons.
    background_corrected_current: np.ndarray | None = None

    @property
    def error_e0(self) -> float:
        return self.error_analysis.e0_error if self.error_analysis else float("nan")

    @property
    def processed_cycle_potential(self) -> np.ndarray:
        return np.concatenate((self.forward_potential, self.backward_potential))

    @property
    def processed_cycle_current(self) -> np.ndarray:
        return np.concatenate((self.forward_current, self.backward_current))

    @property
    def processed_cycle_conc_o(self) -> np.ndarray:
        return np.concatenate((self.forward_conc_o, self.backward_conc_o))

    @property
    def processed_cycle_conc_r(self) -> np.ndarray:
        return np.concatenate((self.forward_conc_r, self.backward_conc_r))

    @property
    def processed_cycle_sigma_o(self) -> np.ndarray:
        return np.concatenate((self.forward_sigma_o, self.backward_sigma_o))

    @property
    def processed_cycle_sigma_r(self) -> np.ndarray:
        return np.concatenate((self.forward_sigma_r, self.backward_sigma_r))
