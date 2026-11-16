import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple

import numpy as np

from ..models import AnalysisConfig, BACKGROUND_CAPACITANCE
from ..smoothing import DEFAULTS as SMOOTHING_DEFAULTS, parse_smoothing


@dataclass(frozen=True)
class ParameterDefinition:
    key: str
    label: str
    unit: str
    group: str
    value_type: type = float
    minimum: float = None
    maximum: float = None
    required: bool = True
    help_text: str = ""

    def parse(self, raw_value) -> float:
        text = str(raw_value).strip()
        if not text:
            if self.required:
                raise ValueError("A value is required.")
            return 0.0
        try:
            numeric = float(text)
        except ValueError as exc:
            raise ValueError("Enter a numeric value; scientific notation is accepted.") from exc
        if not np.isfinite(numeric):
            raise ValueError("Value must be finite.")
        if self.value_type is int:
            if not numeric.is_integer():
                raise ValueError("Must be a whole number.")
            numeric = int(numeric)
        if self.minimum is not None and numeric < self.minimum:
            comparison = "greater than zero" if self.minimum > 0 else f"at least {self.minimum:g}"
            raise ValueError(f"Must be {comparison}.")
        if self.maximum is not None and numeric > self.maximum:
            raise ValueError(f"Must be no greater than {self.maximum:g}.")
        return numeric


MAIN_PARAMETERS = (
    ParameterDefinition(
        "cv_cycles_n", "CV cycle to analyze", "", "Experiment",
        int, 1, help_text="One-based index of the complete CV cycle used for kinetics.",
    ),
    ParameterDefinition(
        "n_e", "Number of electrons", "", "Experiment",
        int, 1, help_text="Number of electrons transferred in the redox reaction.",
    ),
    ParameterDefinition(
        "diameter", "Electrode diameter", "cm", "Experiment",
        float, 1e-300, help_text="Diameter of the circular working electrode.",
    ),
    ParameterDefinition(
        "scan_rate", "Scan rate", "V/s", "Experiment",
        float, 1e-300, help_text="Potential scan rate used to acquire the CV.",
    ),
    ParameterDefinition(
        "temperature", "Temperature", "K", "Experiment",
        float, 1e-300, help_text="Absolute experiment temperature.",
    ),
    ParameterDefinition(
        "diffusion_o", "Diffusion coefficient, O", "cm^2/s", "Mass transport",
        float, 1e-300, help_text="Diffusion coefficient of the oxidized species.",
    ),
    ParameterDefinition(
        "diffusion_r", "Diffusion coefficient, R", "cm^2/s", "Mass transport",
        float, 1e-300, help_text="Diffusion coefficient of the reduced species.",
    ),
    ParameterDefinition(
        "double_layer_capacity", "Double-layer capacitance",
        "F", "Background correction", float, 0,
        help_text="Capacitance used to estimate the charging-current background.",
    ),
)


ERROR_PARAMETERS = (
    ParameterDefinition(
        "sigma_current", "Current uncertainty", "A", "Measurement uncertainty",
        float, 0,
    ),
    ParameterDefinition(
        "sigma_cdl", "Capacitance uncertainty", "F", "Measurement uncertainty",
        float, 0,
    ),
    ParameterDefinition(
        "sigma_diameter_percent", "Electrode diameter uncertainty",
        "%", "Measurement uncertainty", float, 0,
    ),
    ParameterDefinition(
        "sigma_diffusion_o_percent", "Do uncertainty", "%",
        "Measurement uncertainty", float, 0,
    ),
    ParameterDefinition(
        "sigma_diffusion_r_percent", "Dr uncertainty", "%",
        "Measurement uncertainty", float, 0,
    ),
    ParameterDefinition(
        "lgk_error_limit", "Maximum allowed width in lgk", "",
        "Selection", float, 0,
    ),
)


