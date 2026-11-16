# Calculation method

Convolution analysis reconstructs electrode-surface concentrations from the current
history and combines them with the measured current to extract electron-transfer
rate constants. The software calculates the formal potential E₀ from the
backward-scan zero-current region, then obtains kₛ and the potential dependence of
the oxidation and reduction rate constants.

The treatment considers a dissolved redox couple under semi-infinite planar
diffusion, with negligible migration, convection, adsorption and coupled chemical
reaction during the analyzed interval. Oxidation current is positive. Kinetic
extraction uses the thermodynamic ratio of the directional rate constants and
requires no prescribed B-V or MHL rate law.

The equations below describe the numerical implementation of the method presented
in SI Notes S1 and S3. The main calculation is implemented in
[`engine.py`](../convolution_cv/engine.py), concentration referencing in
[`normalization.py`](../convolution_cv/normalization.py), and error propagation in
[`uncertainty.py`](../convolution_cv/uncertainty.py). For operation of the interface,
see the [user guide](USER_GUIDE.md).

## 1. Quantities and units

| Symbol | Quantity | Unit |
|---|---|---|
| E | Electrode potential | V |
| I | Current, positive for oxidation | A |
| v | Scan-rate magnitude | V/s |
| d | Circular electrode diameter | cm |
| A | Electrode area, πd²/4 | cm² |
| n | Electrons transferred per redox event | Positive integer |
| D_O, D_R | Diffusion coefficients | cm²/s |
| C_O, C_R | Surface concentrations | mol/cm³ |
| T | Temperature | K |
| C_dl | Total electrode capacitance | F |
| F | Faraday constant, 96485 | C/mol |
| R | Gas constant, 8.3145 | J/(mol K) |

Enter physical inputs in these units. The plots display current in µA and
concentration in µmol/cm³. Logarithmic rate constants are
log₁₀[k / (cm/s)]; ln denotes the natural logarithm.

## 2. Input and preprocessing

### Import and timing

The sample CSV supplies potential and current in acquisition order. Preferred
column names are `Potential/V` and `Current/A`; alternative sample columns can be
mapped during import. Numeric conversion removes rows with missing or nonnumeric
values, and subsequent indices refer to the cleaned arrays. Analysis requires at
least three finite paired samples and a complete selected cycle.

The time step is determined from the first potential increment:

```math
\Delta E_{sample}=|E_1-E_0|,\qquad
\Delta t=\frac{\Delta E_{sample}}{v}.
```

Here E₀ with a sample subscript denotes the first recorded potential; E⁰ denotes
the formal potential. The calculation uses uniform time intervals and a nonzero
first potential increment. Import reports nonuniform potential spacing and retains
the first increment for the calculation.

Positive potential increments define anodic segments and negative increments
define cathodic segments. Zero increments are skipped when detecting direction.
A change in direction starts a new segment at the first sample after the turning
point. Segments use half-open index intervals [start, end); the turning sample
belongs to the outgoing segment.

Two successive segments form a complete cycle. The one-based cycle selection c
uses segments 2(c − 1) and 2(c − 1) + 1. These are called forward and backward,
respectively, whether the first sweep is anodic or cathodic.

### Background subtraction

For constant-capacitance correction, let sᵢ = +1 on anodic segments and −1 on
cathodic segments. The corrected current is

```math
I_{corr,i}=I_{raw,i}-s_iC_{dl}v.
```

C_dl is the total electrode capacitance in F. For a measured blank, the software
instead subtracts the corresponding current at each sample:

```math
I_{corr,i}=I_{raw,i}-I_{blank,i}.
```

The blank CSV uses `Potential/V` and `Current/A` columns. After numeric cleanup,
its length and potential sequence must exactly match those of the sample. A
mismatch is reported with the differing sample values.

### Smoothing

Optional Savitzky–Golay smoothing is applied to the complete corrected trace.
The defaults are a 20 mV full potential window and polynomial order 2. The window
is converted to the nearest odd sample count using the median nonzero absolute
potential increment; ties round upward. A 20 mV window at 1 mV spacing gives
21 samples. SciPy's filter uses endpoint mode `interp` and derivative order zero.

