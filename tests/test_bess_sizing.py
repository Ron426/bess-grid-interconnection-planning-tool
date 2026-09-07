import pytest

from src.bess_sizing import size_bess


def test_baseline_bess_sizing_with_n_plus_one():
    """
    Baseline project case:
    50 MW / 100 MWh requirement
    5 MW / 10 MWh blocks
    N+1 enabled
    """
    result = size_bess(
        required_mw=50.0,
        required_mwh=100.0,
        block_mw=5.0,
        block_mwh=10.0,
        n_plus_one=True,
    )

    assert result["blocks_for_power"] == 10
    assert result["blocks_for_energy"] == 10
    assert result["minimum_blocks"] == 10
    assert result["installed_blocks"] == 11


def test_baseline_bess_sizing_without_n_plus_one():
    """
    Same baseline case, but without the redundant BESS block.
    """
    result = size_bess(
        required_mw=50.0,
        required_mwh=100.0,
        block_mw=5.0,
        block_mwh=10.0,
        n_plus_one=False,
    )

    assert result["minimum_blocks"] == 10
    assert result["installed_blocks"] == 10


def test_energy_requirement_controls_sizing():
    """
    Verify that the energy requirement controls sizing
    when it requires more blocks than the MW requirement.
    """
    result = size_bess(
        required_mw=40.0,
        required_mwh=100.0,
        block_mw=5.0,
        block_mwh=10.0,
        n_plus_one=True,
    )

    assert result["blocks_for_power"] == 8
    assert result["blocks_for_energy"] == 10
    assert result["minimum_blocks"] == 10
    assert result["installed_blocks"] == 11


def test_power_requirement_controls_sizing():
    """
    Verify that the power requirement controls sizing
    when it requires more blocks than the energy requirement.
    """
    result = size_bess(
        required_mw=50.0,
        required_mwh=80.0,
        block_mw=5.0,
        block_mwh=10.0,
        n_plus_one=True,
    )

    assert result["blocks_for_power"] == 10
    assert result["blocks_for_energy"] == 8
    assert result["minimum_blocks"] == 10
    assert result["installed_blocks"] == 11


def test_fractional_requirement_rounds_up():
    """
    Verify that partial block requirements are rounded upward.
    """
    result = size_bess(
        required_mw=51.0,
        required_mwh=101.0,
        block_mw=5.0,
        block_mwh=10.0,
        n_plus_one=True,
    )

    assert result["blocks_for_power"] == 11
    assert result["blocks_for_energy"] == 11
    assert result["minimum_blocks"] == 11
    assert result["installed_blocks"] == 12


@pytest.mark.parametrize(
    "required_mw, required_mwh, block_mw, block_mwh",
    [
        (0.0, 100.0, 5.0, 10.0),
        (-50.0, 100.0, 5.0, 10.0),
        (50.0, 0.0, 5.0, 10.0),
        (50.0, -100.0, 5.0, 10.0),
        (50.0, 100.0, 0.0, 10.0),
        (50.0, 100.0, 5.0, 0.0),
    ],
)
def test_invalid_inputs_raise_value_error(
    required_mw,
    required_mwh,
    block_mw,
    block_mwh,
):
    with pytest.raises(ValueError):
        size_bess(
            required_mw=required_mw,
            required_mwh=required_mwh,
            block_mw=block_mw,
            block_mwh=block_mwh,
        )