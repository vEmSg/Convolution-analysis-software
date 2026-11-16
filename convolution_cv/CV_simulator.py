"""Independent planar BV/MHL forward solver (cm, s, mol/cm³, A; lambda in eV).

Uses a stretched finite-volume mesh, implicit Euler time integration and a
kinetic surface-flux boundary condition to simulate the measured waveform.
"""
from dataclasses import dataclass, asdict
from functools import lru_cache
import hashlib
import math
from pathlib import Path

import numpy as np
from scipy.optimize import brentq, minimize_scalar
from scipy.integrate import quad
from scipy.sparse import diags, eye
from scipy.sparse.linalg import splu

# Match the existing analysis constants, not rounded display values.
F, R = 96485.0, 8.3145
VERSION = "planar-bv-mhl-fv-2"


class SimulationCancelled(Exception):
    pass


@dataclass(frozen=True)
class SolverOptions:
    cells: int = 120
    substeps: int = 4
    domain_factor: float = 7.0


@dataclass
class CVSimulation:
    time_s: np.ndarray
    potential_v: np.ndarray
    current_a: np.ndarray
    surface_o: np.ndarray
    surface_r: np.ndarray
    metadata: dict
    diagnostics: dict


def _dimensionless_potential(potential, e0, k_s, temperature, n_e):
    if not all(np.isfinite(v) for v in (e0, k_s, temperature, n_e)):
        raise ValueError("Kinetic parameters must be finite.")
    if k_s < 0 or temperature <= 0 or n_e < 1 or int(n_e) != n_e:
        raise ValueError("Require k_s ≥ 0, T > 0 and positive integer n.")
    eta = n_e * F * (np.asarray(potential) - e0) / (R * temperature)
    if not np.all(np.isfinite(eta)) or np.any(np.abs(eta) > 600):
        raise ValueError("Potential range is outside the solver's numerical range (|nFη/RT| > 600).")
    return eta


def bv_rates(potential, e0, k_s, temperature, alpha=.5, n_e=1):
    """Cathodic alpha; return oxidation/reduction rates in cm/s."""
    eta = _dimensionless_potential(potential, e0, k_s, temperature, n_e)
    if not np.isfinite(alpha) or not 0 < alpha < 1:
        raise ValueError("BV alpha must lie strictly between 0 and 1.")
    if k_s == 0:
        return np.zeros_like(eta), np.zeros_like(eta)
    with np.errstate(over="raise", invalid="raise"):
        try:
            return np.exp(np.log(k_s) + (1-alpha)*eta), np.exp(np.log(k_s) - alpha*eta)
        except FloatingPointError as exc:
            raise ValueError("Kinetic rates overflow; check the input parameters.") from exc


def normalize_model(model):
    key = str(model).upper().replace("-", "").replace("–", "")
    if key not in {"BV", "MHL"}:
        raise ValueError("Choose B-V or MHL.")
    return key


@lru_cache(maxsize=8192)
def _log_mhl_integral(L, eta_abs):
    """Symmetric constant-DOS MHC integral evaluated by stable log quadrature.

    H(L,η) = integral exp[-(x-L+η)^2/(4L)] / (1+exp(x)) dx.
    Scaled Gaussian coordinates resolve both small and large lambda/(kBT).
    """
    root = math.sqrt(L)
    def log_integrand(y):
        return -y*y - np.logaddexp(0., L-eta_abs+2*root*y)
    bound = root+12.
    fit = minimize_scalar(lambda y: -log_integrand(y), bounds=(-bound, bound),
                          method="bounded", options={"xatol": 1e-11})
    if not fit.success:
        raise ValueError("MHL quadrature mode search failed.")
    mode, peak = float(fit.x), float(-fit.fun)
    integral, error = quad(lambda y: math.exp(log_integrand(y)-peak), mode-12., mode+12.,
                           epsabs=1e-11, epsrel=1e-10, limit=200, points=[mode])
    if integral <= 0 or error > 1e-8*integral:
        raise ValueError("MHL integral did not meet its numerical tolerance.")
    return math.log(2*root)+peak+math.log(integral)


