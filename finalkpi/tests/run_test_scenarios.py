"""Exercise material, quiet, sparse-history and access-denied cases."""

from run_full_demo import run


scenarios = [
    ("material event", dict(), "MATERIAL_CAUSE_UNVERIFIED"),
    ("early history", dict(target_date="2023-01-06"), "INSUFFICIENT_HISTORY"),
    ("new category", dict(target_date="2024-12-15", category="Beauty"), "INSUFFICIENT_HISTORY"),
    ("wrong region", dict(persona="regional_manager_north", region="South"), "ACCESS_DENIED"),
]

for name, overrides, expected in scenarios:
    result = run(**overrides)
    actual = result["verdict"]
    print(f"{name}: {actual}")
    assert actual == expected, f"{name}: expected {expected}, got {actual}"