The polynomial order must be smaller than the sample window, which must contain
at least three samples and fit within the trace. With smoothing disabled, the
corrected current passes directly to convolution. The resulting current is denoted
I_proc throughout the following calculation.

## 3. Surface-concentration reconstruction

### Discrete convolution

Integration of the square-root kernel over each lag interval gives

```math
w_m=2\sqrt{\Delta t}\left(\sqrt{m+1}-\sqrt m\right),\qquad m=0,\ldots,N-1.
```

The unshifted contributions to the surface concentrations are

```math
u_{O,i}=G_O\sum_{j=0}^{i}w_{i-j}I_{proc,j},\qquad
u_{R,i}=-G_R\sum_{j=0}^{i}w_{i-j}I_{proc,j},
```

```math
G_x=\frac{1}{nFA\sqrt{\pi D_x}}.
```

The software evaluates the linear convolution with SciPy's `fftconvolve` in full
mode and retains the first N samples. Each concentration includes the preceding
current history. The first current sample is paired with the first integrated
kernel interval, as described in SI Note S1.

### Full-trace concentration references

Convolution determines concentration changes. Absolute concentration references
are established by assuming depletion of O at the negative potential endpoint
and R at the positive endpoint:

```math
C_{O,i}^{full}=u_{O,i}-u_{O,r_-},\qquad
C_{R,i}^{full}=u_{R,i}-u_{R,r_+}.
```

The pair of reference samples depends on the selected cycle:

| Selected cycle | Reference pair |
|---|---|
| First cycle | Initial sample and the cycle's turning sample |
| Second or later cycle | Final sample of the selected cycle and its turning sample |

The lower-potential sample of the pair references O; the higher-potential sample
references R. The turning sample is the final sample of the selected forward
segment, and the cycle's final sample is the final sample of its backward segment.
These offsets apply to the complete concentration traces.

### Selected-scan concentration references

The selected forward and backward scans are each referenced again using their own
endpoints. For either scan q,

```math
C_{O,q,i}=C_{O,i}^{full}-C_{O,r_{q,-}}^{full},\qquad
C_{R,q,i}=C_{R,i}^{full}-C_{R,r_{q,+}}^{full}.
```

These scan-specific concentrations are used to calculate E₀ and the kinetic
curves. CV and concentration plots display the selected cycle, with concentrations
from the full-trace reference. All six reference indices, potentials and times are
saved and reused during error propagation. Negative concentrations are retained.

## 4. Formal potential

At a Faradaic zero-current crossing, the oxidation and reduction fluxes balance.
The surface-concentration ratio then gives the formal potential through the Nernst
relation.

The software first locates the backward-scan sample j with the smallest |I| and
fits I = mE + b over that sample and up to five neighboring samples on either side.
The fitting window is clipped at the scan boundaries and requires at least two
points. The fitted zero-current potential is

```math
E_{I=0,fit}=-\frac{b}{m}.
```

The backward-scan sample z nearest this fitted potential supplies the measured
potential and scan-specific concentrations:

```math
|E_{b,z}-E_{I=0,fit}|=\min_i|E_{b,i}-E_{I=0,fit}|,
```

```math
E^0=E_{b,z}-\frac{RT}{nF}\ln\left(\frac{C_{O,b,z}}{C_{R,b,z}}\right).
```

The calculation requires a finite positive concentration ratio and a nonzero
fitted slope. Thus, the fitted crossing locates the sample, and the concentration
ratio at that sample determines E₀.

## 5. Rate constants

### Potential-dependent kinetics

For each sample in the selected forward or backward scan, define

```math
q_i=\exp\left[\frac{nF(E_i-E^0)}{RT}\right].
```

Combining the current balance with kO/kR = q gives

```math
k_{R,i}=\frac{I_i}{nFA(q_iC_{R,i}-C_{O,i})},\qquad
k_{O,i}=q_i k_{R,i}.
```

The software stores the base-10 logarithms of these rates. Each scan uses its own
referenced concentrations. Undefined logarithmic values appear as gaps in plots
and as non-finite or empty entries in the corresponding exported tables.

### Standard rate constant

At E = E⁰, both directional rates equal kₛ. For sampled data, the software uses
the backward-scan point h nearest E₀:

