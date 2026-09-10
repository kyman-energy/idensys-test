import json
from pathlib import Path
import pandas as pd
import streamlit as st

from klimora_core.schema import Model
from klimora_core.validation import validate_model
from klimora_core.solver import solve_model
from klimora_core.results import extract_results

st.set_page_config(page_title="Klimora Playground", page_icon="⚡", layout="wide")

ROOT = Path(__file__).parent
SAMPLE = ROOT / "sample_industrial_heat.json"


def load_model(data):
    return Model.model_validate(data)


def model_json(model):
    return json.dumps(model.model_dump(), indent=2)


def reset_model(data):
    st.session_state.model_text = json.dumps(data, indent=2)
    st.session_state.last_result = None

if "model_text" not in st.session_state:
    reset_model(json.loads(SAMPLE.read_text()))
if "last_result" not in st.session_state:
    st.session_state.last_result = None

st.title("⚡ Klimora Industrial Energy Modeler")
st.caption("Real modeling playground — canonical model → validation → Pyomo/HiGHS → results")

with st.sidebar:
    st.header("Workspace")
    page = st.radio("Go to", ["Model", "Demand & Technologies", "Scenario", "Validate", "Optimize", "Results", "Raw Schema"])
    st.divider()
    if st.button("Load Industrial Heat Demo", use_container_width=True):
        reset_model(json.loads(SAMPLE.read_text()))
        st.rerun()
    uploaded = st.file_uploader("Load model JSON", type=["json"])
    if uploaded is not None:
        try:
            reset_model(json.load(uploaded))
            st.success("Model loaded")
            st.rerun()
        except Exception as e:
            st.error(f"Could not load JSON: {e}")

try:
    data = json.loads(st.session_state.model_text)
    model = load_model(data)
except Exception as e:
    model = None
    st.error(f"Model schema error: {e}")

if page == "Model":
    st.subheader("Model Setup")
    if model:
        a,b,c,d = st.columns(4)
        a.metric("Years", f"{model.meta.base_year}–{model.meta.end_year}")
        b.metric("Nodes", len(model.nodes))
        c.metric("Technologies", len(model.technologies))
        d.metric("Commodities", len(model.commodities))
        st.json({"name": model.meta.name, "region": model.meta.region, "objective": model.meta.objective, "time_slice_mode": model.meta.time_slice_mode})
        st.write("**Horizon**", model.meta.periods)
    st.info("Use Raw Schema for complete generic editing. The playground intentionally keeps the core schema flexible rather than hard-coding an industry.")

elif page == "Demand & Technologies":
    if not model: st.stop()
    st.subheader("Demand")
    for svc in model.services:
        st.markdown(f"### {svc.name} (`{svc.id}`)")
        vals = pd.DataFrame({"Year": list(svc.demand.keys()), "Demand": list(svc.demand.values())})
        if not vals.empty: st.line_chart(vals.set_index("Year"))
    st.subheader("Technologies")
    rows=[]
    for t in model.technologies:
        rows.append({"id":t.id,"name":t.name,"service":t.service_id,"CAPEX":t.capex.get(model.meta.base_year,0),"lifetime":t.lifetime,"availability":t.availability.get(model.meta.base_year,1)})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

elif page == "Scenario":
    if not model: st.stop()
    st.subheader("Scenario Manager")
    for s in model.scenarios:
        with st.expander(f"{s.name} ({s.id})"):
            st.write("Parent:", s.parent_id or "None")
            st.json([o.model_dump() for o in s.overrides])
    st.info("Scenario definitions are preserved in the canonical model. Advanced scenario editing is available in Raw Schema.")

elif page == "Validate":
    st.subheader("Model Validation")
    if model:
        errors = validate_model(model)
        if errors:
            st.error(f"{len(errors)} issue(s)")
            for e in errors: st.write(f"• {e}")
        else:
            st.success("Model is valid — 0 validation errors")

elif page == "Optimize":
    st.subheader("Real Optimization")
    if not model: st.stop()
    st.warning("This button executes the actual Klimora Pyomo model and HiGHS solver. No simulated results are generated.")
    try:
        import pyomo.environ as pyo
        available = bool(pyo.SolverFactory("highs").available(exception_flag=False))
    except Exception:
        available = False
    st.write("HiGHS available:", "✅ Yes" if available else "❌ No")
    if st.button("▶ Run Optimization", type="primary", disabled=not available):
        with st.spinner("Compiling and solving..."):
            try:
                pm, res = solve_model(model, "highs")
                st.session_state.last_result = extract_results(pm, res)
                st.success(f"Solver status: {res.solver.status}; termination: {res.solver.termination_condition}")
                st.rerun()
            except Exception as e:
                st.error(f"Optimization failed: {e}")

elif page == "Results":
    st.subheader("Results")
    r = st.session_state.last_result
    if not r:
        st.info("No optimization result in this session yet. Go to Optimize.")
    else:
        a,b,c = st.columns(3)
        a.metric("Status", r.get("status"))
        b.metric("Termination", r.get("termination_condition"))
        c.metric("Objective", f"{r.get('objective'):.4g}" if isinstance(r.get('objective'), (int,float)) else str(r.get('objective')))
        emissions = pd.DataFrame([{"Year":int(y),"Emissions":v} for y,v in r.get("emissions",{}).items() if v is not None]).sort_values("Year")
        if not emissions.empty:
            st.markdown("### Emissions")
            st.line_chart(emissions.set_index("Year"))
        st.markdown("### Capacity")
        cap_rows=[]
        for k,v in r.get("capacity",{}).items():
            parts=k.split("|")
            if len(parts)==2: cap_rows.append({"Technology":parts[0],"Year":int(parts[1]),"Capacity":v})
        cap=pd.DataFrame(cap_rows)
        if not cap.empty: st.line_chart(cap.pivot(index="Year",columns="Technology",values="Capacity").fillna(0))
        st.download_button("Download results JSON", json.dumps(r, indent=2), "klimora_results.json", "application/json")

elif page == "Raw Schema":
    st.subheader("Canonical Model Editor")
    st.caption("Edit the entire generic model definition. Save changes to the session, then validate and optimize.")
    edited = st.text_area("model.json", st.session_state.model_text, height=650)
    if st.button("Apply JSON", type="primary"):
        try:
            candidate = json.loads(edited)
            Model.model_validate(candidate)
            st.session_state.model_text = json.dumps(candidate, indent=2)
            st.session_state.last_result = None
            st.success("Model applied")
            st.rerun()
        except Exception as e:
            st.error(f"Invalid model: {e}")
    st.download_button("Download current model", st.session_state.model_text, "klimora_model.json", "application/json")
