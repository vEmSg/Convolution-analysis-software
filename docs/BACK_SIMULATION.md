# Back simulation

Back simulation generates a CV from the extracted E₀ and kₛ and compares it with
the background-subtracted experiment. It provides a consistency check under the
selected kinetic model and planar-diffusion conditions.

## Run a comparison

After completing the main calculation, open **Results → Back Simulation**. Choose
**B-V** and enter the transfer coefficient α, or choose **MHL** and enter the
reorganization energy λ in eV. B-V with α = 0.5 is the default. The model requires
0 < α < 1 for B-V or a positive λ for MHL.

The simulation uses the completed analysis values of E₀, kₛ, diffusion
coefficients, electrode area, temperature and electron number. It assumes one
species is initially present: R for an initial anodic sweep or O for an initial
cathodic sweep. Its bulk concentration is estimated from the reconstructed
initial concentrations:

```math
\widehat C_{bulk}=\max[C_{O,full}(0),C_{R,full}(0)].
```

The imported potential sequence drives the simulation from the first sample to
the end of the selected cycle. Concentration profiles carry through successive
sweeps, preserving the diffusion history. The comparison displays the selected
cycle.

## Kinetic models

Define the dimensionless potential as

```math
\eta=\frac{nF(E-E^0)}{RT}.
```

For Butler–Volmer kinetics, the oxidation and reduction rate constants are

```math
k_O=k_s\exp[(1-\alpha)\eta],\qquad
k_R=k_s\exp[-\alpha\eta].
```

The Marcus–Hush–Levich (MHL) option evaluates a symmetric constant-density-of-states
integral:

```math
L=\frac{\lambda F}{RT},\qquad
H(L,\eta)=\int_{-\infty}^{\infty}
\frac{\exp[-(x-L+\eta)^2/(4L)]}{1+\exp(x)}\,dx,
```

```math
k_O=k_s\frac{H(L,\eta)}{H(L,0)},\qquad
k_R=k_s\frac{H(L,-\eta)}{H(L,0)}.
```

Both rates equal kₛ at E₀ and satisfy kO/kR = exp(η). λ is expressed in eV per
modeled reaction event. The integral is evaluated by adaptive quadrature in the
log domain. Its supported numerical range is 0.01 ≤ L ≤ 1000 and |η| ≤ 600.

## Diffusion calculation

The solver in [`CV_simulator.py`](../convolution_cv/CV_simulator.py) evaluates
one-dimensional planar diffusion using a stretched finite-volume mesh and
implicit Euler time integration. The surface flux couples the two species:

```math
J=k_OC_{R,s}-k_RC_{O,s},\qquad I=nFAJ.
```

Oxidation produces O and consumes R. The far boundary remains at the initial bulk
concentrations. The calculation uses cm, s, mol/cm³ and A, with F = 96485 C/mol
and R = 8.3145 J/(mol K).

The default mesh contains 120 cells and extends to seven times
sqrt(max(DO, DR) × duration). Four internal time steps are used per input interval,
with linear interpolation of the potential between samples. Output intervals
follow the analysis time step, Δt = |E₁ − E₀|/v. Mesh size, time subdivision and
domain extent can be adjusted through `SolverOptions` in the Python API.

## Smoothing and residuals

Comparison smoothing initially follows Review: SG enabled, a 20 mV potential
window and polynomial order 2. The comparison controls apply the same filter to
both current traces before selecting the displayed cycle. The raw simulation
and main-analysis results are retained separately.

The residual is experimental current minus simulated current. The comparison
reports RMSE and maximum absolute residual for the selected cycle, together with
forward- and backward-scan metrics. Raw metrics use the unsmoothed traces;
displayed metrics use the plotted traces. All selected-cycle samples contribute.
Peak-current and peak-potential differences are reported when both curves have
an interior peak of the expected scan sign.

## Recalculate and save

Rerun the simulation after changing its model or kinetic parameter. Changes to
physical inputs, background treatment, selected cycle or preprocessing require a
new main calculation first. Error-only recalculation preserves the simulation.

**Save Latest Results** includes the comparison in the offline overview and saves
its data in `7_back_simulation/`. This folder contains the complete simulated
history, raw and displayed selected-cycle currents, residuals, settings and
metrics, and comparison figures in PNG, SVG and PDF. The saved settings identify
the calculation and smoothing used for that comparison.
