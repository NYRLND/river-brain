"""River Brain: why is the Columbia River at Hayden Island rising or falling?

Pipeline: sources (fetch) -> qc -> inputs (hourly, aligned) -> features (causal)
-> model (fit offline / apply hourly) -> outputs (JSON for the static PWA).
"""

__version__ = "0.2.0"
