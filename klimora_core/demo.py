import json
from pathlib import Path
from .schema import Model
from .scenario import apply_scenario
from .solver import solve_model
from .results import extract_results

if __name__=="__main__":
    raw=json.loads((Path(__file__).parent/"sample_model.json").read_text())
    m=Model.model_validate(raw)
    scenario=raw["scenarios"][1]["id"]
    m2=apply_scenario(m,scenario)
    pm,res=solve_model(m2)
    print(extract_results(pm,res))
