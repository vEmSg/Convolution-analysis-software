import json
import re
import math
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

import pandas as pd

from . import __version__
from .engine import calculate_k_s, calculate_k_s_error
from .models import AnalysisResult, BACKGROUND_CV
from .plotting import save_result_figures
from .readable_report import write_readable_report
from .uncertainty import error_metadata, error_columns
from .normalization import normalization_metadata


class ExportCancelled(Exception):
    """A partial export is retained with an explicit cancelled manifest."""


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned or "analysis"


def _error_window_payload(potential, indices):
    if not len(indices):
        return None
    selected = [float(potential[int(index)]) for index in indices]
    return {"minimum_v": min(selected), "maximum_v": max(selected)}


def create_run_directory(output_root: str, input_path: Path) -> Path:
    root = Path(output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    base_name = f"{_safe_name(input_path.stem)}_{timestamp}"
    run_directory = root / base_name
    suffix = 1
    while run_directory.exists():
        run_directory = root / f"{base_name}_{suffix}"
        suffix += 1
    run_directory.mkdir()
    return run_directory


def output_paths(run_directory: Path) -> Dict[str, str]:
    return {
        "processed_CVs_folder": str(run_directory / "1_processed_CVs"),
        "original_conc_folder": str(run_directory / "2_original_conc"),
        "processed_conc_folder": str(run_directory / "3_processed_conc"),
        "original_lgk_folder": str(run_directory / "4_original_lgk"),
        "error_and_final_results_folder": str(run_directory / "5_error_and_final_results"),
        "figures_folder": str(run_directory / "6_plots"),
    }


def _write_json_atomic(path: Path, payload: dict) -> None:
    def clean(value):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        return value
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(clean(payload), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def initial_manifest(result: AnalysisResult, run_directory: Path, *, include_input_copy: bool = True) -> dict:
    manifest = {
        "status": "running",
        "software_version": __version__,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": {
            "path": f"input/{result.input_path.name}" if include_input_copy else None,
            "name": result.input_path.name,
            "sha256": result.source.sha256 if result.source else None,
            "status_at_save": result.source.current_status() if result.source else "not captured",
            "potential_column": result.potential_column,
            "current_column": result.current_column,
        },
        "config": asdict(result.config),
        "error_analysis": error_metadata(result),
        "concentration_normalization": normalization_metadata(result),
        "k_s_uncertainty": asdict(calculate_k_s_error(result)),
        "warnings": list(result.warnings),
        "run_directory": ".",
        "path_basis": "relative to manifest.json; input paths are null when copying is disabled",
    }
    # Export a portable copy; keep original paths in memory for source checks.
    manifest["config"]["background_cv_path"] = ""
    if result.config.background_mode == BACKGROUND_CV:
        background_path = Path(result.config.background_cv_path).expanduser().resolve()
        manifest["input"]["background_cv"] = {
            "path": f"input/background_{background_path.name}" if include_input_copy else None,
            "name": background_path.name,
            "sha256": result.background_source.sha256 if result.background_source else None,
            "status_at_save": result.background_source.current_status() if result.background_source else "not captured",
            "potential_column": "Potential/V",
            "current_column": "Current/A",
        }
        manifest["config"]["background_cv_path"] = manifest["input"]["background_cv"]["path"]
    if not result.config.uncertainty_configured:
        for key in manifest["config"]:
            if key.startswith("sigma_") or key == "lgk_error_limit":
                manifest["config"][key] = None
    _write_json_atomic(run_directory / "manifest.json", manifest)
    return manifest


def finish_manifest(run_directory: Path, manifest: dict, status: str, error: str = "") -> None:
    manifest["status"] = status
    manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    if error:
        manifest["error"] = error
    _write_json_atomic(run_directory / "manifest.json", manifest)


def write_legacy_tables(result: AnalysisResult, run_directory: Path, data_name: str) -> None:
    """Write the established CSV layout inside one collision-safe run directory."""

    paths = {name: Path(value) for name, value in output_paths(run_directory).items()}
    for name, path in paths.items():
        if name != "figures_folder":
            path.mkdir(parents=True, exist_ok=False)

    pd.DataFrame(
        {"Potential/V": result.potential, "Current/A": result.processed_current}
    ).to_csv(paths["processed_CVs_folder"] / f"{data_name}.csv", index=False)

    pd.DataFrame(
        {
            "Potential(V)": result.potential,
            "Current(A)": result.processed_current,
            "Original_Conc_O(mol/cm^3)": result.original_conc_o,
            "Original_Conc_R(mol/cm^3)": result.original_conc_r,
        }
    ).to_csv(paths["original_conc_folder"] / f"{data_name}.csv", index=False)

    pd.DataFrame(
        {
            "Potential(V)": result.forward_potential,
            "Current(A)": result.forward_current,
            "Processed_Conc_O(mol/cm^3)": result.forward_conc_o,
            "Processed_Conc_R(mol/cm^3)": result.forward_conc_r,
        }
    ).to_csv(paths["processed_conc_folder"] / f"{data_name}_forward.csv", index=False)
    pd.DataFrame(
        {
            "Potential(V)": result.backward_potential,
            "Current(A)": result.backward_current,
            "Processed_Conc_O(mol/cm^3)": result.backward_conc_o,
            "Processed_Conc_R(mol/cm^3)": result.backward_conc_r,
        }
    ).to_csv(paths["processed_conc_folder"] / f"{data_name}_backward.csv", index=False)

    pd.DataFrame({"E0(V)": [result.e0], "errorE0(V)": [result.error_e0]}).to_csv(
        paths["original_lgk_folder"] / f"{data_name}_E0.csv", index=False
    )
    pd.DataFrame(
        {
            "Potential(V)": result.forward_potential,
            "Current(A)": result.forward_current,
            "Original_lgkR(cm/s)": result.forward_lgk_r,
            "Original_lgkO(cm/s)": result.forward_lgk_o,
        }
    ).to_csv(paths["original_lgk_folder"] / f"{data_name}_forward.csv", index=False)
    pd.DataFrame(
        {
            "Potential(V)": result.backward_potential,
            "Current(A)": result.backward_current,
            "Original_lgkR(cm/s)": result.backward_lgk_r_original,
            "Original_lgkO(cm/s)": result.backward_lgk_o_original,
        }
    ).to_csv(paths["original_lgk_folder"] / f"{data_name}_backward.csv", index=False)

    pd.DataFrame(
        {
            "Potential(V)": result.potential,
            "Current(A)": result.processed_current,
            "Original_Conc_O(mol/cm^3)": result.original_conc_o,
            "Original_Conc_R(mol/cm^3)": result.original_conc_r,
            "Sigma_Conc_O(mol/cm^3)": result.original_sigma_o,
            "Sigma_Conc_R(mol/cm^3)": result.original_sigma_r,
            **error_columns(result, "original"),
        }
    ).to_csv(
        paths["error_and_final_results_folder"]
        / f"{data_name}_original_conc_with_error.csv",
        index=False,
    )
    pd.DataFrame(
        {
            "Potential(V)": result.processed_cycle_potential,
            "Current(A)": result.processed_cycle_current,
            "Processed_Conc_O(mol/cm^3)": result.processed_cycle_conc_o,
            "Processed_Conc_R(mol/cm^3)": result.processed_cycle_conc_r,
            "Sigma_Conc_O(mol/cm^3)": result.processed_cycle_sigma_o,
            "Sigma_Conc_R(mol/cm^3)": result.processed_cycle_sigma_r,
            **error_columns(result, "cycle"),
        }
    ).to_csv(
        paths["error_and_final_results_folder"]
        / f"{data_name}_processed_conc_with_error.csv",
        index=False,
    )
    pd.DataFrame(
        {
            "Potential(V)": result.forward_potential,
            "lgkR(cm/s)": result.forward_lgk_r,
            "lgkR_min": result.forward_lgk_r_min,
            "lgkR_max": result.forward_lgk_r_max,
            "lgkO(cm/s)": result.forward_lgk_o,
            "lgkO_min": result.forward_lgk_o_min,
            "lgkO_max": result.forward_lgk_o_max,
        }
    ).to_csv(
        paths["error_and_final_results_folder"]
        / f"{data_name}_forward_lgk_with_error.csv",
        index=False,
    )
    pd.DataFrame(
        {
            "Potential(V)": result.backward_potential,
            "lgkR(cm/s)": result.backward_lgk_r,
            "lgkR_min": result.backward_lgk_r_min,
            "lgkR_max": result.backward_lgk_r_max,
            "lgkO(cm/s)": result.backward_lgk_o,
            "lgkO_min": result.backward_lgk_o_min,
            "lgkO_max": result.backward_lgk_o_max,
        }
    ).to_csv(
        paths["error_and_final_results_folder"] / f"{data_name}_lgk_with_error.csv",
        index=False,
    )

    try:
        k_s = calculate_k_s(result)
    except (ValueError, OverflowError):
        k_s = None
    k_s_error = calculate_k_s_error(result)
    width_at_k_s = max(float(result.backward_lgk_r_max[k_s.index] - result.backward_lgk_r_min[k_s.index]),
                      float(result.backward_lgk_o_max[k_s.index] - result.backward_lgk_o_min[k_s.index])) if k_s else None
    _write_json_atomic(
        run_directory / "summary.json",
        {
            "e0_v": result.e0,
            "errorE0_v": result.error_e0,
            "error_analysis": error_metadata(result),
            "concentration_normalization": normalization_metadata(result),
            "k_s_cm_per_s": k_s.k_s if k_s else None,
            "k_s_uncertainty": asdict(k_s_error),
            "k_s_error_cm_per_s": k_s_error.symmetric_error_cm_per_s,
            "k_s_lower_bound_cm_per_s": k_s_error.lower_cm_per_s,
            "k_s_upper_bound_cm_per_s": k_s_error.upper_cm_per_s,
            "k_s_error_status": k_s_error.status,
            "lgk_s": k_s.lgk_s if k_s else None,
            "k_s_method": k_s.method if k_s else "Unavailable at nearest E0 sample",
            "k_s_nearest_potential_v": k_s.nearest_potential if k_s else None,
            "k_s_lgk_r": k_s.lgk_r if k_s else None,
            "k_s_lgk_o": k_s.lgk_o if k_s else None,
            "k_s_error_width": width_at_k_s,
            "k_s_error_width_units": "log10; maximum of the O/R branch widths, not the symmetric k_s error",
            "k_s_point_within_error_limit": bool(k_s.index in result.chosen_backward_indices) if k_s and result.config.uncertainty_configured else None,
            "input_points": len(result.potential),
            "forward_scan_points": len(result.forward_potential),
            "backward_scan_points": len(result.backward_potential),
            "lgk_error_limit": result.config.lgk_error_limit if result.config.uncertainty_configured else None,
            "uncertainty_configured": result.config.uncertainty_configured,
            "background_correction_mode": result.config.background_mode,
            "accepted_forward_points": len(result.chosen_forward_indices),
            "accepted_backward_points": len(result.chosen_backward_indices),
            "forward_error_window": _error_window_payload(
                result.forward_potential, result.chosen_forward_indices
            ),
            "backward_error_window": _error_window_payload(
                result.backward_potential, result.chosen_backward_indices
            ),
            "note": "k_s preserves the current nearest-E0 geometric-mean method.",
            "warnings": list(result.warnings),
        },
    )


def export_analysis_result(
    result: AnalysisResult,
    output_root: str,
    *,
    data_name: str = "",
    include_input_copy: bool = True,
    include_error_figures: bool = True,
    kinetics_scan: str = "backward",
    error_kinetics_scan: str = "backward",
    result_outdated: bool = False,
    simulation=None,
    simulation_smoothing=None,
    simulation_outdated: bool = False,
    progress_callback=None,
    cancel_event=None,
) -> Path:
    """Save an existing in-memory result without rerunning numerical analysis."""

    include_error_figures = include_error_figures and result.config.uncertainty_configured
    simulation_view = None
    if simulation is not None:
        from .back_simulation import analysis_signature, comparison_view
        if simulation.analysis_id != analysis_signature(result):
            raise ValueError("Back simulation belongs to a different main result. Run it again before exporting.")
        simulation_view = comparison_view(simulation, simulation_smoothing)
    if kinetics_scan not in {"forward", "backward", "both"} or error_kinetics_scan not in {"forward", "backward", "both"}:
        raise ValueError("Unrecognized scan selection.")
    if include_input_copy and (result.source is None or (
        result.config.background_mode == BACKGROUND_CV and result.background_source is None
    )):
        raise ValueError("Original input bytes were not captured. Recalculate before saving an input copy.")
    def check_cancelled():
        if cancel_event is not None and cancel_event.is_set():
            raise ExportCancelled("Export cancelled before the next output step.")
    check_cancelled()
    effective_name = _safe_name(data_name or result.input_path.stem)
    run_directory = create_run_directory(output_root, result.input_path)
    manifest = initial_manifest(result, run_directory, include_input_copy=include_input_copy)
    manifest["presentation"] = {
        "main_scan": kinetics_scan, "error_scan": error_kinetics_scan,
        "error_analysis_requested": include_error_figures,
        "settings_edited_since_calculation": bool(result_outdated),
    }
    try:
        check_cancelled()
        if progress_callback:
            progress_callback("Saving data tables")
        write_legacy_tables(result, run_directory, effective_name)
        save_result_figures(
            result,
            Path(output_paths(run_directory)["figures_folder"]),
            effective_name,
            include_error=include_error_figures,
            kinetics_scan=kinetics_scan,
            error_kinetics_scan=error_kinetics_scan,
            progress_callback=progress_callback,
            check_cancelled=check_cancelled,
        )
        if include_input_copy:
            input_directory = run_directory / "input"
            input_directory.mkdir()
            (input_directory / result.input_path.name).write_bytes(result.source.content)
            if result.config.background_mode == BACKGROUND_CV:
                background_path = Path(result.config.background_cv_path).expanduser().resolve()
                (input_directory / f"background_{background_path.name}").write_bytes(result.background_source.content)
        check_cancelled()
        if progress_callback:
            progress_callback("Preparing the overview report")
        simulation_html = ""
        if simulation is not None:
            from .simulation_reporting import save_back_simulation
            check_cancelled()
            if progress_callback:
                progress_callback("Saving back-simulation comparison")
            payload, simulation_html = save_back_simulation(simulation, run_directory, simulation_view,
                simulation_outdated or result_outdated, check_cancelled)
            manifest["back_simulation"] = payload
            summary_path = run_directory / "summary.json"
            summary = json.loads(summary_path.read_text())
            summary["back_simulation"] = payload
            _write_json_atomic(summary_path, summary)
        write_readable_report(result, run_directory, effective_name, manifest, include_error_figures,
                              simulation_html=simulation_html)
        check_cancelled()
    except ExportCancelled as exc:
        finish_manifest(run_directory, manifest, "cancelled", str(exc))
        raise ExportCancelled(f"Export cancelled. Partial files: {run_directory}") from exc
    except Exception as exc:
        finish_manifest(run_directory, manifest, "failed", str(exc))
        raise
    finish_manifest(run_directory, manifest, "completed")
    return run_directory
