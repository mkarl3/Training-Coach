import os
import sys

# slice3 depends on the metrics package (the AthleteProfile lives there).
SLICE3 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLICE1 = os.path.join(os.path.dirname(SLICE3), "slice1")
for p in (SLICE3, SLICE1):
    if p not in sys.path:
        sys.path.insert(0, p)
