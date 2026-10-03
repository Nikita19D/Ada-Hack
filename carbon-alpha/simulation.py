"""Monte Carlo delivery-risk calculations for selected carbon-credit projects.

Optimised for ngrok hosting: NumPy vectorisation when available
(~50-100x faster), pure-Python fallback otherwise.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Mapping
from numbers import Real

__all__ = ["simulate_portfolio", "stress_once"]

try:
    import numpy as _np

    _HAS_NUMPY = True
except Exception:  # environment without numpy
    _np = None  # type: ignore
    _HAS_NUMPY = False


def _validate_inputs(projects, target, n_simulations=None):
    if not isinstance(projects, list) or not projects:
        raise ValueError("projects must be a non-empty list.")
    if (
        isinstance(target, bool)
        or not isinstance(target, Real)
        or not math.isfinite(target)
        or target < 0
    ):
        raise ValueError("target must be a finite, non-negative number.")
    if n_simulations is not None and (
        isinstance(n_simulations, bool)
        or not isinstance(n_simulations, int)
        or n_simulations <= 0
    ):
        raise ValueError("n_simulations must be a positive integer.")

    for index, project in enumerate(projects):
        if not isinstance(project, Mapping):
            raise ValueError(f"Project {index + 1} must be a dictionary.")
        if "id" not in project or project["id"] is None or project["id"] == "":
            raise ValueError(f"Project {index + 1} is missing a valid id.")
        if (
            "project_name" not in project
            or not isinstance(project["project_name"], str)
            or not project["project_name"].strip()
        ):
            raise ValueError(f"Project {project['id']} is missing a valid project_name.")
        if "co2" not in project:
            raise ValueError(f"Project {project['id']} is missing co2.")
        if "failure_probability" not in project:
            raise ValueError(f"Project {project['id']} is missing failure_probability.")

        co2 = project["co2"]
        if (
            isinstance(co2, bool)
            or not isinstance(co2, Real)
            or not math.isfinite(co2)
            or co2 < 0
        ):
            raise ValueError(
                f"Project {project['id']} co2 must be a finite, non-negative number."
            )

        failure_probability = project["failure_probability"]
        if (
            isinstance(failure_probability, bool)
            or not isinstance(failure_probability, Real)
            or not math.isfinite(failure_probability)
            or not 0 <= failure_probability <= 1
        ):
            raise ValueError(
                f"Project {project['id']} failure_probability must be between 0 and 1."
            )
        recovery = project.get("loss_recovery_fraction", 0)
        if (isinstance(recovery, bool) or not isinstance(recovery, Real)
                or not math.isfinite(recovery) or not 0 <= recovery <= 1):
            raise ValueError("loss_recovery_fraction must be between 0 and 1.")


def _simulate_numpy(projects, n_simulations) -> list[float]:
    """Vectorised simulation: one RNG draw per (simulation, project)."""
    seed = random.getrandbits(32)  # keeps `random.seed(x)` reproducible
    rng = _np.random.default_rng(seed)
    co2 = _np.asarray([float(p["co2"]) for p in projects], dtype=_np.float64)
    failure = _np.asarray(
        [float(p["failure_probability"]) for p in projects], dtype=_np.float64
    )
    recovery = _np.asarray(
        [float(p.get("loss_recovery_fraction", 0)) for p in projects],
        dtype=_np.float64,
    )
    draws = rng.random((n_simulations, len(projects)))
    totals = _np.where(draws >= failure, co2, co2 * recovery).sum(axis=1)
    return totals.tolist()


def _simulate_python(projects, n_simulations) -> list[float]:
    results = []
    for _ in range(n_simulations):
        delivered = sum(
            project["co2"] if random.random() >= project["failure_probability"]
            else project["co2"] * project.get("loss_recovery_fraction", 0)
            for project in projects
        )
        results.append(delivered)
    return results


def simulate_portfolio(projects, n_simulations=5000, target=100000):
    """Simulate project failures and summarize delivered credits across scenarios."""
    _validate_inputs(projects, target, n_simulations)

    if _HAS_NUMPY and n_simulations * len(projects) >= 1000:
        simulation_results = _simulate_numpy(projects, n_simulations)
    else:
        simulation_results = _simulate_python(projects, n_simulations)

    successful_simulations = sum(
        delivered >= target for delivered in simulation_results
    )
    success_probability = successful_simulations / n_simulations
    return {
        "target": target,
        "simulations": n_simulations,
        "success_probability": success_probability,
        "shortfall_probability": 1 - success_probability,
        "expected_co2": statistics.mean(simulation_results),
        "median_co2": statistics.median(simulation_results),
        "simulation_results": simulation_results,
    }


def stress_once(projects, target=100000):
    """Generate one random project-by-project delivery scenario."""
    _validate_inputs(projects, target)

    scenario_projects = []
    total_delivered = 0
    for project in projects:
        survived = random.random() >= project["failure_probability"]
        delivered_co2 = (project["co2"] if survived else
                         project["co2"] * project.get("loss_recovery_fraction", 0))
        total_delivered += delivered_co2

        scenario_project = {
            "id": project["id"],
            "project_name": project["project_name"],
            "survived": survived,
            "delivered_co2": delivered_co2,
        }
        scenario_projects.append(scenario_project)

    return {
        "projects": scenario_projects,
        "total_delivered": total_delivered,
        "target_reached": total_delivered >= target,
    }
