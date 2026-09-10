from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import json
from .schema import Model
from .validation import validate_model
from .scenario import apply_scenario

class ModelStore:
    def __init__(self, root: str | Path = "data/models"):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
    def save(self, model_id: str, model: Model):
        p=self.root/f"{model_id}.json"; p.write_text(json.dumps(model.model_dump(), indent=2)); return p
    def load(self, model_id: str):
        p=self.root/f"{model_id}.json"
        if not p.exists(): raise FileNotFoundError(model_id)
        return Model.model_validate(json.loads(p.read_text()))
    def list(self): return sorted(p.stem for p in self.root.glob('*.json'))

def validate_or_raise(model):
    errors=validate_model(model)
    return {"valid": not errors, "errors": errors}

def model_summary(model):
    return {"name":model.meta.name,"base_year":model.meta.base_year,"end_year":model.meta.end_year,"periods":model.meta.periods,"nodes":len(model.nodes),"time_slices":len(model.time_slices),"commodities":len(model.commodities),"services":len(model.services),"technologies":len(model.technologies),"flows":len(model.flows),"storages":len(model.storages),"network_links":len(model.network_links),"constraints":len(model.constraints),"scenarios":len(model.scenarios)}
