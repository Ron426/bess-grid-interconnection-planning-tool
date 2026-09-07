import math


def reactive_power_mvar(active_power_mw: float, power_factor: float) -> float:
    """
    Calculate reactive power magnitude in MVAr.

    Q = P * tan(cos^-1(PF))
    """
    if active_power_mw < 0:
        raise ValueError("Active power cannot be negative.")

    if not 0 < power_factor <= 1:
        raise ValueError("Power factor must be between 0 and 1.")

    angle_rad = math.acos(power_factor)

    return active_power_mw * math.tan(angle_rad)


def three_phase_current_a(apparent_power_mva: float, voltage_kv: float) -> float:
    """
    Calculate three-phase line current.

    I = S / (sqrt(3) * V)
    """

    if apparent_power_mva < 0:
        raise ValueError("Apparent power cannot be negative.")

    if voltage_kv <= 0:
        raise ValueError("Voltage must be greater than zero.")

    apparent_power_va = apparent_power_mva * 1_000_000
    voltage_v = voltage_kv * 1_000

    return apparent_power_va / (math.sqrt(3) * voltage_v)


def transformer_rated_current_a(transformer_mva: float, voltage_kv: float) -> float:
    """
    Calculate transformer full-load rated current
    at a specified voltage level.
    """

    if transformer_mva <= 0:
        raise ValueError("Transformer rating must be greater than zero.")

    if voltage_kv <= 0:
        raise ValueError("Voltage must be greater than zero.")

    transformer_va = transformer_mva * 1_000_000
    voltage_v = voltage_kv * 1_000

    return transformer_va / (math.sqrt(3) * voltage_v)


def current_utilization_percent(
    operating_current_a: float,
    rated_current_a: float
) -> float:
    """
    Calculate current utilization as a percentage
    of equipment rated current.
    """

    if rated_current_a <= 0:
        raise ValueError("Rated current must be greater than zero.")

    return operating_current_a / rated_current_a * 100