from __future__ import annotations
from copy import deepcopy
from .schema import Model, Scenario

def scenario_chain(m: Model, scenario_id: str) -> list[Scenario]:
    by_id={s.id:s for s in m.scenarios}
    if scenario_id not in by_id:
        raise KeyError(f"unknown scenario: {scenario_id}")
    chain=[]; seen=set(); cur=scenario_id
    while cur:
        if cur in seen: raise ValueError("scenario inheritance cycle detected")
        seen.add(cur)
        s=by_id[cur]; chain.append(s); cur=s.parent_id
    return list(reversed(chain))

def apply_scenario(m: Model, scenario_id: str) -> Model:
    out=deepcopy(m)
    chain=scenario_chain(out,scenario_id)
    for sc in chain:
        for ov in sc.overrides:
            parts=ov.parameter.split(".")
            values=ov.values
            if parts[0]=="technology" and len(parts)>=3:
                t=next((x for x in out.technologies if x.id==parts[1]),None)
                if t is None: raise KeyError(f"override technology not found: {parts[1]}")
                field=parts[2]
                target=getattr(t,field,None)
                if not isinstance(target,dict): raise ValueError(f"{ov.parameter} is not a year-indexed field")
                for y,v in values.items(): target[int(y)]=v
            elif parts[0]=="service" and len(parts)>=3:
                s=next((x for x in out.services if x.id==parts[1]),None)
                if s is None: raise KeyError(f"override service not found: {parts[1]}")
                field=parts[2]
                target=getattr(s,field,None)
                if not isinstance(target,dict): raise ValueError(f"{ov.parameter} is not a year-indexed field")
                for y,v in values.items(): target[int(y)]=v
            elif parts[0]=="commodity" and len(parts)>=3:
                c=next((x for x in out.commodities if x.id==parts[1]),None)
                if c is None: raise KeyError(f"override commodity not found: {parts[1]}")
                field=parts[2]
                if field=="price":
                    for y,v in values.items(): c.price[int(y)]=float(v)
                else: raise ValueError(f"unsupported commodity override: {ov.parameter}")
            elif parts[0]=="meta" and len(parts)==2:
                setattr(out.meta,parts[1],next(iter(values.values())))
            else:
                raise ValueError(f"unsupported override path: {ov.parameter}")
    return out
