# Smoke test: the package imports and Kathryn is reachable in this environment.

import carolyne


def test_carolyne_imports():
    assert carolyne.__version__


def test_kathryn_available():
    import kathryn as k
    assert hasattr(k, "Module") and hasattr(k, "emit_verilog")
