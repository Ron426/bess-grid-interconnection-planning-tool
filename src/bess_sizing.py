import math


def size_bess(required_mw: float, required_mwh: float,
              block_mw: float, block_mwh: float,
              n_plus_one: bool = True) -> dict:
    """Return a conceptual BESS block-sizing result."""

    if min(required_mw, required_mwh, block_mw, block_mwh) <= 0:
        raise ValueError("All power and energy values must be greater than zero.")

    blocks_for_power = math.ceil(required_mw / block_mw)
    blocks_for_energy = math.ceil(required_mwh / block_mwh)
    minimum_blocks = max(blocks_for_power, blocks_for_energy)

    installed_blocks = minimum_blocks + 1 if n_plus_one else minimum_blocks

    return {
        "blocks_for_power": blocks_for_power,
        "blocks_for_energy": blocks_for_energy,
        "minimum_blocks": minimum_blocks,
        "installed_blocks": installed_blocks,
        "installed_mw": installed_blocks * block_mw,
        "installed_mwh": installed_blocks * block_mwh,
        "reserve_blocks": installed_blocks - minimum_blocks,
        "n_plus_one": n_plus_one,
    }
