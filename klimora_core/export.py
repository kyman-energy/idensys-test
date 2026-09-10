from __future__ import annotations
import csv, io, json
from typing import Any

def results_csv(results: dict[str, Any]) -> str:
    rows=[]
    for section in ('capacity','new_capacity','emissions','imports','exports'):
        values=results.get(section,{})
        if isinstance(values,dict):
            for key,value in values.items():
                rows.append({'section':section,'key':key,'value':value})
    buf=io.StringIO(); w=csv.DictWriter(buf,fieldnames=['section','key','value']); w.writeheader(); w.writerows(rows)
    return buf.getvalue()

def results_json(results: dict[str, Any]) -> str:
    return json.dumps(results, indent=2, default=str)

def result_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for section, values in results.items():
        if not isinstance(values, dict):
            continue
        for key, value in values.items():
            if isinstance(value, (dict, list)):
                continue
            rows.append({'section': section, 'key': key, 'value': value})
    return rows
