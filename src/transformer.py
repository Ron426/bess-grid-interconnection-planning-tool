from typing import Iterable


def required_mva(active_power_mw: float, power_factor: float) -> float:
    """Calculate apparent power requirement, S = P / PF."""
    if active_power_mw <= 0:
        raise ValueError("Active power must be greater than zero.")
    if not 0 < power_factor <= 1:
        raise ValueError("Power factor must be between 0 and 1.")
    return active_power_mw / power_factor


def loading_percent(required_mva_value: float, transformer_mva: float) -> float:
    if transformer_mva <= 0:
        raise ValueError("Transformer rating must be greater than zero.")
    return required_mva_value / transformer_mva * 100


def evaluate_transformers(active_power_mw: float,
                          power_factor: float,
                          growth_percent: float,
                          transformer_options: Iterable[float],
                          target_max_loading_percent: float = 85.0) -> list[dict]:
    """Evaluate transformer options at present load and after projected growth."""

    present_mva = required_mva(active_power_mw, power_factor)
    future_mw = active_power_mw * (1 + growth_percent / 100)
    future_mva = required_mva(future_mw, power_factor)

    results = []

    for rating in sorted(transformer_options):
        present_loading = loading_percent(present_mva, rating)
        future_loading = loading_percent(future_mva, rating)

        if future_loading <= target_max_loading_percent:
            status = "RECOMMENDED"
        elif future_loading <= 100:
            status = "ACCEPTABLE, LOW MARGIN"
        else:
            status = "REJECT"

        results.append({
            "rating_mva": rating,
            "present_loading_percent": present_loading,
            "future_loading_percent": future_loading,
            "status": status,
        })

    return results
