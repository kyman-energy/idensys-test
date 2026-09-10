from __future__ import annotations
import json, sqlite3, os
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

class SQLiteStore:
    def __init__(self, path: str|Path = 'data/klimora.db'):
        self.path=Path(path); self.path.parent.mkdir(parents=True, exist_ok=True); self._init()
    def _conn(self):
        c=sqlite3.connect(self.path); c.row_factory=sqlite3.Row; return c
    def _init(self):
        with self._conn() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS models (id TEXT PRIMARY KEY, name TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL); CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, model_id TEXT NOT NULL, scenario_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL); CREATE INDEX IF NOT EXISTS idx_runs_model ON runs(model_id, created_at DESC); CREATE TABLE IF NOT EXISTS model_revisions (id INTEGER PRIMARY KEY AUTOINCREMENT, model_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL); CREATE INDEX IF NOT EXISTS idx_model_revisions ON model_revisions(model_id, id DESC); CREATE TABLE IF NOT EXISTS jobs (run_id TEXT PRIMARY KEY, status TEXT NOT NULL, worker_id TEXT, attempts INTEGER NOT NULL DEFAULT 0, available_at TEXT NOT NULL, lease_until TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL); CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(status, available_at);''')
    def save_model(self, model_id, payload):
        now=datetime.now(timezone.utc).isoformat(); name=payload.get('meta',{}).get('name','Untitled')
        with self._conn() as c:
            c.execute('INSERT INTO models VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,payload=excluded.payload,updated_at=excluded.updated_at',(model_id,name,json.dumps(payload),now))
            c.execute('INSERT INTO model_revisions(model_id,payload,created_at) VALUES(?,?,?)',(model_id,json.dumps(payload),now))
    def list_revisions(self, model_id):
        with self._conn() as c:
            rows=c.execute('SELECT id,model_id,created_at FROM model_revisions WHERE model_id=? ORDER BY id DESC',(model_id,)).fetchall()
        return [dict(r) for r in rows]

    def delete_model(self, model_id):
        with self._conn() as c:
            run_ids=[r[0] for r in c.execute('SELECT id FROM runs WHERE model_id=?',(model_id,)).fetchall()]
            if run_ids: c.executemany('DELETE FROM jobs WHERE run_id=?', [(rid,) for rid in run_ids])
            c.execute('DELETE FROM runs WHERE model_id=?',(model_id,)); c.execute('DELETE FROM model_revisions WHERE model_id=?',(model_id,)); c.execute('DELETE FROM models WHERE id=?',(model_id,))
    def get_model(self, model_id):
        with self._conn() as c: r=c.execute('SELECT payload FROM models WHERE id=?',(model_id,)).fetchone()
        if not r: raise FileNotFoundError(model_id)
        return json.loads(r['payload'])
    def list_models(self):
        with self._conn() as c: return [dict(r) for r in c.execute('SELECT id,name,updated_at FROM models ORDER BY updated_at DESC')]
    def create_run(self, run_id, model_id, scenario_id, status='queued', payload=None):
        now=datetime.now(timezone.utc).isoformat()
        with self._conn() as c: c.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)',(run_id,model_id,scenario_id,status,json.dumps(payload) if payload is not None else None,now,now))
    def update_run(self, run_id, status, payload=None):
        now=datetime.now(timezone.utc).isoformat()
        with self._conn() as c: c.execute('UPDATE runs SET status=?,payload=?,updated_at=? WHERE id=?',(status,json.dumps(payload) if payload is not None else None,now,run_id))
    def patch_run(self, run_id, **fields):
        allowed={'status','payload'}; fields={k:v for k,v in fields.items() if k in allowed}
        if not fields:return
        now=datetime.now(timezone.utc).isoformat(); sets=[]; vals=[]
        for k,v in fields.items(): sets.append(k+'=?'); vals.append(json.dumps(v) if k=='payload' and v is not None else v)
        vals += [now,run_id]
        with self._conn() as c: c.execute('UPDATE runs SET '+','.join(sets)+',updated_at=? WHERE id=?',vals)
    def get_run(self, run_id):
        with self._conn() as c: r=c.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
        if not r: raise FileNotFoundError(run_id)
        d=dict(r); d['payload']=json.loads(d['payload']) if d['payload'] else None; return d
    def list_runs(self, model_id=None):
        with self._conn() as c:
            rows=c.execute('SELECT * FROM runs WHERE model_id=? ORDER BY created_at DESC',(model_id,)).fetchall() if model_id else c.execute('SELECT * FROM runs ORDER BY created_at DESC').fetchall()
        out=[]
        for r in rows:
            d=dict(r); d['payload']=json.loads(d['payload']) if d['payload'] else None; out.append(d)
        return out


    def enqueue_job(self, run_id):
        now=datetime.now(timezone.utc).isoformat()
        with self._conn() as c: c.execute('INSERT OR REPLACE INTO jobs(run_id,status,worker_id,attempts,available_at,lease_until,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(run_id,'queued',None,0,now,None,now,now))
    def claim_next_job(self, worker_id, lease_seconds):
        now=datetime.now(timezone.utc); lease=(now+__import__('datetime').timedelta(seconds=lease_seconds)).isoformat()
        with self._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            r=c.execute("SELECT j.run_id,r.model_id,r.scenario_id FROM jobs j JOIN runs r ON r.id=j.run_id WHERE j.status='queued' AND r.status='queued' AND j.available_at<=? ORDER BY j.created_at LIMIT 1",(now.isoformat(),)).fetchone()
            if not r: c.rollback(); return None
            c.execute("UPDATE jobs SET status='running',worker_id=?,attempts=attempts+1,lease_until=?,updated_at=? WHERE run_id=?",(worker_id,lease,now.isoformat(),r['run_id']))
            return dict(r)
    def finish_job(self, run_id):
        now=datetime.now(timezone.utc).isoformat()
        with self._conn() as c: c.execute("UPDATE jobs SET status='done',lease_until=NULL,updated_at=? WHERE run_id=?",(now,run_id))
    def requeue_expired_jobs(self, lease_seconds=300):
        now=datetime.now(timezone.utc).isoformat()
        with self._conn() as c: c.execute("UPDATE jobs SET status='queued',worker_id=NULL,lease_until=NULL,available_at=?,updated_at=? WHERE status='running' AND lease_until IS NOT NULL AND lease_until<?",(now,now,now))
    def queue_stats(self):
        with self._conn() as c: rows=c.execute('SELECT status,COUNT(*) n FROM jobs GROUP BY status').fetchall()
        return {r['status']:r['n'] for r in rows}

class PostgresStore:
    """PostgreSQL persistence implementation; requires psycopg 3 at runtime."""
    def __init__(self, dsn: str):
        try: import psycopg
        except ImportError as exc: raise RuntimeError('PostgreSQL backend requires psycopg[binary]>=3.2') from exc
        self.psycopg=psycopg; self.dsn=dsn; self._init()
    def _conn(self): return self.psycopg.connect(self.dsn)
    def _init(self):
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS models (id TEXT PRIMARY KEY, name TEXT NOT NULL, payload JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, model_id TEXT NOT NULL, scenario_id TEXT NOT NULL, status TEXT NOT NULL, payload JSONB, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_runs_model ON runs(model_id, created_at DESC)")
            c.execute("CREATE TABLE IF NOT EXISTS model_revisions (id BIGSERIAL PRIMARY KEY, model_id TEXT NOT NULL, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_model_revisions ON model_revisions(model_id, id DESC)")
            c.execute("CREATE TABLE IF NOT EXISTS jobs (run_id TEXT PRIMARY KEY, status TEXT NOT NULL, worker_id TEXT, attempts INTEGER NOT NULL DEFAULT 0, available_at TIMESTAMPTZ NOT NULL, lease_until TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(status, available_at)")
    def save_model(self, model_id,payload):
        now=datetime.now(timezone.utc); name=payload.get('meta',{}).get('name','Untitled')
        with self._conn() as c:
            c.execute("INSERT INTO models VALUES(%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET name=EXCLUDED.name,payload=EXCLUDED.payload,updated_at=EXCLUDED.updated_at",(model_id,name,json.dumps(payload),now))
            c.execute("INSERT INTO model_revisions(model_id,payload,created_at) VALUES(%s,%s,%s)",(model_id,json.dumps(payload),now))
    def list_revisions(self, model_id):
        with self._conn() as c:
            rows=c.execute('SELECT id,model_id,created_at FROM model_revisions WHERE model_id=%s ORDER BY id DESC',(model_id,)).fetchall()
        return [{'id':r[0],'model_id':r[1],'created_at':r[2].isoformat()} for r in rows]

    def delete_model(self,model_id):
        with self._conn() as c:
            run_ids=[r[0] for r in c.execute('SELECT id FROM runs WHERE model_id=%s',(model_id,)).fetchall()]
            if run_ids: c.executemany('DELETE FROM jobs WHERE run_id=%s', [(rid,) for rid in run_ids])
            c.execute('DELETE FROM runs WHERE model_id=%s',(model_id,)); c.execute('DELETE FROM model_revisions WHERE model_id=%s',(model_id,)); c.execute('DELETE FROM models WHERE id=%s',(model_id,))
    def get_model(self,model_id):
        with self._conn() as c: r=c.execute('SELECT payload FROM models WHERE id=%s',(model_id,)).fetchone()
        if not r: raise FileNotFoundError(model_id)
        return r[0] if isinstance(r[0],dict) else json.loads(r[0])
    def list_models(self):
        with self._conn() as c: rows=c.execute('SELECT id,name,updated_at FROM models ORDER BY updated_at DESC').fetchall()
        return [{'id':r[0],'name':r[1],'updated_at':r[2].isoformat()} for r in rows]
    def create_run(self,run_id,model_id,scenario_id,status='queued',payload=None):
        now=datetime.now(timezone.utc)
        with self._conn() as c: c.execute('INSERT INTO runs VALUES(%s,%s,%s,%s,%s,%s,%s)',(run_id,model_id,scenario_id,status,json.dumps(payload) if payload is not None else None,now,now))
    def update_run(self,run_id,status,payload=None):
        with self._conn() as c: c.execute('UPDATE runs SET status=%s,payload=%s,updated_at=%s WHERE id=%s',(status,json.dumps(payload) if payload is not None else None,datetime.now(timezone.utc),run_id))
    def patch_run(self,run_id,**fields):
        current=self.get_run(run_id)
        status=fields.get('status', current['status'])
        payload=fields.get('payload', current.get('payload'))
        self.update_run(run_id,status,payload)
    def get_run(self,run_id):
        with self._conn() as c: r=c.execute('SELECT id,model_id,scenario_id,status,payload,created_at,updated_at FROM runs WHERE id=%s',(run_id,)).fetchone()
        if not r: raise FileNotFoundError(run_id)
        d=dict(zip(['id','model_id','scenario_id','status','payload','created_at','updated_at'],r)); return d
    def list_runs(self,model_id=None):
        with self._conn() as c:
            q='SELECT id,model_id,scenario_id,status,payload,created_at,updated_at FROM runs'; args=[]
            if model_id:q+=' WHERE model_id=%s';args=[model_id]
            q+=' ORDER BY created_at DESC'; rows=c.execute(q,args).fetchall()
        return [dict(zip(['id','model_id','scenario_id','status','payload','created_at','updated_at'],r)) for r in rows]


    def enqueue_job(self, run_id):
        now=datetime.now(timezone.utc)
        with self._conn() as c: c.execute('INSERT INTO jobs(run_id,status,worker_id,attempts,available_at,lease_until,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(run_id) DO UPDATE SET status=EXCLUDED.status,available_at=EXCLUDED.available_at,updated_at=EXCLUDED.updated_at', (run_id,'queued',None,0,now,None,now,now))
    def claim_next_job(self, worker_id, lease_seconds):
        from datetime import timedelta
        now=datetime.now(timezone.utc); lease=now+timedelta(seconds=lease_seconds)
        with self._conn() as c:
            row=c.execute("SELECT j.run_id,r.model_id,r.scenario_id FROM jobs j JOIN runs r ON r.id=j.run_id WHERE j.status='queued' AND j.available_at<=%s ORDER BY j.created_at FOR UPDATE SKIP LOCKED LIMIT 1",(now,)).fetchone()
            if not row:return None
            c.execute("UPDATE jobs SET status='running',worker_id=%s,attempts=attempts+1,lease_until=%s,updated_at=%s WHERE run_id=%s",(worker_id,lease,now,row[0]))
            return {'run_id':row[0],'model_id':row[1],'scenario_id':row[2]}
    def finish_job(self, run_id):
        with self._conn() as c: c.execute("UPDATE jobs SET status='done',lease_until=NULL,updated_at=%s WHERE run_id=%s",(datetime.now(timezone.utc),run_id))
    def requeue_expired_jobs(self, lease_seconds=300):
        now=datetime.now(timezone.utc)
        with self._conn() as c: c.execute("UPDATE jobs SET status='queued',worker_id=NULL,lease_until=NULL,available_at=%s,updated_at=%s WHERE status='running' AND lease_until IS NOT NULL AND lease_until<%s",(now,now,now))
    def queue_stats(self):
        with self._conn() as c: rows=c.execute('SELECT status,COUNT(*) FROM jobs GROUP BY status').fetchall()
        return {r[0]:r[1] for r in rows}

def create_store():
    if os.getenv('KLIMORA_DB_BACKEND','sqlite').lower()=='postgres': return PostgresStore(os.environ['KLIMORA_DATABASE_URL'])
    return SQLiteStore(os.getenv('KLIMORA_DB_PATH',str(Path(__file__).resolve().parent.parent/'data'/'klimora.db')))
