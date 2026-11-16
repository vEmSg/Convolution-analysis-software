from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Dict, Optional
import math

from ..models import AnalysisResult, CVInspection, PreprocessingPreview
from ..back_simulation import BackSimulation


def same_values(left, right):
    """Compare numeric text and parsed values without spurious invalidation."""
    if left.keys() != right.keys():
        return False
    for key, value in left.items():
        other = right[key]
        if str(value).lower() in {"true", "false"} and str(other).lower() in {"true", "false"}:
            if str(value).lower() != str(other).lower():
                return False
            continue
        try:
            if not math.isclose(float(value), float(other), rel_tol=1e-12, abs_tol=0):
                return False
        except (TypeError, ValueError):
            if value != other:
                return False
    return True


class Stage(IntEnum):
    IMPORT = 1
    CONFIGURE = 2
    REVIEW = 3
    RESULTS = 4


@dataclass
class SessionState:
    stage: Stage = Stage.IMPORT
    inspection: Optional[CVInspection] = None
    main_values: Dict[str, float] = field(default_factory=dict)
    error_values: Dict[str, float] = field(default_factory=dict)
    preview: Optional[PreprocessingPreview] = None
    main_result: Optional[AnalysisResult] = None
    error_result: Optional[AnalysisResult] = None
    preview_outdated: bool = False
    result_outdated: bool = False
    error_outdated: bool = False
    saved_path: Optional[Path] = None
    calculating: bool = False
    simulation_result: Optional[BackSimulation] = None
    simulation_outdated: bool = False

    @property
    def current_result(self) -> Optional[AnalysisResult]:
        return self.error_result or self.main_result

    @property
    def has_unsaved_result(self) -> bool:
        return self.current_result is not None and self.saved_path is None

    @property
    def configure_complete(self) -> bool:
        """Current main settings have produced a successful preprocessing preview."""
        return self.inspection is not None and self.preview is not None and not self.preview_outdated

    def set_import(self, inspection: CVInspection) -> None:
        changed = (
            self.inspection is None
            or self.inspection.input_path != inspection.input_path
            or self.inspection.potential_column != inspection.potential_column
            or self.inspection.current_column != inspection.current_column
            or self.inspection.source != inspection.source
        )
        self.inspection = inspection
        self.stage = Stage.IMPORT
        if changed:
            self.simulation_result = None
            self.simulation_outdated = False
            self.preview = None
            self.main_result = None
            self.error_result = None
            self.preview_outdated = False
            self.result_outdated = False
            self.error_outdated = False
            self.saved_path = None

    def clear_import(self) -> None:
        self.simulation_result = None
        self.simulation_outdated = False
        self.inspection = None
        self.preview = None
        self.main_result = None
        self.error_result = None
        self.saved_path = None
        self.stage = Stage.IMPORT
        self.preview_outdated = False
        self.result_outdated = False
        self.error_outdated = False

    def set_main_values(self, values: Dict[str, float]) -> None:
        if self.main_values and not same_values(values, self.main_values):
            self.preview_outdated = self.preview is not None
            self.result_outdated = self.main_result is not None
            self.error_outdated = self.error_result is not None
        self.main_values = dict(values)

    def set_error_values(self, values: Dict[str, float], limit_only: bool = False) -> None:
        if self.error_values and not same_values(values, self.error_values):
            self.error_outdated = self.error_result is not None and not limit_only
        self.error_values = dict(values)

    def set_preview(self, preview: PreprocessingPreview) -> None:
        self.preview = preview
        self.preview_outdated = False
        self.stage = Stage.REVIEW

    def set_main_result(self, result: AnalysisResult) -> None:
        self.simulation_result = None
        self.simulation_outdated = False
        self.main_result = result
        self.error_result = None
        self.result_outdated = False
        self.error_outdated = False
        self.saved_path = None
        self.stage = Stage.RESULTS

    def set_error_result(self, result: AnalysisResult) -> None:
        self.error_result = result
        self.error_outdated = False
        self.saved_path = None

    def set_simulation_result(self, result: BackSimulation) -> None:
        self.simulation_result = result
        self.simulation_outdated = False
        self.saved_path = None

    def mark_saved(self, path: Path) -> None:
        self.saved_path = Path(path)

    def reset(self) -> None:
        main_values = dict(self.main_values)
        error_values = dict(self.error_values)
        self.__dict__.update(SessionState().__dict__)
        self.main_values = main_values
        self.error_values = error_values
