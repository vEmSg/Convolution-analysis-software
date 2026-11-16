# User guide

The application guides the analysis from an imported CV through background
correction and concentration reconstruction to E₀, kₛ and potential-dependent
rate constants. Error analysis and back simulation help assess the extracted
kinetics. Each completed analysis can be saved as a report with its data and settings.

## Prepare the experiment and data

Record complete CV cycles from the start of the first sweep, retaining the current
history preceding the cycle selected for analysis. Import the samples in acquisition
order, with **positive current for oxidation** and negative current for reduction.
Acquire uniformly spaced potential samples at a constant scan-rate magnitude.
The calculation obtains the time interval from the first potential increment and
scan rate; nonuniform spacing is reported during import.

For informative kinetic extraction, the manuscript suggests choosing a scan rate
that gives an anodic–cathodic peak separation of **at least 120 mV**. This helps
resolve kinetic effects when nearly Nernstian CVs provide little sensitivity to kₛ.
The recommendation guides experimental design; point selection in Error Analysis
uses the calculated rate-constant interval widths.

Choose potential limits that approach depletion of **O at the negative endpoint**
and **R at the positive endpoint**. These endpoints provide the zero-concentration
references. Incomplete depletion shifts the reconstructed concentrations and can
affect E₀ and kₛ. The [calculation method](DATA_ANALYSIS_METHOD.md) describes the
reference points used for each cycle and scan.

## Import and configure

Import a CSV with potential in V and current in A. Preferred headers are
`Potential/V` and `Current/A`; alternative sample-CV headers can be mapped in
Import. Nonnumeric and missing rows are reported and discarded. Select the
complete CV cycle to analyze, using a one-based index.

Configure fields start blank. Enter the experimental parameters or load a saved
preset. Choose one background treatment:

- **Capacitance correction:** enter the **total electrode capacitance in F**.
  Convert an area-normalized value by multiplying by the electrode area and
  converting to farads.
- **Measured blank:** select a CSV with `Potential/V` and `Current/A` columns and
  exactly the same cleaned potential sequence and number of samples as the experiment.

Presets save main and error parameters. Relative blank-CV paths are resolved
beside the preset file, so a demo folder can be moved as a unit. Missing preset
values remain blank for the user to supply.

## Review preprocessing

The preview shows the selected cycle: raw current in brown, measured blank in
gray, background-corrected current in translucent blue, and output current in
dark blue. A measured blank is subtracted point by point before smoothing.

Choose No smoothing or Savitzky–Golay (SG). The default is SG enabled, **20 mV full
potential span**, **order 2**. A 1 mV potential increment gives a 21-point window.
Changing these settings updates the preview. Review reports the effective window
and any settings that need adjustment.

## Results and error analysis

Results display E₀ and kₛ alongside one full-size plot at a time: voltammogram,
surface concentration O, surface concentration R, or kinetics. CV and concentration
plots show the selected cycle; full-trace exports include every imported cycle.
Kinetic plots can show the forward scan, backward scan, or both. E₀ and kₛ are
calculated from the backward scan.

Error Analysis starts with editable inputs:

| Input | Default |
|---|---:|
| Current uncertainty | 1e-6 A |
| Capacitance uncertainty | 0 F |
| Diameter uncertainty | 0% |
| Diffusion uncertainty O / R | 0% / 0% |
| Maximum log₁₀ width | 0.3 |

Set these values for the measurement before running Error Analysis. **Current
uncertainty is the per-sample current-noise standard deviation after background
subtraction and before smoothing**, in A. Include the blank's noise when using
measured-blank subtraction. Capacitance uncertainty contributes in capacitance
correction mode. The propagation uses independent input-current samples before
smoothing; estimate the noise from the corresponding unsmoothed data.

Accepted samples have finite oxidation and reduction intervals whose widths are
both below the selected limit. They appear larger and opaque; other samples are
translucent in the same curve color. Undefined values appear as gaps, and unbounded
upper intervals extend to the plot ceiling. The reported errors are sensitivity
estimates rather than statistical confidence intervals.

**Inspect** selects normal pointer mode. **Pan** moves the view, **Zoom** selects
a region, and **Back** and **Reset** restore previous or initial views. **Export**
and **Enlarge** apply to the selected plot.

## Back simulation

Open **Results → Back Simulation** after completing the main analysis. The default
is **B-V** kinetics with **α = 0.5**. For **MHL**, enter the reorganization energy
**λ in eV**. Run the simulation after selecting the model and its parameter.

The simulation uses the extracted E₀ and kₛ and the configured experimental
parameters under planar diffusion. It assumes one initial species and estimates
its bulk concentration from the reconstructed initial concentrations. Earlier
cycles establish the diffusion profiles for the selected-cycle comparison.

Comparison smoothing initially follows Review. Its independent No smoothing/SG
controls apply equally to measured and simulated currents. CV and residual views
report raw and displayed comparison metrics separately. See
[Back simulation](BACK_SIMULATION.md) for the equations and solver settings.

## Save and share

**Save Latest Results** writes the latest completed calculation. After changing
main parameters, return to Review and rerun the analysis. Changes to error inputs
require error recalculation; changes to the simulation model or its parameter
require a new simulation. The interface identifies results that need updating.

Each save creates a timestamped folder containing `Overview.html`, `FILE_GUIDE.md`,
`manifest.json`, `summary.json`, tables in `data/` and the numbered data folders,
and figures in `6_plots/`. Completed simulations add `7_back_simulation/`.
Input copies are stored in `input/` when enabled.

Open `Overview.html` to review the results and `FILE_GUIDE.md` for table definitions.
Share the complete run folder to preserve its data and figure links. The manifest
records calculation settings, input fingerprints and save status, using paths
relative to the run folder.

## Troubleshooting

- **No Tkinter / no window:** run `python -m tkinter` with the application's Python
  environment. Install Tk support from the Python or OS distributor and run the
  application in a desktop session.
- **Wrong Python:** activate the environment or use its Python executable directly.
  Check the installation with `python -m convolution_cv --version`.
- **Background mismatch:** supply a blank acquired on the same potential sequence.
- **Invalid smoothing:** reduce the window or polynomial order to fit the data.
- **Results need updating:** rerun the relevant calculation after editing its inputs.
- **Cannot write output:** choose a writable destination.

The Help menu provides the log location. For the equations and numerical workflow,
see [Calculation method](DATA_ANALYSIS_METHOD.md).
