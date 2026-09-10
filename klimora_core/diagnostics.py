from __future__ import annotations
from typing import Any
from .schema import Model
from .validation import validate_model


def validation_diagnostics(model: Model) -> dict[str, Any]:
    errors = validate_model(model)
    items=[]
    for msg in errors:
        severity='error'
        lower=msg.lower()
        if 'warning' in lower: severity='warning'
        # Best-effort machine-readable classification while preserving exact message.
        entity=None
        for prefix in ('technology','flow','stock','storage','constraint','service','commodity','node','scenario','time slice'):
            if lower.startswith(prefix): entity=prefix.replace(' ','_'); break
        items.append({'severity':severity,'code':'MODEL_VALIDATION','entity_type':entity,'message':msg})
    counts={'error':sum(x['severity']=='error' for x in items),'warning':sum(x['severity']=='warning' for x in items)}
    return {'valid': not errors, 'counts':counts, 'issues':items}


def compare_results(results_by_scenario: dict[str, dict[str, Any]]) -> dict[str, Any]:
    scenarios=list(results_by_scenario)
    objectives={s:results_by_scenario[s].get('objective') for s in scenarios}
    emissions={s:results_by_scenario[s].get('emissions',{}) for s in scenarios}
    years=sorted({str(y) for e in emissions.values() for y in e})
    emission_table=[]
    for y in years:
        row={'year':y}
        for s in scenarios: row[s]=emissions[s].get(y)
        emission_table.append(row)
    return {'scenarios':scenarios,'objectives':objectives,'emissions':emission_table}
