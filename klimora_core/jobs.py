from __future__ import annotations
import os, time, traceback
from datetime import datetime, timezone, timedelta
from typing import Any

TERMINAL = {'completed','blocked','failed','cancelled'}

class DurableJobWorker:
    def __init__(self, store, worker_id: str|None=None, poll_seconds: float=2.0, lease_seconds: int=300):
        self.store=store
        self.worker_id=worker_id or f"worker-{os.getpid()}"
        self.poll_seconds=poll_seconds
        self.lease_seconds=lease_seconds

    def process_one(self) -> bool:
        job=self.store.claim_next_job(self.worker_id, self.lease_seconds)
        if not job:
            return False
        run_id=job['run_id']; model_id=job['model_id']; scenario_id=job['scenario_id']
        try:
            self.store.update_run(run_id,'running',{'worker_id':self.worker_id,'started_at':datetime.now(timezone.utc).isoformat()})
            from .schema import Model
            from .scenario import apply_scenario
            from .solver import solve_model
            from .results import extract_results
            m=Model.model_validate(self.store.get_model(model_id))
            resolved=apply_scenario(m,scenario_id) if scenario_id not in ('','baseline','base') else m
            pm,res=solve_model(resolved, solver_name=os.getenv('KLIMORA_SOLVER','highs'))
            result=extract_results(pm,res)
            result['_run_meta']={'worker_id':self.worker_id,'completed_at':datetime.now(timezone.utc).isoformat()}
            self.store.update_run(run_id,'completed',result)
        except RuntimeError as e:
            self.store.update_run(run_id,'blocked',{'error':str(e),'worker_id':self.worker_id})
        except Exception as e:
            self.store.update_run(run_id,'failed',{'error':str(e),'worker_id':self.worker_id,'traceback':traceback.format_exc(limit=8)})
        finally:
            self.store.finish_job(run_id)
        return True

    def run_forever(self):
        while True:
            did=self.process_one()
            if not did:
                self.store.requeue_expired_jobs(self.lease_seconds)
                time.sleep(self.poll_seconds)
