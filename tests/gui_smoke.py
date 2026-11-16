"""Optional desktop check: python -m tests.gui_smoke --output gui-check.json."""
import argparse
import json
from pathlib import Path
import tkinter as tk

import numpy as np
from convolution_cv import analyze_cv, inspect_cv, preview_preprocessing
from convolution_cv.ui.app import ConvolutionAnalysisApp
from convolution_cv.ui.state import Stage
from convolution_cv.ui.parameter_schema import load_preset, build_analysis_config, default_error_values
from tests.support import EXAMPLES, CASES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = tk.Tk()
    report = {'passed': False, 'cases': []}
    try:
        app = ConvolutionAnalysisApp(root)
        configure = app.stages[Stage.CONFIGURE]
        results = app.stages[Stage.RESULTS]
        review = app.stages[Stage.REVIEW]
        assert configure.raw_values()['scan_rate'] == ''
        assert results.error_form.raw_values() == default_error_values()
        for name, stem in CASES.items():
            path = EXAMPLES / name / f'{stem}.csv'
            main_values, error = load_preset(path.with_suffix('.json'))
            app.state.set_import(inspect_cv(str(path)))
            app.stages[Stage.IMPORT].show_inspection(app.state.inspection)
            app._loading_values = True
            configure.set_values(main_values)
            results.set_error_values(error)
            app._loading_values = False
            app.state.set_main_values(main_values)
            values = configure.validate()
            assert values is not None, name
            config = build_analysis_config(values, error)
            preview = preview_preprocessing(str(path), config)
            app.state.set_preview(preview)
            review.show_preview(preview, config.cv_cycles_n)
            result = analyze_cv(str(path), config)
            app.state.set_main_result(result)
            results.show_result(result)
            app.state.set_error_result(result)
            results.show_error_result(result)
            app.show_stage(Stage.RESULTS)
            root.update()
            report['cases'].append(name)
        app.show_stage(Stage.REVIEW)
        review.smoothing_vars['smoothing_enabled'].set('False')
        root.after(650, root.quit)
        root.mainloop()
        np.testing.assert_array_equal(app.state.preview.smoothed_current, app.state.preview.corrected_current)
        panel = results.simulation_tab
        assert panel.kinetics_values() == {'kinetic_model': 'BV', 'alpha': .5}
        panel.kinetic_model.set('MHL')
        panel.lambda_eV.set('.7')
        assert panel.kinetics_values() == {'kinetic_model': 'MHL', 'lambda_eV': .7}
        assert str(panel.alpha_entry['state']) == 'disabled'
        app.show_stage(Stage.RESULTS)
        results.notebook.select(0)
        for size in ('1040x680', '1260x820'):
            root.geometry(size)
            root.update()
            assert results.main_figures.winfo_ismapped()
            assert results.main_figures.winfo_width() > 0
        report['passed'] = True
    except Exception as exc:
        report['error'] = repr(exc)
        raise
    finally:
        Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
        root.destroy()


if __name__ == '__main__':
    main()
