"""Core analysis package for the convolution-analysis application."""

from .engine import (
    analyze_cv,
    calculate_k_s,
    calculate_k_s_error,
    inspect_cv,
    inspect_background_cv,
    preview_preprocessing,
    recalculate_error_analysis,
    select_error_limit,
)
from .models import (
    AnalysisConfig,
    AnalysisResult,
    BACKGROUND_CAPACITANCE,
    BACKGROUND_CV,
    CVInspection,
    KsResult,
    KsError,
    PreprocessingPreview,
)

__all__ = [
    "AnalysisConfig",
    "AnalysisResult",
    "BACKGROUND_CAPACITANCE",
    "BACKGROUND_CV",
    "CVInspection",
    "KsResult",
    "KsError",
    "PreprocessingPreview",
    "analyze_cv",
    "calculate_k_s",
    "calculate_k_s_error",
    "inspect_cv",
    "inspect_background_cv",
    "preview_preprocessing",
    "recalculate_error_analysis",
    "select_error_limit",
]

__version__ = "0.7.0"
