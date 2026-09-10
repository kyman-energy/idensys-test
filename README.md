# Klimora Streamlit Playground v1

Hands-on browser prototype for the Klimora canonical industrial energy-system model.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Then open the displayed URL, usually `http://localhost:8501`.

## Streamlit Community Cloud

Push this folder to a GitHub repository. In Streamlit Community Cloud, create an app using `app.py` as the entrypoint. The dependencies are in `requirements.txt`.

The app calls the real `klimora_core` Pyomo compiler and HiGHS solver when available. It never fabricates optimization results.

## Notes

- The Raw Schema page is the most complete generic model editor.
- The Industrial Heat demo is deliberately small so it can be used as an acceptance test.
- For production Klimora, retain the FastAPI/worker/PostgreSQL architecture; Streamlit is the rapid validation playground.
