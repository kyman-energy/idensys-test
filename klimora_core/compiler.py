from __future__ import annotations
import pyomo.environ as pyo
from .schema import Model


def val(d, year, default=0.0):
    if not d:
        return default
    d2 = {int(k): v for k, v in d.items()}
    if year in d2:
        return d2[year]
    ks = sorted(d2)
    prior = [k for k in ks if k <= year]
    return d2[prior[-1]] if prior else d2[ks[0]]


def slice_val(d, sid, default=1.0):
    if not d:
        return default
    return d.get(sid, default)


def compile_model(m: Model):
    years = list(m.meta.periods)
    slices = m.time_slices or []
    if not slices:
        slices = [type("AnnualSlice", (), {"id": "annual", "name": "Annual", "weight": 1.0, "hours": 8760, "period": None})()]
    # Map slices to periods. If omitted, every slice belongs to every model year.
    slice_ids = [s.id for s in slices]
    slice_year = {s.id: s.period for s in slices}
    techs = [t.id for t in m.technologies]
    services = [s.id for s in m.services]
    commodities = [c.id for c in m.commodities]
    nodes = [n.id for n in m.nodes] or ["default"]
    td = {t.id: t for t in m.technologies}
    cd = {c.id: c for c in m.commodities}
    sd = {s.id: s for s in m.services}
    stocks = list(m.stock)
    vintages = sorted(set(s.vintage for s in stocks) | set(years))

    def tech_node(k): return td[k].node_id or nodes[0]
    def service_node(s): return sd[s].node_id or nodes[0]

    M = pyo.ConcreteModel("KlimoraEngineV5")
    M.Y = pyo.Set(initialize=years, ordered=True)
    M.TS = pyo.Set(initialize=slice_ids)
    M.K = pyo.Set(initialize=techs)
    M.S = pyo.Set(initialize=services)
    M.C = pyo.Set(initialize=commodities)
    M.N = pyo.Set(initialize=nodes)
    M.V = pyo.Set(initialize=vintages)
    M.KB = pyo.Set(initialize=[t.id for t in m.technologies if t.decision == "binary"])
    M.KI = pyo.Set(initialize=[t.id for t in m.technologies if t.decision == "integer"])

    # Annual capacity and investment; dispatch is time-slice resolved.
    M.activity = pyo.Var(M.K, M.Y, M.TS, domain=pyo.NonNegativeReals)
    M.capacity = pyo.Var(M.K, M.Y, domain=pyo.NonNegativeReals)
    M.new_capacity = pyo.Var(M.K, M.Y, domain=pyo.NonNegativeReals)
    M.commissioned_capacity = pyo.Var(M.K, M.Y, domain=pyo.NonNegativeReals)
    M.vintage_capacity = pyo.Var(M.K, M.V, M.Y, domain=pyo.NonNegativeReals)
    M.retirement = pyo.Var(M.K, M.V, M.Y, domain=pyo.NonNegativeReals)
    M.build_binary = pyo.Var(M.KB, M.Y, domain=pyo.Binary)
    M.build_integer = pyo.Var(M.KI, M.Y, domain=pyo.NonNegativeIntegers)
    minload_techs = [t.id for t in m.technologies if any(float(v) > 0 for v in t.min_load.values())]
    M.dispatch_on = pyo.Var(minload_techs, M.Y, M.TS, domain=pyo.Binary)

    M.imports = pyo.Var(M.C, M.N, M.Y, M.TS, domain=pyo.NonNegativeReals)
    M.exports = pyo.Var(M.C, M.N, M.Y, M.TS, domain=pyo.NonNegativeReals)

    storage_ids = [s.id for s in m.storages]
    M.charge = pyo.Var(storage_ids, M.Y, M.TS, domain=pyo.NonNegativeReals)
    M.discharge = pyo.Var(storage_ids, M.Y, M.TS, domain=pyo.NonNegativeReals)
    M.soc = pyo.Var(storage_ids, M.Y, M.TS, domain=pyo.NonNegativeReals)

    link_ids = [x.id for x in m.network_links]
    M.transmit = pyo.Var(link_ids, M.Y, M.TS, domain=pyo.NonNegativeReals)

    # Time-slice demand: demand is allocated using slice weights unless explicit slice mapping exists.
    def service_demand(s, y):
        svc = sd[s]
        if svc.demand_driver_id:
            drv = next((d for d in m.demand_drivers if d.id == svc.demand_driver_id), None)
            if drv is not None:
                base = svc.demand_base_value if svc.demand_base_value is not None else val(svc.demand, svc.demand_base_year or years[0], 0.0)
                ref = val(drv.values, svc.demand_base_year or years[0], 1.0)
                return base * val(svc.demand_driver_multiplier, y, 1.0) * val(drv.values, y, 0.0) / max(ref, 1e-12)
        return val(svc.demand, y, 0.0)

    M.ServiceBalance = pyo.Constraint(M.S, M.Y, M.TS)
    for s in services:
        ks = [k for k in techs if td[k].service_id == s]
        for y in years:
            active_slices = [x for x in slices if x.period is None or x.period == y]
            total_weight = sum(max(0.0, x.weight) for x in active_slices) or 1.0
            for x in active_slices:
                demand_ts = service_demand(s, y) * x.weight / total_weight
                M.ServiceBalance[s, y, x.id] = sum(M.activity[k, y, x.id] for k in ks) >= demand_ts
            for x in slices:
                if x not in active_slices:
                    M.ServiceBalance[s, y, x.id] = pyo.Constraint.Skip

    # Commissioning with period-based lead time.
    M.Commissioning = pyo.Constraint(M.K, M.Y)
    for k in techs:
        lt = max(0, int(td[k].lead_time))
        for y in years:
            source_year = y - lt
            inv = M.new_capacity[k, source_year] if source_year in years else 0
            M.Commissioning[k, y] = M.commissioned_capacity[k, y] == inv

    M.VintageDynamics = pyo.ConstraintList()
    M.VintageRetirementLimit = pyo.ConstraintList()
    stock_by_kv = {(s.technology_id, s.vintage): s for s in stocks}
    for k in techs:
        lifetime_default = max(1, int(td[k].lifetime))
        for v in vintages:
            initial = stock_by_kv.get((k, v))
            life = initial.lifetime if initial else lifetime_default
            for y in years:
                prior_y = years[years.index(y)-1] if y != years[0] else None
                valid = v <= y < v + life
                if not valid:
                    M.VintageDynamics.add(M.vintage_capacity[k, v, y] == 0)
                    M.VintageRetirementLimit.add(M.retirement[k, v, y] == 0)
                    continue
                commissioned = M.new_capacity[k, y] if v == y else 0
                if prior_y is None:
                    initial_cap = initial.capacity if initial else 0.0
                    M.VintageDynamics.add(M.vintage_capacity[k, v, y] == initial_cap + commissioned - M.retirement[k, v, y])
                    available = initial_cap + commissioned
                else:
                    M.VintageDynamics.add(M.vintage_capacity[k, v, y] == M.vintage_capacity[k, v, prior_y] + commissioned - M.retirement[k, v, y])
                    available = M.vintage_capacity[k, v, prior_y] + commissioned
                if initial and v == initial.vintage and not initial.retireable:
                    M.VintageRetirementLimit.add(M.retirement[k, v, y] == 0)
                else:
                    M.VintageRetirementLimit.add(M.retirement[k, v, y] <= available)

    M.CapacityAggregation = pyo.Constraint(M.K, M.Y)
    for k in techs:
        for y in years:
            M.CapacityAggregation[k, y] = M.capacity[k, y] == sum(M.vintage_capacity[k, v, y] for v in vintages)

    # Dispatch bounds and explicit time-slice availability.
    M.ActivityCapacity = pyo.Constraint(M.K, M.Y, M.TS)
    for k in techs:
        for y in years:
            active_slices = [x for x in slices if x.period is None or x.period == y]
            for x in slices:
                if x not in active_slices:
                    M.ActivityCapacity[k, y, x.id] = pyo.Constraint.Skip
                    continue
                avail = max(0.0, val(td[k].availability, y, 1.0)) * max(0.0, slice_val(td[k].time_slice_availability, x.id, 1.0))
                M.ActivityCapacity[k, y, x.id] = M.activity[k, y, x.id] <= M.capacity[k, y] * avail

    M.MinLoad = pyo.ConstraintList()
    for k in techs:
        for y in years:
            ml = val(td[k].min_load, y, 0.0)
            if ml > 0 and k in minload_techs:
                active = [x for x in slices if x.period is None or x.period == y]
                for x in active:
                    avail = max(0.0, val(td[k].availability, y, 1.0)) * max(0.0, slice_val(td[k].time_slice_availability, x.id, 1.0))
                    M.MinLoad.add(M.activity[k, y, x.id] <= M.capacity[k, y] * avail * M.dispatch_on[k, y, x.id])
                    M.MinLoad.add(M.activity[k, y, x.id] >= ml * M.capacity[k, y] * M.dispatch_on[k, y, x.id])

    M.InvestmentLink = pyo.ConstraintList()
    for k in M.KB:
        for y in years:
            M.InvestmentLink.add(M.new_capacity[k, y] <= td[k].unit_capacity * M.build_binary[k, y])
    for k in M.KI:
        for y in years:
            M.InvestmentLink.add(M.new_capacity[k, y] == td[k].unit_capacity * M.build_integer[k, y])

    M.CapacityMax = pyo.ConstraintList()
    for k in techs:
        for y in years:
            mx = val(td[k].max_capacity, y, None)
            if mx is not None:
                M.CapacityMax.add(M.capacity[k, y] <= mx)

    # Commodity flow expressions by node, year, slice.
    def flow_coeff(f, y, sid):
        return val(f.coefficient, y, 0.0) * slice_val(f.time_slice_coefficient, sid, 1.0)

    def tech_input(c, n, y, sid):
        return sum(M.activity[k, y, sid] * flow_coeff(f, y, sid)
                   for k in techs if tech_node(k) == n
                   for f in m.flows if f.technology_id == k and f.commodity_id == c and f.direction == "input"
                   and (f.node_id is None or f.node_id == n))

    def tech_output(c, n, y, sid):
        return sum(M.activity[k, y, sid] * flow_coeff(f, y, sid)
                   for k in techs if tech_node(k) == n
                   for f in m.flows if f.technology_id == k and f.commodity_id == c and f.direction == "output"
                   and (f.node_id is None or f.node_id == n))

    M.TechInput = pyo.Expression(M.C, M.N, M.Y, M.TS, rule=lambda mm,c,n,y,x: tech_input(c,n,y,x))
    M.TechOutput = pyo.Expression(M.C, M.N, M.Y, M.TS, rule=lambda mm,c,n,y,x: tech_output(c,n,y,x))

    M.StorageCharge = pyo.Expression(M.C, M.N, M.Y, M.TS, rule=lambda mm,c,n,y,x: sum(M.charge[s.id,y,x] for s in m.storages if s.commodity_id == c and (s.node_id or nodes[0]) == n))
    M.StorageDischarge = pyo.Expression(M.C, M.N, M.Y, M.TS, rule=lambda mm,c,n,y,x: sum(M.discharge[s.id,y,x] for s in m.storages if s.commodity_id == c and (s.node_id or nodes[0]) == n))

    # Network inflow/outflow. Loss applies to received flow.
    M.NetworkIn = pyo.Expression(M.C, M.N, M.Y, M.TS, rule=lambda mm,c,n,y,x: sum(M.transmit[l.id,y,x] * (1-val(l.loss,y,0.0)) for l in m.network_links if l.commodity_id == c and l.to_node == n))
    M.NetworkOut = pyo.Expression(M.C, M.N, M.Y, M.TS, rule=lambda mm,c,n,y,x: sum(M.transmit[l.id,y,x] for l in m.network_links if l.commodity_id == c and l.from_node == n))

    emission_carriers = [c for c in commodities if cd[c].emission_carrier or cd[c].type.lower() == "emission"]
    M.Emissions = pyo.Expression(M.Y, rule=lambda mm,y: sum(M.TechOutput[c,n,y,x] for c in emission_carriers for n in nodes for x in slice_ids if slice_year[x] in (None,y)))

    balance_commodities = [c for c in commodities if c not in emission_carriers]
    M.CommodityBalance = pyo.Constraint(balance_commodities, M.N, M.Y, M.TS)
    for c in balance_commodities:
        mode = cd[c].balance_mode
        for n in nodes:
            for y in years:
                for x in slices:
                    if x.period is not None and x.period != y:
                        M.CommodityBalance[c,n,y,x.id] = pyo.Constraint.Skip
                        continue
                    lhs = M.TechOutput[c,n,y,x.id] + M.imports[c,n,y,x.id] + M.StorageDischarge[c,n,y,x.id] + M.NetworkIn[c,n,y,x.id]
                    rhs = M.TechInput[c,n,y,x.id] + M.exports[c,n,y,x.id] + M.StorageCharge[c,n,y,x.id] + M.NetworkOut[c,n,y,x.id]
                    if mode == "strict": M.CommodityBalance[c,n,y,x.id] = lhs == rhs
                    elif mode == "supply_only": M.CommodityBalance[c,n,y,x.id] = lhs >= rhs
                    else: M.CommodityBalance[c,n,y,x.id] = pyo.Constraint.Skip

    M.TradeBounds = pyo.ConstraintList()
    for c in commodities:
        cc=cd[c]
        for n in nodes:
            for y in years:
                for x in slices:
                    if x.period is not None and x.period != y: continue
                    if not cc.allow_import: M.TradeBounds.add(M.imports[c,n,y,x.id] == 0)
                    else:
                        lim=val(cc.import_max,y,None)
                        if lim is not None: M.TradeBounds.add(M.imports[c,n,y,x.id] <= lim)
                    if not cc.allow_export: M.TradeBounds.add(M.exports[c,n,y,x.id] == 0)
                    else:
                        lim=val(cc.export_max,y,None)
                        if lim is not None: M.TradeBounds.add(M.exports[c,n,y,x.id] <= lim)

    M.ResourceLimit = pyo.ConstraintList()
    for c in balance_commodities:
        for n in nodes:
            for y in years:
                lim=val(cd[c].max_available,y,None)
                if lim is not None:
                    M.ResourceLimit.add(sum(M.TechInput[c,n,y,x.id]+M.StorageCharge[c,n,y,x.id] for x in slices if x.period is None or x.period==y) <= lim)

    # Storage dynamics across time slices; annual boundaries carry the last SOC.
    M.StorageState = pyo.ConstraintList(); M.StoragePower=pyo.ConstraintList(); M.StorageEnergy=pyo.ConstraintList()
    for s in m.storages:
        prev_soc = None
        for y in years:
            active=[x for x in slices if x.period is None or x.period==y]
            for x in active:
                loss=max(0,min(1,val(s.standing_loss,y,0)))
                ce=max(1e-9,s.charge_efficiency); de=max(1e-9,s.discharge_efficiency)
                prev = val(s.initial_soc,y,0) if prev_soc is None else prev_soc
                M.StorageState.add(M.soc[s.id,y,x.id] == prev*(1-loss) + ce*M.charge[s.id,y,x.id] - M.discharge[s.id,y,x.id]/de)
                pmax=val(s.power_capacity,y,None); emax=val(s.energy_capacity,y,None)
                if pmax is not None:
                    M.StoragePower.add(M.charge[s.id,y,x.id] <= pmax); M.StoragePower.add(M.discharge[s.id,y,x.id] <= pmax)
                if emax is not None: M.StorageEnergy.add(M.soc[s.id,y,x.id] <= emax)
                prev_soc=M.soc[s.id,y,x.id]
            final=val(s.final_soc_min,y,None)
            if y==years[-1] and final is not None: M.StorageEnergy.add(prev_soc >= final)

    M.NetworkCapacity = pyo.ConstraintList()
    for l in m.network_links:
        for y in years:
            lim=val(l.capacity,y,None)
            if lim is not None:
                for x in slices:
                    if x.period is None or x.period==y: M.NetworkCapacity.add(M.transmit[l.id,y,x.id] <= lim)

    M.Policy=pyo.ConstraintList()
    for c in m.constraints:
        y=c.period
        if y not in years: continue
        if c.type=="emission_cap": M.Policy.add(M.Emissions[y] <= c.value)
        elif c.type=="commodity_max":
            n=c.node_id or nodes[0]; M.Policy.add(sum(M.TechOutput[c.target_id,n,y,x.id] for x in slices if x.period is None or x.period==y) <= c.value)
        elif c.type=="commodity_min":
            n=c.node_id or nodes[0]; M.Policy.add(sum(M.TechOutput[c.target_id,n,y,x.id] for x in slices if x.period is None or x.period==y) >= c.value)
        elif c.type=="capacity_max": M.Policy.add(M.capacity[c.target_id,y] <= c.value)
        elif c.type=="resource_max":
            n=c.node_id or nodes[0]; M.Policy.add(sum(M.TechInput[c.target_id,n,y,x.id] for x in slices if x.period is None or x.period==y) <= c.value)
        elif c.type in ("min_share","max_share"):
            target=c.target_id; scope=c.scope.get("service_id")
            ks=[k for k in techs if k==target and (scope is None or td[k].service_id==scope)]
            allks=[k for k in techs if scope is None or td[k].service_id==scope]
            total=sum(M.activity[k,y,x.id] for k in allks for x in slices if x.period is None or x.period==y)
            share=sum(M.activity[k,y,x.id] for k in ks for x in slices if x.period is None or x.period==y)
            M.Policy.add(share >= c.value*total if c.type=="min_share" else share <= c.value*total)

    def obj(mm):
        total=0.0; r=m.meta.discount_rate; base=years[0]
        for t in m.technologies:
            for y in years:
                df=1/((1+r)**(y-base))
                total += df*(val(t.capex,y)*mm.new_capacity[t.id,y] + val(t.fixed_opex,y)*mm.capacity[t.id,y])
                for x in slices:
                    if x.period is None or x.period==y:
                        total += df*val(t.variable_opex,y)*mm.activity[t.id,y,x.id]*x.weight
        for c in commodities:
            for n in nodes:
                for y in years:
                    df=1/((1+r)**(y-base))
                    for x in slices:
                        if x.period is None or x.period==y:
                            total += df*(val(c.import_price,y,val(c.price,y,0))*mm.imports[c.id,n,y,x.id]-val(c.export_price,y,0)*mm.exports[c.id,n,y,x.id])*x.weight
        for l in m.network_links:
            for y in years:
                df=1/((1+r)**(y-base))
                for x in slices:
                    if x.period is None or x.period==y: total += df*val(l.variable_cost,y,0)*mm.transmit[l.id,y,x.id]*x.weight
        if m.meta.objective in ("min_cost","min_cost_with_emission_target"):
            for y in years:
                df=1/((1+r)**(y-base)); total += df*val(m.meta.carbon_price,y,0)*mm.Emissions[y]
            return total
        return sum(mm.Emissions[y] for y in years)
    M.OBJ=pyo.Objective(rule=obj,sense=pyo.minimize)
    return M

compile_lp=compile_model
