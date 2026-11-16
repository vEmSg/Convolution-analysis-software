"""Shared demo inputs; never application startup defaults."""
from pathlib import Path

from convolution_cv.ui.parameter_schema import load_preset, build_analysis_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = PROJECT_ROOT / 'examples'
CASES = {
    'ferrocene': '20V',
    'ferrocyanide': '10V',
    'dioxygen': '50V',
    'tris_bipyridine_ruthenium': '50V',
    'tert_nitrobutane': '10V',
}


def demo_config(folder, stem):
    main, error = load_preset(Path(folder) / f'{stem}.json')
    # Configure ignores capacitance in measured-blank mode, even when left blank.
    values = dict(main, double_layer_capacity='0')
    return build_analysis_config(values, error)
