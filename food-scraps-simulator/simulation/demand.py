import hashlib
import numpy as np
from .models import CollectionLocation

def arrivals(loc: CollectionLocation, dt_hours: float, seed: int, interval_index: int, stochastic: bool=False, cv: float=0.35) -> float:
    mean = max(0.0, loc.demand_lbs_per_day * dt_hours / 24.0)
    if not stochastic or mean == 0: return mean
    key = f"{seed}|{loc.id}|{interval_index}".encode()
    local_seed = int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
    rng = np.random.default_rng(local_seed)
    sigma2 = np.log(1.0 + cv * cv)
    return float(rng.lognormal(np.log(mean) - sigma2 / 2.0, np.sqrt(sigma2)))
