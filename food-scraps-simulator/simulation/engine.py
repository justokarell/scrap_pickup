from datetime import datetime, timedelta
from .models import Scenario
from .state import SystemState, BinState, TruckState, SiteState
from .demand import arrivals
from .processing import advance_processing
from .policies import requested_locations
from .routing import execute_greedy_route

class SimulationEngine:
    def __init__(self, scenario: Scenario, seed: int=42, stochastic: bool=False):
        self.scenario=scenario; self.seed=seed; self.stochastic=stochastic
        self.state=SystemState(
            bins={x.id:BinState(inventory_lbs=x.initial_lbs) for x in scenario.locations},
            trucks={x.id:TruckState() for x in scenario.trucks},
            sites={x.id:SiteState() for x in scenario.processing_sites})
        self.state.total_source_lbs=sum(x.initial_lbs for x in scenario.locations)

    def _assert_mass_balance(self):
        r=self.state.mass_balance_residual()
        if abs(r)>1e-6: raise RuntimeError(f"Mass balance failed; residual={r}")

    def run(self):
        cfg=self.scenario.simulation; dt=cfg.state_step_hours
        steps=int(round(cfg.duration_days*24/dt)); start=datetime.fromisoformat(cfg.start_date)
        for step in range(steps):
            t1=(step+1)*dt
            for loc in self.scenario.locations:
                q=arrivals(loc,dt,self.seed,step,self.stochastic); b=self.state.bins[loc.id]
                b.arrivals_lbs+=q; self.state.total_source_lbs+=q
                raw=b.inventory_lbs+q; overflow=max(0.0,raw-loc.capacity_lbs)
                if overflow>1e-12:
                    b.overflow_lbs+=overflow; b.overflow_events+=1; self.state.total_overflow_lbs+=overflow
                b.inventory_lbs=min(loc.capacity_lbs,raw); b.max_inventory_lbs=max(b.max_inventory_lbs,b.inventory_lbs)
                b.inventory_sum+=b.inventory_lbs; b.samples+=1
            advance_processing(self.scenario,self.state,dt)
            now=start+timedelta(hours=t1)
            if now.hour==cfg.decision_epoch_hour and now.minute==0:
                execute_greedy_route(self.scenario,self.state,requested_locations(self.scenario,self.state,t1),t1)
            self._assert_mass_balance()
            if abs(t1%24.0)<1e-9:
                self.state.time_series.append({"hour":t1,"bins":{k:v.inventory_lbs for k,v in self.state.bins.items()},"processing":{k:v.inventory_lbs for k,v in self.state.sites.items()}})
        return self._result()

    def _result(self):
        miles=sum(x.miles for x in self.state.trucks.values()); labor=sum(x.labor_hours for x in self.state.trucks.values()); routes=sum(x.routes for x in self.state.trucks.values())
        tons=self.state.total_collected_lbs/2000.0
        summary={"total_arrivals_lbs":self.state.total_source_lbs,"total_collected_lbs":self.state.total_collected_lbs,"total_overflow_lbs":self.state.total_overflow_lbs,"overflow_events":sum(x.overflow_events for x in self.state.bins.values()),"capture_rate":self.state.total_collected_lbs/self.state.total_source_lbs if self.state.total_source_lbs>0 else 1.0,"routes_executed":routes,"miles_driven":miles,"labor_hours":labor,"operating_cost":self.state.operating_cost,"cost_per_ton":self.state.operating_cost/tons if tons>0 else None,"remaining_bin_inventory_lbs":sum(x.inventory_lbs for x in self.state.bins.values()),"processing_backlog_lbs":sum(x.inventory_lbs for x in self.state.sites.values()),"processed_lbs":self.state.total_processed_lbs}
        loc_lookup={x.id:x for x in self.scenario.locations}
        locations=[{"id":lid,"name":loc_lookup[lid].name,"arrivals_lbs":b.arrivals_lbs+loc_lookup[lid].initial_lbs,"collected_lbs":b.collected_lbs,"overflow_lbs":b.overflow_lbs,"overflow_events":b.overflow_events,"pickups":b.pickups,"average_inventory_lbs":b.inventory_sum/b.samples if b.samples else b.inventory_lbs,"peak_inventory_lbs":b.max_inventory_lbs,"service_level":1.0-(b.overflow_events/b.samples if b.samples else 0.0)} for lid,b in self.state.bins.items()]
        trucks=[{"id":tid,"routes":s.routes,"miles":s.miles,"labor_hours":s.labor_hours,"peak_load_lbs":s.max_load_lbs,"final_load_lbs":s.load_lbs} for tid,s in self.state.trucks.items()]
        sites=[{"id":sid,"received_lbs":s.received_lbs,"processed_lbs":s.processed_lbs,"backlog_lbs":s.inventory_lbs,"peak_backlog_lbs":s.max_inventory_lbs} for sid,s in self.state.sites.items()]
        return {"status":"complete","valid":True,"validation":{"mass_balance_passed":True,"mass_balance_residual_lbs":self.state.mass_balance_residual()},"summary":summary,"locations":locations,"trucks":trucks,"processing_sites":sites,"failures":[f.__dict__ for f in self.state.failures],"time_series":self.state.time_series}
