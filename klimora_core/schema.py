from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Flexible(BaseModel):
    model_config = ConfigDict(extra="allow")

class ModelMeta(BaseModel):
    name: str
    region: str = "Indonesia"
    base_year: int
    end_year: int
    periods: list[int]
    discount_rate: float = 0.08
    currency: str = "USD_2025"
    objective: Literal["min_cost", "min_emissions", "min_cost_with_emission_target"] = "min_cost"
    carbon_price: dict[int, float] = Field(default_factory=dict)
    time_slice_mode: Literal["annual", "custom"] = "annual"

class Node(Flexible):
    id: str
    type: str
    name: str
    parent: str | None = None

class TimeSlice(Flexible):
    id: str
    name: str
    weight: float = 1.0
    hours: float = 8760
    period: int | None = None
    season: str | None = None

class Commodity(Flexible):
    id: str
    name: str
    type: str
    unit: str
    price: dict[int, float] = Field(default_factory=dict)
    emission_carrier: bool = False
    max_available: dict[int, float] = Field(default_factory=dict)
    import_price: dict[int, float] = Field(default_factory=dict)
    export_price: dict[int, float] = Field(default_factory=dict)
    import_max: dict[int, float] = Field(default_factory=dict)
    export_max: dict[int, float] = Field(default_factory=dict)
    allow_import: bool = True
    allow_export: bool = False
    balance_mode: Literal["strict", "supply_only", "unbalanced"] = "strict"

class DemandDriver(Flexible):
    id: str
    name: str
    unit: str
    values: dict[int, float]

class EnergyService(Flexible):
    id: str
    name: str
    unit: str
    demand: dict[int, float] = Field(default_factory=dict)
    node_id: str | None = None
    demand_driver_id: str | None = None
    demand_driver_multiplier: dict[int, float] = Field(default_factory=dict)
    demand_base_year: int | None = None
    demand_base_value: float | None = None

class Technology(Flexible):
    id: str
    name: str
    service_id: str | None = None
    node_id: str | None = None
    lifetime: int = 20
    lead_time: int = 0
    capex: dict[int, float] = Field(default_factory=dict)
    fixed_opex: dict[int, float] = Field(default_factory=dict)
    variable_opex: dict[int, float] = Field(default_factory=dict)
    availability: dict[int, float] = Field(default_factory=dict)
    min_load: dict[int, float] = Field(default_factory=dict)
    decision: Literal["continuous", "integer", "binary"] = "continuous"
    unit_capacity: float = 1.0
    max_capacity: dict[int, float] = Field(default_factory=dict)
    time_slice_availability: dict[str, float] = Field(default_factory=dict)

class TechnologyFlow(Flexible):
    technology_id: str
    commodity_id: str
    direction: Literal["input", "output"]
    coefficient: dict[int, float]
    node_id: str | None = None
    time_slice_coefficient: dict[str, float] = Field(default_factory=dict)

class StockVintage(Flexible):
    technology_id: str
    vintage: int
    capacity: float
    lifetime: int
    utilization: dict[int, float] = Field(default_factory=dict)
    retireable: bool = True
    node_id: str | None = None

class Storage(Flexible):
    id: str
    name: str
    commodity_id: str
    node_id: str | None = None
    charge_efficiency: float = 1.0
    discharge_efficiency: float = 1.0
    power_capacity: dict[int, float] = Field(default_factory=dict)
    energy_capacity: dict[int, float] = Field(default_factory=dict)
    initial_soc: dict[int, float] = Field(default_factory=dict)
    final_soc_min: dict[int, float] = Field(default_factory=dict)
    standing_loss: dict[int, float] = Field(default_factory=dict)

class NetworkLink(Flexible):
    id: str
    commodity_id: str
    from_node: str
    to_node: str
    capacity: dict[int, float] = Field(default_factory=dict)
    variable_cost: dict[int, float] = Field(default_factory=dict)
    loss: dict[int, float] = Field(default_factory=dict)
    allow_bidirectional: bool = False

class Constraint(Flexible):
    id: str
    type: Literal["emission_cap", "commodity_max", "commodity_min", "min_share", "max_share", "capacity_max", "resource_max"]
    target_id: str
    period: int
    value: float
    scope: dict[str, str] = Field(default_factory=dict)
    node_id: str | None = None

class ScenarioOverride(Flexible):
    parameter: str
    values: dict[int, float | str]

class Scenario(Flexible):
    id: str
    name: str
    parent_id: str | None = None
    overrides: list[ScenarioOverride] = Field(default_factory=list)

class Model(BaseModel):
    meta: ModelMeta
    nodes: list[Node] = Field(default_factory=list)
    time_slices: list[TimeSlice] = Field(default_factory=list)
    commodities: list[Commodity] = Field(default_factory=list)
    demand_drivers: list[DemandDriver] = Field(default_factory=list)
    services: list[EnergyService] = Field(default_factory=list)
    technologies: list[Technology] = Field(default_factory=list)
    flows: list[TechnologyFlow] = Field(default_factory=list)
    stock: list[StockVintage] = Field(default_factory=list)
    storages: list[Storage] = Field(default_factory=list)
    network_links: list[NetworkLink] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)
