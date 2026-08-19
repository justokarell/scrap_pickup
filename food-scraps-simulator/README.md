# Food Scraps Simulator API

GitHub/Render-ready FastAPI service for a municipal food-scraps planning simulator.

**The bundled Stamford values are illustrative assumptions, not measured Stamford operating data.**

## Local run

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000/health` and `http://127.0.0.1:8000/docs`.

Test the included scenario:

```bash
curl -X POST http://127.0.0.1:8000/simulate \
  -H "Content-Type: application/json" \
  --data @reference_request.json
```

## Render

Push this entire folder to a GitHub repository. Create a Render Web Service from the repo. `render.yaml` contains the build/start configuration.

The production endpoint will be:

`https://YOUR-SERVICE.onrender.com/simulate`

Give that URL to Lovable.

## Included model

This self-contained implementation supports deterministic or stochastic demand, fixed/threshold/hybrid collection policies, bin accumulation and overflow, truck weight capacity, processing storage/throughput, a transparent greedy route/cost approximation, mass-balance validation, and API tests.

Replace the illustrative input values with Stamford-supplied or measured parameters as they become available.