def rate_constants(potential, e0, k_s, temperature, alpha=.5, n_e=1,
                   kinetic_model="BV", lambda_eV=None):
    """B-V or symmetric constant-DOS MHL rates, normalized to k_s at E0.

    Lambda is eV per modeled reaction event: L=lambda*F/(RT); driving energy
    is nF(E-E0). For n>1 this is an effective, not a multistep, model.
    Only the active model's parameter is used or validated.
    """
    model = normalize_model(kinetic_model)
    if model == "BV":
        return bv_rates(potential, e0, k_s, temperature, alpha, n_e)
    eta = _dimensionless_potential(potential, e0, k_s, temperature, n_e)
    try:
        lam = float(lambda_eV)
    except (TypeError, ValueError) as exc:
        raise ValueError("MHL requires a positive reorganization energy λ in eV.") from exc
    if not np.isfinite(lam) or lam <= 0:
        raise ValueError("MHL requires a positive reorganization energy λ in eV.")
    L = lam*F/(R*temperature)
    if not .01 <= L <= 1000:
        raise ValueError("MHL numerical range requires 0.01 ≤ λ/(kBT) ≤ 1000.")
    if k_s == 0:
        return np.zeros_like(eta), np.zeros_like(eta)
    reference = _log_mhl_integral(L, 0.)
    favorable = np.array([_log_mhl_integral(L, float(abs(x)))-reference
                         for x in eta.ravel()]).reshape(eta.shape)
    log_ox = favorable-np.maximum(-eta, 0.)
    log_red = favorable-np.maximum(eta, 0.)
    with np.errstate(over="raise", invalid="raise"):
        try:
            return np.exp(np.log(k_s)+log_ox), np.exp(np.log(k_s)+log_red)
        except FloatingPointError as exc:
            raise ValueError("MHL kinetic rates overflow; check the input parameters.") from exc


def kinetic_description(metadata):
    if metadata.get("model", "BV") == "MHL":
        return f"MHL · λ = {metadata['lambda_eV']:g} eV"
    return f"B-V · α = {metadata['alpha']:g}"