def default_error_values() -> Dict[str, str]:
    """Editable startup values; prefilling does not run error analysis."""
    return {
        "sigma_current": "1e-6",
        "sigma_cdl": "0",
        "sigma_diameter_percent": "0",
        "sigma_diffusion_o_percent": "0",
        "sigma_diffusion_r_percent": "0",
        "lgk_error_limit": "0.3",
    }


def empty_parameter_values() -> Tuple[Dict[str, str], Dict[str, str]]:
    """Blank measurement inputs; retain the separately requested Review settings."""
    main = {definition.key: "" for definition in MAIN_PARAMETERS}
    main.update(background_mode=BACKGROUND_CAPACITANCE, background_cv_path="")
    main.update(SMOOTHING_DEFAULTS)
    return main, {definition.key: "" for definition in ERROR_PARAMETERS}


def validate_parameter_values(
    definitions: Iterable[ParameterDefinition], raw_values: Dict[str, str]
) -> Tuple[Dict[str, float], Dict[str, str]]:
    values = {}
    errors = {}
    for definition in definitions:
        try:
            values[definition.key] = definition.parse(raw_values.get(definition.key, ""))
        except ValueError as exc:
            errors[definition.key] = str(exc)
    return values, errors


def build_analysis_config(
    main_values: Dict[str, float],
    error_values: Dict[str, float] | None = None,
) -> AnalysisConfig:
    uncertainty_configured = error_values is not None
    # Disabled placeholders satisfy the numerical config schema; they are never
    # used as measured uncertainties or written into the entry fields.
    if error_values is None:
        error_values = {definition.key: 0.0 for definition in ERROR_PARAMETERS}
    diameter = float(main_values["diameter"])
    diffusion_o = float(main_values["diffusion_o"])
    diffusion_r = float(main_values["diffusion_r"])
    config = AnalysisConfig(
        n_e=int(main_values["n_e"]),
        diameter=diameter,
        cv_cycles_n=int(main_values["cv_cycles_n"]),
        diffusion_o=diffusion_o,
        diffusion_r=diffusion_r,
        double_layer_capacity=float(main_values["double_layer_capacity"]),
        temperature=float(main_values["temperature"]),
        scan_rate=float(main_values["scan_rate"]),
        lgk_error_limit=float(error_values["lgk_error_limit"]),
        sigma_current=float(error_values["sigma_current"]),
        sigma_cdl=float(error_values["sigma_cdl"]),
        sigma_diameter=float(error_values["sigma_diameter_percent"]) * diameter / 100.0,
        sigma_diffusion_o=(
            float(error_values["sigma_diffusion_o_percent"]) * diffusion_o / 100.0
        ),
        sigma_diffusion_r=(
            float(error_values["sigma_diffusion_r_percent"]) * diffusion_r / 100.0
        ),
        background_mode=str(
            main_values.get("background_mode", BACKGROUND_CAPACITANCE)
        ),
        background_cv_path=str(main_values.get("background_cv_path", "")),
        uncertainty_configured=uncertainty_configured,
        **parse_smoothing(main_values),
    )
    config.validate()
    return config


def preset_payload(main_values: Dict[str, str], error_values: Dict[str, str]) -> dict:
    return {
        "format": "convolution-analysis-parameter-preset",
        "version": 1,
        "main_parameters": dict(main_values),
        "error_parameters": dict(error_values),
    }


def load_preset(path: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    path = Path(path).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("format") != "convolution-analysis-parameter-preset":
        raise ValueError("This file is not a convolution-analysis parameter preset.")
    main_defaults, error_defaults = empty_parameter_values()
    main_defaults.update({key: str(value) for key, value in payload.get("main_parameters", {}).items()})
    error_defaults.update({key: str(value) for key, value in payload.get("error_parameters", {}).items()})
    background = main_defaults.get("background_cv_path", "")
    if background:
        candidate = Path(background).expanduser()
        if not candidate.is_absolute():
            main_defaults["background_cv_path"] = str((path.parent / candidate).resolve())
    return main_defaults, error_defaults
