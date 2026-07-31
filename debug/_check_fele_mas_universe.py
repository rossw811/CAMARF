import sys, logging
sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)
from data import UniverseBuilder

builder = UniverseBuilder()
universe = builder.build(connect=False, fetch=False)
print("total assets in universe.assets:", len(universe.assets))
print("exclusion_set size:", len(universe.exclusion_set))
syms = {s for s, _ in universe.assets}
print("FELE in universe.assets:", "FELE" in syms)
print("MAS in universe.assets:", "MAS" in syms)
print("FELE in exclusion_set:", "FELE" in universe.exclusion_set)
print("MAS in exclusion_set:", "MAS" in universe.exclusion_set)
print("FELE_1h in universe.data:", "FELE_1h" in universe.data)
print("MAS_1h in universe.data:", "MAS_1h" in universe.data)
