from __future__ import annotations
from collections import defaultdict
from .hierarchy import descendants
from .units import convert

def aggregate_records(model, records, value_key='value', node_key='node_id', unit_key='unit', target_unit=None, target_node=None):
    """Roll up flat result records across the user-defined node hierarchy.

    Records are dictionaries. Non-node dimensions are preserved in the grouping key.
    Values are converted before aggregation when target_unit is supplied.
    """
    allowed = set(descendants(model, target_node, include_self=True)) if target_node else None
    groups=defaultdict(float); meta={}
    for r in records:
        nid=r.get(node_key)
        if allowed is not None and nid not in allowed: continue
        rr=dict(r); val=float(rr[value_key])
        if target_unit and rr.get(unit_key): val=convert(val, rr[unit_key], target_unit)
        key=tuple((k,rr.get(k)) for k in sorted(rr) if k not in {value_key,node_key,unit_key})
        groups[key]+=val
        meta[key]=rr
    out=[]
    for key,v in groups.items():
        rr={k:x for k,x in key}; rr[node_key]=target_node or 'aggregate'; rr[value_key]=v
        if target_unit: rr[unit_key]=target_unit
        out.append(rr)
    return out
