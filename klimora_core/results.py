from __future__ import annotations
import pyomo.environ as pyo

def _safe(v):
    try: return float(pyo.value(v))
    except Exception: return None

def _indexed(var):
    return {"|".join(map(str, idx if isinstance(idx, tuple) else (idx,))): _safe(var[idx]) for idx in var}

def extract_results(pm, res):
    out = {
        "status": str(res.solver.status),
        "termination_condition": str(res.solver.termination_condition),
        "objective": _safe(pm.OBJ),
        "activity": _indexed(pm.activity), "capacity": _indexed(pm.capacity),
        "new_capacity": _indexed(pm.new_capacity), "commissioned_capacity": _indexed(pm.commissioned_capacity),
        "retirement": _indexed(pm.retirement), "vintage_capacity": _indexed(pm.vintage_capacity),
        "imports": _indexed(pm.imports), "exports": _indexed(pm.exports),
        "emissions": {str(y): _safe(pm.Emissions[y]) for y in pm.Y},
    }
    for name in ("charge","discharge","soc","transmit"):
        if hasattr(pm, name): out[name] = _indexed(getattr(pm,name))
    if hasattr(pm, "TechInput"):
        out["commodity"] = {}
        for c in pm.C:
            for n in pm.N:
                for y in pm.Y:
                    for ts in pm.TS:
                        key=f"{c}|{n}|{y}|{ts}"
                        out["commodity"][key]={"production":_safe(pm.TechOutput[c,n,y,ts]),"consumption":_safe(pm.TechInput[c,n,y,ts]),"imports":_safe(pm.imports[c,n,y,ts]),"exports":_safe(pm.exports[c,n,y,ts]),"storage_charge":_safe(pm.StorageCharge[c,n,y,ts]),"storage_discharge":_safe(pm.StorageDischarge[c,n,y,ts])}
    return out
