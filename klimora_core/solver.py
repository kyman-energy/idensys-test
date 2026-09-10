from __future__ import annotations
import pyomo.environ as pyo
from .compiler import compile_model
from .schema import Model
from .validation import validate_model

def solve_model(m:Model,solver_name="highs"):
    errors=validate_model(m)
    if errors: raise ValueError("; ".join(errors))
    pm=compile_model(m)
    solver=pyo.SolverFactory(solver_name)
    if not solver.available(exception_flag=False):
        raise RuntimeError(f"Solver '{solver_name}' unavailable. Install highspy for HiGHS.")
    result=solver.solve(pm,tee=False)
    return pm,result