```math
|E_{b,h}-E^0|=\min_i|E_{b,i}-E^0|,\qquad
\log_{10}k_s=\frac{\log_{10}k_{R,h}+\log_{10}k_{O,h}}{2}.
```

This is the geometric mean of the two rates at that sample. If only one logarithmic
branch is finite, its value is used; if neither is finite, kₛ is unavailable.
Error-limit selection reports the acceptance of the sample while retaining the
same central E₀ and kₛ.

## 6. Concentration-error calculation

Error analysis combines current noise and uncertainties in capacitance, diameter
and diffusion coefficients with an empirical nonplanar-diffusion contribution.
The resulting concentration errors are propagated into E₀ and kinetic sensitivity
bounds, following SI Note S3.

### Measurement inputs

| Input | Unit |
|---|---|
| Current standard uncertainty, σ_I | A |
| Total-capacitance standard uncertainty, σ_Cdl | F |
| Diameter relative uncertainty, p_d | % |
| Diffusion relative uncertainties, p_DO and p_DR | % |
| Maximum accepted log₁₀ interval width, L | Log₁₀ units |

Percentage inputs are converted to absolute uncertainties:

```math
\sigma_d=\frac{p_d}{100}d,\qquad
\sigma_{D_x}=\frac{p_{D_x}}{100}D_x.
```

Current uncertainty describes independent input samples after background
subtraction and before smoothing. Include measured-blank noise in σ_I when using
blank subtraction. The capacitance term applies to capacitance correction mode.
The propagation uses the unsmoothed discrete weights; SG noise reduction and
correlations are omitted.

### Reference subtraction and measurement contributions

For species x with reference sample r, the difference between the observation
and reference kernel rows is

```math
h_{i,j}=w_{i-j}\mathbf1_{j\le i}-w_{r-j}\mathbf1_{j\le r}.
```

This retains the covariance shared by the concentration and its reference.
Full-trace errors use the full-trace reference; each selected scan uses its own
reference. With sⱼ denoting the scan-direction sign, the variance contributions are

```math
V_{I,i}=G_x^2\sigma_I^2\sum_j h_{i,j}^2,
```

```math
V_{Cdl,i}=G_x^2(v\sigma_{Cdl})^2\left(\sum_jh_{i,j}s_j\right)^2,
```

```math
V_{param,i}=C_{x,i}^2\left[4\left(\frac{\sigma_d}{d}\right)^2+
\frac14\left(\frac{\sigma_{D_x}}{D_x}\right)^2\right].
```

The calculation treats these input-error sources as mutually uncorrelated.
FFT products evaluate the referenced kernel contributions across the complete
current history, including scan reversals. The combined measurement contribution
vanishes at its concentration reference.

### Nonplanar-diffusion contribution

SI Eq. S23 estimates the instantaneous concentration error from nonplanar diffusion:

```math
e_{multiD,i}=0.4520\widehat C_{bulk}
\left(\frac{\sqrt{6D_{eff}t_i}}{d}\right)^{1.049},
```

```math
\widehat C_{bulk}=\max[C_{O,full}(0),C_{R,full}(0)],\qquad
D_{eff}=\sqrt{D_OD_R},\qquad t_i=i\Delta t.
```

The bulk estimate assumes one initial redox form. The empirical relation was
derived from whole-cycle concentration errors with equal diffusivities; the
software uses their geometric mean for unequal DO and DR. The same multiD
contribution is applied to both species, using elapsed time from the start of
the imported trace.

The total error is

```math
e_{C_x,i}=\sqrt{V_{I,i}+V_{Cdl,i}+V_{param,i}+e_{multiD,i}^2}.
```

The multiD term contributes to the error estimate while the central concentrations
remain those obtained by planar convolution.

## 7. Formal-potential and kinetic errors

### E₀ error

At the same backward-scan sample z used for E₀, positive O and R concentrations give

```math
e_{E^0}=\frac{RT}{nF}\sqrt{
\left(\frac{e_{C_O,z}}{C_{O,z}}\right)^2+
\left(\frac{e_{C_R,z}}{C_{R,z}}\right)^2}.
```

This first-order estimate treats potential, temperature and sample location as
fixed and neglects the O/R error covariance. E₀ is displayed in V and its error
in mV, rounded to 0.1 mV. E₀ retains four decimal places for errors up to 0.5 mV;
for larger errors, its precision follows the error magnitude.

