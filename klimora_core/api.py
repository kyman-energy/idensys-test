from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from .schema import Model
from .validation import validate_model
from .scenario import apply_scenario
from .service import model_summary
from .persistence import create_store
from .diagnostics import validation_diagnostics, compare_results
from .export import results_csv, results_json


VERSION='1.3.0'
app=FastAPI(title='Klimora Energy System Modeling API',version=VERSION)
import os
CORS_ORIGINS=[x.strip() for x in os.getenv('KLIMORA_CORS_ORIGINS','*').split(',') if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=CORS_ORIGINS,allow_credentials=('*' not in CORS_ORIGINS),allow_methods=['GET','POST','PUT','DELETE','OPTIONS'],allow_headers=['Content-Type','Authorization','X-Klimora-Key'])
store=create_store()

@app.get('/health')
def health(): return {'status':'ok','engine':'klimora','version':VERSION,'persistence':os.getenv('KLIMORA_DB_BACKEND','sqlite'),'solver':os.getenv('KLIMORA_SOLVER','highs')}

@app.get('/ready')
def ready():
    try: store.list_models(); return {'status':'ready','persistence':os.getenv('KLIMORA_DB_BACKEND','sqlite')}
    except Exception as e: raise HTTPException(503, f'Persistence unavailable: {e}')


@app.get('/schema/catalog')
def schema_catalog():
    return {
        'version': VERSION,
        'entities': ['nodes','time_slices','commodities','demand_drivers','services','technologies','flows','stock','storages','network_links','constraints','scenarios'],
        'objectives': ['min_cost','min_emissions','min_cost_with_emission_target'],
        'decisions': ['continuous','integer','binary'],
        'constraint_types': ['emission_cap','commodity_max','commodity_min','min_share','max_share','capacity_max','resource_max'],
    }

@app.post('/diagnostics/validate')
def validation_report(m:Model):
    return validation_diagnostics(m)

@app.get('/models/{model_id}/revisions')
def model_revisions(model_id:str):
    try: store.get_model(model_id)
    except FileNotFoundError: raise HTTPException(404,'Model not found')
    return {'model_id':model_id,'revisions':store.list_revisions(model_id)}

@app.get('/models/{model_id}/validation-report')
def saved_validation_report(model_id:str):
    try: m=Model.model_validate(store.get_model(model_id))
    except FileNotFoundError: raise HTTPException(404,'Model not found')
    return validation_diagnostics(m)

@app.get('/models/{model_id}/run-comparison')
def run_comparison(model_id:str):
    runs=store.list_runs(model_id)
    completed={}
    for r in runs:
        if r.get('status')=='completed' and r.get('payload') is not None:
            completed.setdefault(r['scenario_id'], r['payload'])
    return compare_results(completed)


@app.get('/schema/json')
def schema_json():
    return Model.model_json_schema()

@app.post('/models/{model_id}/clone')
def clone_model(model_id:str):
    try: payload=store.get_model(model_id)
    except FileNotFoundError: raise HTTPException(404,'Model not found')
    new_id='model_'+uuid4().hex[:10]
    payload=dict(payload); meta=dict(payload.get('meta',{})); meta['name']=meta.get('name','Untitled')+' (Copy)'; payload['meta']=meta
    store.save_model(new_id,payload)
    return {'id':new_id,**model_summary(Model.model_validate(payload))}

@app.post('/models/{model_id}/runs/{scenario_id}/retry', status_code=202)
def retry_run(model_id:str, scenario_id:str):
    try: store.get_model(model_id)
    except FileNotFoundError: raise HTTPException(404,'Model not found')
    run_id='run_'+uuid4().hex[:10]
    store.create_run(run_id,model_id,scenario_id,'queued')
    store.enqueue_job(run_id)
    return {'id':run_id,'model_id':model_id,'scenario_id':scenario_id,'status':'queued'}

@app.post('/runs/{run_id}/cancel')
def cancel_run(run_id:str):
    try: run=store.get_run(run_id)
    except FileNotFoundError: raise HTTPException(404,'Run not found')
    if run['status'] in ('completed','failed','blocked','cancelled'):
        return run
    store.update_run(run_id,'cancelled',{'error':'Cancelled by user'})
    try: store.finish_job(run_id)
    except Exception: pass
    return store.get_run(run_id)

@app.get('/runs/{run_id}/export.json')
def export_run_json(run_id:str):
    try: run=store.get_run(run_id)
    except FileNotFoundError: raise HTTPException(404,'Run not found')
    if not run.get('payload'): raise HTTPException(409,'Run has no results yet')
    return Response(content=results_json(run['payload']),media_type='application/json',headers={'Content-Disposition':f'attachment; filename={run_id}.json'})