def simulate_cv(potential, dt, *, e0, k_s, diffusion_o, diffusion_r, temperature,
                area, initial_concentration, initial_species, n_e=1, alpha=.5,
                solver=None, cancel_event=None, progress_callback=None,
                kinetic_model="BV", lambda_eV=None):
    """Replay E(t) from uniform single-species bulk, without resetting at reversals.

    Implicit finite volumes on a stretched semi-infinite-domain approximation.
    Output t=0 is the instantaneous kinetic current of uniform bulk.
    """
    opts = solver or SolverOptions()
    if not isinstance(opts, SolverOptions):
        raise ValueError("solver must be a SolverOptions instance.")
    E = np.asarray(potential, dtype=float)
    if E.ndim != 1 or not 2 <= len(E) <= 100001 or not np.all(np.isfinite(E)):
        raise ValueError("Simulation needs 2–100001 finite potential samples.")
    for value in (dt, diffusion_o, diffusion_r, area, initial_concentration, opts.domain_factor):
        if not np.isfinite(value) or value <= 0:
            raise ValueError("Time step, diffusivities, area, concentration and domain must be positive.")
    if (not isinstance(opts.cells, int) or not 8 <= opts.cells <= 4000 or
            not isinstance(opts.substeps, int) or opts.substeps < 1 or
            (len(E)-1)*opts.substeps > 2000000 or opts.domain_factor < 3):
        raise ValueError("Solver resolution/domain is outside supported resource limits.")
    if initial_species not in {"O", "R"}:
        raise ValueError("Initial species must be O or R.")
    model = normalize_model(kinetic_model)
    def check_cancelled():
        if cancel_event is not None and cancel_event.is_set():
            raise SimulationCancelled("Back simulation cancelled; previous result retained.")
    check_cancelled()
    # Only the initial rates are needed here; the rest are evaluated during
    # stepping, so expensive MHL quadrature remains cancellable between samples.
    ko, kr = rate_constants(E[:1], e0, k_s, temperature, alpha, n_e, model, lambda_eV)
    step = dt / opts.substeps
    length = opts.domain_factor*np.sqrt(max(diffusion_o, diffusion_r)*(len(E)-1)*dt)
    first = min(.15*np.sqrt(min(diffusion_o, diffusion_r)*step), length/opts.cells)
    if not np.isfinite(length) or first <= 0 or not np.isfinite(step) or step <= 0:
        raise ValueError("Unrepresentable simulation mesh or time scale.")
    if np.isclose(first*opts.cells, length, rtol=1e-12, atol=0):
        widths = np.full(opts.cells, length/opts.cells)
    else:
        ratio = brentq(lambda g: first*np.expm1(opts.cells*g)/np.expm1(g)-length,
                       1e-14, 600/opts.cells)
        widths = first*np.exp(ratio*np.arange(opts.cells))
    centers = np.cumsum(widths) - widths/2
    conductance = 1/np.diff(centers)
    lower, upper = conductance/widths[1:], conductance/widths[:-1]
    diagonal = np.zeros(opts.cells)
    diagonal[:-1] -= upper
    diagonal[1:] -= lower
    bulk_source = np.zeros(opts.cells)
    bulk_source[-1] = 2/widths[-1]**2
    diagonal -= bulk_source
    operator = diags((lower, diagonal, upper), (-1, 0, 1), format="csc")
    co0 = initial_concentration if initial_species == "O" else 0.
    cr0 = initial_concentration if initial_species == "R" else 0.
    co, cr = np.full(opts.cells, co0), np.full(opts.cells, cr0)
    lu_o = splu(eye(opts.cells, format="csc") - step*diffusion_o*operator)
    lu_r = lu_o if diffusion_o == diffusion_r else splu(eye(opts.cells, format="csc") - step*diffusion_r*operator)
    injection = np.zeros(opts.cells)
    injection[0] = step/widths[0]
    go, gr = lu_o.solve(injection), lu_r.solve(injection)
    distance = widths[0]/2
    current, so, sr = np.empty(len(E)), np.empty(len(E)), np.empty(len(E))
    current[0] = n_e*F*area*(ko[0]*cr0-kr[0]*co0)
    so[0], sr[0] = co0, cr0
    max_balance, far_deviation, minimum = 0., 0., 0.
    fractions = np.arange(1, opts.substeps+1)/opts.substeps
    for i in range(1, len(E)):
        check_cancelled()
        if progress_callback and (i == 1 or i % 200 == 0):
            progress_callback(f"Simulating waveform: {i}/{len(E)-1} samples")
        ox, red = rate_constants(E[i-1]+(E[i]-E[i-1])*fractions, e0, k_s, temperature,
                                alpha, n_e, model, lambda_eV)
        for substep, (o, r) in enumerate(zip(ox, red)):
            if substep % 256 == 0:
                check_cancelled()
            bo = lu_o.solve(co + step*diffusion_o*bulk_source*co0)
            br = lu_r.solve(cr + step*diffusion_r*bulk_source*cr0)
            scale = max(1., o, r)
            o, r, inv = o/scale, r/scale, 1/scale
            denominator = inv+o*distance/diffusion_r+r*distance/diffusion_o
            o, r = o/denominator, r/denominator
            flux = (o*br[0]-r*bo[0])/(1+o*gr[0]+r*go[0])
            new_o, new_r = bo+go*flux, br-gr*flux
            surface_o = new_o[0]+flux*distance/diffusion_o
            surface_r = new_r[0]-flux*distance/diffusion_r
            minimum = min(minimum, new_o.min(), new_r.min(), surface_o, surface_r)
            if (not np.all(np.isfinite(new_o)) or not np.all(np.isfinite(new_r)) or
                    minimum < -1e-8*initial_concentration):
                raise ValueError("Nonphysical simulation concentrations; check parameters or refine resolution.")
            for old, new, D, bulk, sign in ((co,new_o,diffusion_o,co0,1), (cr,new_r,diffusion_r,cr0,-1)):
                delta = float(widths@(new-old))
                expected = step*(float(widths@(D*bulk_source*(bulk-new)))+sign*flux)
                normalizer = max(abs(delta), abs(expected), initial_concentration*length*1e-12)
                max_balance = max(max_balance, abs(delta-expected)/normalizer)
                far_deviation = max(far_deviation, abs(new[-1]-bulk)/initial_concentration)
            co, cr = new_o, new_r
        current[i], so[i], sr[i] = n_e*F*area*flux, surface_o, surface_r
    if not np.all(np.isfinite(current)):
        raise ValueError("Simulation current is nonfinite; check input scales.")
    warnings = []
    if model == "MHL" and n_e != 1:
        warnings.append("MHL with n > 1 uses an effective reaction model, with λ in eV per modeled event.")
    if abs(current[0]) > .05*max(np.max(np.abs(current[1:])), 1e-300):
        warnings.append("Significant initial kinetic current: no pre-equilibration hold was assumed.")
    if far_deviation > 1e-4:
        warnings.append("Remote concentration changed appreciably; enlarge the numerical domain.")
    metadata = dict(version=VERSION, model=model,
        kinetic_model="Butler–Volmer" if model == "BV" else "MHL (symmetric constant-DOS MHC)", diffusion_model="planar",
        alpha=float(alpha) if model == "BV" else None,
        lambda_eV=float(lambda_eV) if model == "MHL" else None,
        e0_v=float(e0), k_s_cm_s=float(k_s), n_e=int(n_e),
        diffusion_o_cm2_s=float(diffusion_o), diffusion_r_cm2_s=float(diffusion_r),
        temperature_k=float(temperature), area_cm2=float(area), initial_species=initial_species,
        initial_concentration_mol_cm3=float(initial_concentration), output_dt_s=float(dt),
        internal_dt_s=float(step), solver=asdict(opts), domain_cm=float(length),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        current_convention="anodic positive", initial_condition="uniform single species, no hold")
    return CVSimulation(np.arange(len(E))*dt, E.copy(), current, so, sr, metadata,
        dict(warnings=warnings, max_mass_balance_relative_residual=float(max_balance),
             minimum_concentration_mol_cm3=float(minimum), far_boundary_fraction=float(far_deviation)))
