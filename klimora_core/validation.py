from __future__ import annotations
from collections import Counter
from .schema import Model
from .hierarchy import validate_hierarchy
from .units import parse_unit

def validate_model(m: Model) -> list[str]:
    errors = []
    errors.extend(validate_hierarchy(m))
    periods = m.meta.periods
    if not periods:
        return ["meta.periods must not be empty"]
    if periods != sorted(periods):
        errors.append("meta.periods must be sorted")
    if len(set(periods)) != len(periods):
        errors.append("meta.periods must be unique")
    if periods[0] != m.meta.base_year:
        errors.append("first period must equal base_year")
    if periods[-1] != m.meta.end_year:
        errors.append("last period must equal end_year")

    def ids(xs, label):
        c = Counter(x.id for x in xs)
        errors.extend(f"duplicate {label} id: {k}" for k, v in c.items() if v > 1)
        return set(c)

    tech_ids = ids(m.technologies, "technology")
    com_ids = ids(m.commodities, "commodity")
    svc_ids = ids(m.services, "service")
    node_ids = ids(m.nodes, "node")
    storage_ids = ids(m.storages, "storage")

    for t in m.technologies:
        if t.node_id is not None and t.node_id not in node_ids:
            errors.append(f"technology {t.id}: unknown node {t.node_id}")
        if t.service_id is not None and t.service_id not in svc_ids:
            errors.append(f"technology {t.id}: unknown service {t.service_id}")
        if t.lifetime <= 0:
            errors.append(f"technology {t.id}: lifetime must be > 0")
        if t.lead_time < 0:
            errors.append(f"technology {t.id}: lead_time must be >= 0")
        if t.unit_capacity <= 0:
            errors.append(f"technology {t.id}: unit_capacity must be > 0")
        for p, v in t.availability.items():
            if v < 0 or v > 1:
                errors.append(f"technology {t.id}: availability {p} must be 0..1")
        for p, v in t.min_load.items():
            if v < 0 or v > 1:
                errors.append(f"technology {t.id}: min_load {p} must be 0..1")

    for f in m.flows:
        if f.technology_id not in tech_ids:
            errors.append(f"flow: unknown technology {f.technology_id}")
        if f.commodity_id not in com_ids:
            errors.append(f"flow: unknown commodity {f.commodity_id}")
        if any(v < 0 for v in f.coefficient.values()):
            errors.append(f"flow {f.technology_id}/{f.commodity_id}: negative coefficient")

    for s in m.stock:
        if s.node_id is not None and s.node_id not in node_ids:
            errors.append(f"stock {s.technology_id}/{s.vintage}: unknown node {s.node_id}")
        if s.technology_id not in tech_ids:
            errors.append(f"stock: unknown technology {s.technology_id}")
        if s.capacity < 0:
            errors.append(f"stock {s.technology_id}/{s.vintage}: negative capacity")
        if s.lifetime <= 0:
            errors.append(f"stock {s.technology_id}/{s.vintage}: lifetime must be > 0")

    for svc in m.services:
        if svc.node_id is not None and svc.node_id not in node_ids:
            errors.append(f"service {svc.id}: unknown node {svc.node_id}")
        if svc.demand_driver_id is not None and svc.demand_driver_id not in {d.id for d in m.demand_drivers}:
            errors.append(f"service {svc.id}: unknown demand driver {svc.demand_driver_id}")

    for s in m.storages:
        if s.node_id is not None and s.node_id not in node_ids:
            errors.append(f"storage {s.id}: unknown node {s.node_id}")
        if s.commodity_id not in com_ids:
            errors.append(f"storage {s.id}: unknown commodity {s.commodity_id}")
        if not 0 < s.charge_efficiency <= 1:
            errors.append(f"storage {s.id}: charge_efficiency must be in (0,1]")
        if not 0 < s.discharge_efficiency <= 1:
            errors.append(f"storage {s.id}: discharge_efficiency must be in (0,1]")

    for l in m.network_links:
        if l.commodity_id not in com_ids: errors.append(f"network link {l.id}: unknown commodity {l.commodity_id}")
        if l.from_node not in node_ids: errors.append(f"network link {l.id}: unknown from_node {l.from_node}")
        if l.to_node not in node_ids: errors.append(f"network link {l.id}: unknown to_node {l.to_node}")
        for y,v in l.loss.items():
            if v < 0 or v > 1: errors.append(f"network link {l.id}: loss {y} must be 0..1")

    for c in m.constraints:
        if c.period not in periods:
            errors.append(f"constraint {c.id}: period {c.period} not in horizon")
        if c.type == "emission_cap":
            continue
        if c.type in {"commodity_max", "commodity_min", "resource_max"} and c.target_id not in com_ids:
            errors.append(f"constraint {c.id}: unknown commodity {c.target_id}")
        if c.type in {"capacity_max", "min_share", "max_share"} and c.target_id not in tech_ids:
            errors.append(f"constraint {c.id}: unknown technology {c.target_id}")
        if c.type in {"min_share", "max_share"} and not 0 <= c.value <= 1:
            errors.append(f"constraint {c.id}: share value must be 0..1")
        if c.node_id is not None and c.node_id not in node_ids:
            errors.append(f"constraint {c.id}: unknown node {c.node_id}")

    for svc in m.services:
        try: parse_unit(svc.unit)
        except ValueError as e: errors.append(f'service {svc.id}: {e}')
    for com in m.commodities:
        try: parse_unit(com.unit)
        except ValueError as e: errors.append(f'commodity {com.id}: {e}')
    for ts in m.time_slices:
        if ts.weight < 0 or ts.hours < 0:
            errors.append(f"time slice {ts.id}: weight/hours must be non-negative")
    return errors
