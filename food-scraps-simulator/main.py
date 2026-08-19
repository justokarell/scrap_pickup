import os, uuid
from typing import Any, Literal
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from simulation.api import simulate
from simulation.models import Scenario

app=FastAPI(title="Food Scraps Simulation API",version="0.1.0")
orig=os.getenv("ALLOWED_ORIGINS","*")
origins=["*"] if orig=="*" else [x.strip() for x in orig.split(",") if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=False,allow_methods=["GET","POST","OPTIONS"],allow_headers=["*"])

class SimulationConfigRequest(BaseModel):
    seed:int=42
    model_version:str="0.1.0"
    detail_level:Literal["summary","percentiles","full_trace"]="summary"
    stochastic:bool=False
class SimulationRequest(BaseModel):
    scenario:dict[str,Any]
    simulation_config:SimulationConfigRequest=Field(default_factory=SimulationConfigRequest)

@app.get("/")
def root(): return {"service":"food-scraps-simulation-api","version":"0.1.0","status":"ok","docs":"/docs"}
@app.get("/health")
def health(): return {"status":"ok","model_version":"0.1.0"}
@app.post("/simulate")
def simulate_endpoint(request:SimulationRequest):
    try:
        scenario=Scenario.from_dict(request.scenario)
        result=simulate(scenario,request.simulation_config.seed,request.simulation_config.stochastic)
        result.update({"run_id":str(uuid.uuid4()),"model_version":request.simulation_config.model_version,"scenario_schema_version":scenario.schema_version,"seed":request.simulation_config.seed})
        return result
    except ValueError as e: raise HTTPException(status_code=422,detail=str(e)) from e
    except Exception as e: raise HTTPException(status_code=500,detail=f"Simulation failed: {type(e).__name__}: {e}") from e
