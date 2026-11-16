"""Potential-endpoint references, expressed as indices in the cleaned full trace."""

NORMALIZATION_VERSION = "potential-endpoints-selected-cycle-v1"


def concentration_references(potential, segments, cycle):
    keys = list(segments)
    first = 2 * (cycle - 1)
    if cycle < 1 or first + 1 >= len(keys):
        raise ValueError(
            f"Requested CV cycle {cycle}, but only {len(keys) // 2} complete "
            "cycle(s) were detected."
        )
    forward, backward = keys[first:first + 2]

    def endpoints(a, b):
        # O is zero at the negative endpoint; R at the positive endpoint.
        if potential[a] == potential[b]:
            raise ValueError("Concentration reference endpoints must have different potentials.")
        return (a, b) if potential[a] < potential[b] else (b, a)

    # The reversal sample is the last point of the outgoing scan. Existing
    # half-open scan boundaries are retained, including at duplicate endpoints.
    anchor = 0 if cycle == 1 else backward[1] - 1
    pairs = {
        "original": endpoints(anchor, forward[1] - 1),
        "forward": endpoints(forward[0], forward[1] - 1),
        "backward": endpoints(backward[0], backward[1] - 1),
    }
    return {f"{scope}_{species}": index for scope, pair in pairs.items()
            for species, index in zip(("o", "r"), pair)}


def normalization_metadata(result):
    dt = result.delta_e / result.config.scan_rate
    return {
        "model_version": result.normalization_version,
        "selected_cycle": result.config.cv_cycles_n,
        "rule": "O zero at negative endpoint; R zero at positive endpoint",
        "full_trace_anchor": "initial_point" if result.config.cv_cycles_n == 1 else "selected_cycle_final_point",
        "reference_indices": dict(result.concentration_reference_indices),
        "reference_potentials_v": {key: float(result.potential[index])
                                   for key, index in result.concentration_reference_indices.items()},
        "reference_times_s": {key: index * dt for key, index in result.concentration_reference_indices.items()},
        "index_basis": "zero-based cleaned full trace",
        "negative_concentrations": "retained without clipping or negative-value warnings",
    }
