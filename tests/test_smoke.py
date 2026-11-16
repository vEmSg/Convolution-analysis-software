"""Essential checks using the same five cases offered as user demos."""
import json
import multiprocessing as mp
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
from matplotlib.figure import Figure

from convolution_cv import __version__, analyze_cv, calculate_k_s, inspect_cv, preview_preprocessing
from convolution_cv.back_simulation import run_back_simulation, comparison_view
from convolution_cv.CV_simulator import SolverOptions
from convolution_cv.plotting import draw_processed_cv, selected_cycle_bounds
from convolution_cv.reporting import export_analysis_result
from convolution_cv.ui.app import _analysis_worker, _result_worker
from convolution_cv.ui.parameter_schema import empty_parameter_values, default_error_values
from tests.support import PROJECT_ROOT, EXAMPLES, CASES, demo_config


class SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {
            name: analyze_cv(str(EXAMPLES / name / f'{stem}.csv'), demo_config(EXAMPLES / name, stem))
            for name, stem in CASES.items()
        }

    def test_five_portable_demos_and_selected_cycle_plots(self):
        self.assertEqual({p.name for p in EXAMPLES.iterdir()
                          if p.is_dir() and p.name != '.ipynb_checkpoints'}, set(CASES))
        with tempfile.TemporaryDirectory() as directory:
            for name, stem in CASES.items():
                with self.subTest(case=name):
                    folder = Path(directory) / name
                    shutil.copytree(EXAMPLES / name, folder)
                    self.assertEqual({p.name for p in folder.iterdir()},
                                     {f'{stem}.csv', f'BG_{stem}.csv', f'{stem}.json'})
                    config = demo_config(folder, stem)
                    self.assertEqual(Path(config.background_cv_path), (folder / f'BG_{stem}.csv').resolve())
                    preview = preview_preprocessing(str(folder / f'{stem}.csv'), config)
                    raw = inspect_cv(str(folder / f'{stem}.csv'))
                    blank = inspect_cv(config.background_cv_path)
                    np.testing.assert_array_equal(preview.corrected_current, raw.current - blank.current)
                    result = analyze_cv(str(folder / f'{stem}.csv'), config)
                    np.testing.assert_array_equal(result.processed_current, self.results[name].processed_current)
                    self.assertEqual(result.e0, self.results[name].e0)
                    self.assertTrue(np.isfinite(result.e0))
                    self.assertGreater(calculate_k_s(result).k_s, 0)
                    axis = Figure().add_subplot()
                    draw_processed_cv(axis, result)
                    start, end = selected_cycle_bounds(result)
                    np.testing.assert_array_equal(axis.lines[0].get_xdata(), result.potential[start:end])

    def test_demos_export_complete_portable_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, result in self.results.items():
                with self.subTest(case=name):
                    folder = export_analysis_result(result, directory, data_name=name)
                    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
                    summary = json.loads((folder / 'summary.json').read_text(encoding='utf-8'))
                    self.assertEqual(manifest['status'], 'completed')
                    self.assertNotIn(str(PROJECT_ROOT), json.dumps(manifest))
                    self.assertEqual((folder / manifest['input']['path']).read_bytes(), result.source.content)
                    self.assertEqual((folder / manifest['input']['background_cv']['path']).read_bytes(), result.background_source.content)
                    self.assertEqual(summary['k_s_cm_per_s'], calculate_k_s(result).k_s)
                    for payload in (manifest, summary):
                        self.assertEqual(payload['error_analysis']['multiD_coefficient'], 0.4520)
                        self.assertEqual(payload['error_analysis']['multiD_time_factor'], 6)
                        self.assertEqual(payload['error_analysis']['multiD_equation_reference'], 'SI Eq. S23')
                    self.assertIn('Standard rate constant kₛ', (folder / 'Overview.html').read_text(encoding='utf-8'))
                    self.assertTrue((folder / 'data/processed_trace.csv').is_file())
                    for extension in ('png', 'svg', 'pdf'):
                        self.assertEqual(len(list((folder / '6_plots').glob(f'*.{extension}'))), 8)

    def test_smoothing_and_simulation_models(self):
        result = self.results['tris_bipyridine_ruthenium']
        raw = preview_preprocessing(str(result.input_path), replace(result.config, smoothing_enabled=False))
        np.testing.assert_array_equal(raw.smoothed_current, raw.corrected_current)
        for model in ('BV', 'MHL'):
            with self.subTest(model=model):
                simulation = run_back_simulation(result, kinetic_model=model, lambda_eV=.7,
                                                 solver=SolverOptions(cells=60, substeps=2))
                self.assertEqual(simulation.simulation.metadata['model'], model)
                self.assertTrue(np.isfinite(simulation.simulation.current_a).all())
                self.assertEqual(len(simulation.simulation.current_a), selected_cycle_bounds(result)[1])
                view = comparison_view(simulation)
                self.assertTrue(np.isfinite(view['raw_metrics']['selected_cycle']['rmse_a']))

    def test_startup_defaults_and_entry_point(self):
        main, error = empty_parameter_values()
        self.assertEqual(main['scan_rate'], '')
        self.assertTrue(all(value == '' for value in error.values()))
        self.assertEqual(float(main['smoothing_window_mv']), 20)
        self.assertEqual(int(main['smoothing_order']), 2)
        self.assertEqual(default_error_values()['sigma_current'], '1e-6')
        output = subprocess.check_output([sys.executable, '-m', 'convolution_cv', '--version'],
                                         cwd=PROJECT_ROOT, text=True)
        self.assertEqual(output.strip(), f'Convolution Analysis {__version__}')

    def test_analysis_worker_and_export_cancellation(self):
        result = self.results['tris_bipyridine_ruthenium']
        context = mp.get_context('spawn')
        with tempfile.TemporaryDirectory() as directory:
            cancelled = context.Event()
            cancelled.set()
            jobs = [(_analysis_worker, (str(result.input_path), result.config, 'Potential/V', 'Current/A'), 'result'),
                    (_result_worker, ('export', result, {'output_root': directory}), 'cancelled')]
            for target, arguments, expected in jobs:
                messages = context.Queue()
                args = (*arguments, messages, cancelled) if target is _result_worker else (*arguments, messages)
                worker = context.Process(target=target, args=args)
                try:
                    worker.start()
                    while True:
                        message = messages.get(timeout=60)
                        if message[0] != 'progress': break
                    worker.join(timeout=5)
                    self.assertEqual(message[0], expected, message)
                    self.assertEqual(worker.exitcode, 0)
                    if expected == 'result': self.assertEqual(message[1].e0, result.e0)
                finally:
                    if worker.is_alive(): worker.terminate(); worker.join(timeout=5)
                    worker.close()
                    messages.close()
                    messages.join_thread()
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