### Rate-constant error bounds

At each potential, the oxidation and reduction rate constants are recalculated
using combinations of the upper and lower estimated surface concentrations and
formal potential. The minimum and maximum valid rates define the bounds for each
branch, which are also used to estimate the error in kₛ. These bounds reflect the
estimated errors in concentration and E₀ rather than statistical confidence
intervals.

### Symmetric kₛ error

At the fixed sample h used for kₛ, combine the four directional bounds:

```math
k_{s,min}=10^{(\ell_{O,min,h}+\ell_{R,min,h})/2},\qquad
k_{s,max}=10^{(\ell_{O,max,h}+\ell_{R,max,h})/2},
```

```math
\Delta k_s=\max(k_s-k_{s,min},\;k_{s,max}-k_s),
```

where ℓ denotes log₁₀ k. Separate branch extrema form a conservative enclosing
range. The result is displayed as kₛ ± Δkₛ, with two significant digits in the
error and matching decimal precision in kₛ, retaining at least two significant
digits in kₛ. Before error analysis, kₛ is shown with three significant digits.

Both central branches and lower bounds must be finite. An unbounded upper branch
gives an unbounded kₛ error; undefined or nonrepresentable bounds give an unavailable
error. The symmetric error can exceed kₛ. Full-precision values and their status
are saved under `k_s_uncertainty`.

## 8. Point selection and figures

A sample is accepted when both kinetic branch centers and bounds are finite and
both interval widths are strictly smaller than L:

```math
\ell_{R,max}-\ell_{R,min}<L,\qquad
\ell_{O,max}-\ell_{O,min}<L.
```

Each scan is evaluated independently. A zero limit accepts no samples. Changing L
reselects the existing bounds; changing uncertainty inputs recalculates the errors
while preserving central concentrations, E₀ and kₛ.

The four main plots show the processed CV, surface concentrations of O and R, and
kinetics. Error-analysis plots add concentration bands and kinetic intervals.
Accepted samples are larger and opaque; other samples are translucent in the
same curve color. Undefined values form gaps, and unbounded upper intervals extend
to the plot ceiling. Concentration bands are drawn separately for each sweep.

Each scan's reported potential window extends from its lowest to highest accepted
potential. Individual rejected samples can lie within that interval. The default
kinetic view is backward; forward and combined views are also available.

## 9. Saved data

Exports preserve the completed calculation at full precision. The HTML overview
presents the results, figures and settings, while CSV and JSON files support
further analysis.

| Location | Contents |
|---|---|
| `data/` | Tables with descriptive column names, including selection and uncertainty status |
| `1_processed_CVs/` | Complete processed potential/current trace |
| `2_original_conc/` | Complete trace with full-trace-referenced concentrations |
| `3_processed_conc/` | Selected forward and backward scans with scan-specific concentrations |
| `4_original_lgk/` | E₀ and the direct forward/backward logarithmic rates |
| `5_error_and_final_results/` | Concentration-error components, rate bounds and selected results |
| `6_plots/` | Individual PNG, SVG and PDF figures |
| `summary.json` | E₀, kₛ, errors, accepted counts and potential windows |
| `manifest.json` | Configuration, input fingerprints, model metadata and save status |

`Original_Conc_O/R` denotes full-trace-referenced concentrations;
`Processed_Conc_O/R` denotes scan-specific concentrations. The `Sigma_Conc`
columns contain total estimated errors. Explicit `Error_*` columns identify the
individual contributions. `k_s_error_width` reports the maximum directional
log₁₀ interval width at h; Δkₛ is stored separately in cm/s.

Uncalculated errors are left blank. Unbounded upper rates use +inf in the numbered
CSV tables and a status label in the descriptive tables. Non-finite JSON values
are null, accompanied by their status. Metadata records the concentration
references and the SI Eq. S23 parameters under error-model version
`endpoint-discrete-multid-geomean-e0-v4`.

For the full output layout and simulation files, see the [user guide](USER_GUIDE.md)
and [back-simulation guide](BACK_SIMULATION.md). Each saved run also includes a
`FILE_GUIDE.md` describing its tables.