@app.get('/runs/{run_id}/export.csv')
def export_run_csv(run_id:str):
    try: run=store.get_run(run_id)
    except FileNotFoundError: raise HTTPException(404,'Run not found')
    if not run.get('payload'): raise HTTPException(409,'Run has no results yet')
    return Response(content=results_csv(run['payload']),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename={run_id}.csv'})

@app.get('/models')
def models(): return {'models':store.list_models()}

@app.post('/models')
def create_model(m:Model):
    model_id='model_'+uuid4().hex[:10]; store.save_model(model_id,m.model_dump()); return {'id':model_id,**model_summary(m)}

@app.get('/models/{model_id}')
def get_model(model_id:str):
    try:return store.get_model(model_id)
    except FileNotFoundError: raise HTTPException(404,'Model not found')

@app.put('/models/{model_id}')
def update_model(model_id:str,m:Model):
    try: store.get_model(model_id)
    except FileNotFoundError: raise HTTPException(404,'Model not found')
    store.save_model(model_id,m.model_dump()); return {'id':model_id,**model_summary(m)}

@app.post('/models/{model_id}/validate')
def validate_saved(model_id:str):
    try:m=Model.model_validate(store.get_model(model_id))
    except FileNotFoundError: raise HTTPException(404,'Model not found')
    e=validate_model(m); return {'valid':not e,'errors':e}

@app.post('/validate')
def validate(m:Model):
    e=validate_model(m); return {'valid':not e,'errors':e}

@app.post('/scenario/{scenario_id}/resolve')
def resolve(scenario_id:str,m:Model):
    try:return apply_scenario(m,scenario_id).model_dump()
    except Exception as e: raise HTTPException(422,str(e))

@app.post('/compile-summary')
def compile_summary(m:Model):
    e=validate_model(m)
    if e: raise HTTPException(422,detail=e)
    try:
        from .compiler import compile_model
        pm=compile_model(m)
        sets={k:len(getattr(pm,k)) for k in ['Y','TS','K','S','C','N','V']}
        variables={k:len(getattr(pm,k)) for k in ['activity','capacity','new_capacity','vintage_capacity','retirement','imports','exports']}
        return {'sets':sets,'variables':variables,'constraints':{k:len(getattr(pm,k)) for k in ['DemandBalance','ServiceBalance','VintageDynamics','CapacityAggregation','ActivityCapacity','CommodityBalance']}}
    except Exception as e: raise HTTPException(500,str(e))

@app.get('/models/{model_id}/scenarios')
def model_scenarios(model_id:str):
    try: m=Model.model_validate(store.get_model(model_id))
    except FileNotFoundError: raise HTTPException(404,'Model not found')
    return {'scenarios':[s.model_dump() for s in m.scenarios]}

@app.delete('/models/{model_id}')
def delete_model(model_id:str):
    try: store.get_model(model_id)
    except FileNotFoundError: raise HTTPException(404,'Model not found')
    store.delete_model(model_id); return {'deleted':True,'id':model_id}

@app.get('/runs')
def runs(model_id:str|None=None): return {'runs':store.list_runs(model_id)}

@app.get('/runs/{run_id}')
def get_run(run_id:str):
    try:return store.get_run(run_id)
    except FileNotFoundError: raise HTTPException(404,'Run not found')

@app.get('/jobs/stats')
def job_stats():
    return {'queue':store.queue_stats()}

@app.get('/solver/status')
def solver_status():
    name=os.getenv('KLIMORA_SOLVER','highs')
    try:
        import pyomo.environ as pyo
        available=bool(pyo.SolverFactory(name).available(exception_flag=False))
        return {'solver':name,'pyomo':pyo.__version__,'available':available}
    except Exception as e:
        return {'solver':name,'pyomo':None,'available':False,'error':str(e)}

@app.post('/models/{model_id}/runs/{scenario_id}', status_code=202)
def run_model_async(model_id:str, scenario_id:str):
    try: store.get_model(model_id)
    except FileNotFoundError: raise HTTPException(404,'Model not found')
    run_id='run_'+uuid4().hex[:10]
    store.create_run(run_id,model_id,scenario_id,'queued')
    store.enqueue_job(run_id)
    return {'id':run_id,'model_id':model_id,'scenario_id':scenario_id,'status':'queued','poll_url':f'/runs/{run_id}'}

@app.post('/models/{model_id}/runs/{scenario_id}/start', status_code=202)
def run_model_start(model_id:str, scenario_id:str):
    return run_model_async(model_id,scenario_id)

@app.get('/models/{model_id}/runs-summary')
def runs_summary(model_id:str):
    try: store.get_model(model_id)
    except FileNotFoundError: raise HTTPException(404,'Model not found')
    runs=store.list_runs(model_id)
    return {'model_id':model_id,'runs':[r for r in runs if r.get('status') in ('completed','blocked','failed','queued','running')]}

@app.post('/solve/{scenario_id}')
def solve(scenario_id:str,m:Model):
    try:
        resolved=apply_scenario(m,scenario_id) if scenario_id not in ('','baseline','base') else m
        from .solver import solve_model
        from .results import extract_results
        pm,res=solve_model(resolved); return extract_results(pm,res)
    except RuntimeError as e: raise HTTPException(503,str(e))
    except Exception as e: raise HTTPException(422,str(e))
