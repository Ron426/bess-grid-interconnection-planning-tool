import pytest

from src.transformer import (
    required_mva,
    loading_percent,
    evaluate_transformers,
)


def test_required_mva_baseline_case():
    """
    Baseline project case:
    50 MW at 0.95 power factor.
    """
    result = required_mva(
        active_power_mw=50.0,
        power_factor=0.95,
    )

    assert result == pytest.approx(52.63157895)


def test_required_mva_at_unity_power_factor():
    """
    At unity power factor, MW and MVA should be equal.
    """
    result = required_mva(
        active_power_mw=50.0,
        power_factor=1.0,
    )

    assert result == pytest.approx(50.0)


def test_required_mva_increases_as_power_factor_decreases():
    """
    Lower power factor should require greater apparent power.
    """
    high_pf = required_mva(
        active_power_mw=50.0,
        power_factor=0.95,
    )

    low_pf = required_mva(
        active_power_mw=50.0,
        power_factor=0.80,
    )

    assert low_pf > high_pf


@pytest.mark.parametrize(
    "active_power_mw",
    [
        0.0,
        -1.0,
        -50.0,
    ],
)
def test_required_mva_rejects_invalid_active_power(active_power_mw):
    with pytest.raises(ValueError):
        required_mva(
            active_power_mw=active_power_mw,
            power_factor=0.95,
        )


@pytest.mark.parametrize(
    "power_factor",
    [
        0.0,
        -0.5,
        1.01,
        2.0,
    ],
)
def test_required_mva_rejects_invalid_power_factor(power_factor):
    with pytest.raises(ValueError):
        required_mva(
            active_power_mw=50.0,
            power_factor=power_factor,
        )


def test_loading_percent_baseline_transformer():
    """
    50 MW at PF = 0.95 requires approximately 52.63 MVA.
    On a 75 MVA transformer, loading should be about 70.18%.
    """
    required = required_mva(
        active_power_mw=50.0,
        power_factor=0.95,
    )

    result = loading_percent(
        required_mva_value=required,
        transformer_mva=75.0,
    )

    assert result == pytest.approx(70.1754386)


def test_loading_percent_at_full_rating():
    result = loading_percent(
        required_mva_value=75.0,
        transformer_mva=75.0,
    )

    assert result == pytest.approx(100.0)


def test_loading_percent_can_exceed_100_percent():
    """
    The calculation should report overload rather than silently cap it.
    """
    result = loading_percent(
        required_mva_value=90.0,
        transformer_mva=75.0,
    )

    assert result == pytest.approx(120.0)


@pytest.mark.parametrize(
    "transformer_mva",
    [
        0.0,
        -1.0,
        -75.0,
    ],
)
def test_loading_percent_rejects_invalid_transformer_rating(transformer_mva):
    with pytest.raises(ValueError):
        loading_percent(
            required_mva_value=50.0,
            transformer_mva=transformer_mva,
        )

def test_evaluate_transformers_baseline_growth_case():
    """
    Baseline planning case:
    50 MW at 0.95 PF with 15% future growth.

    Future export = 57.5 MW
    Future apparent power ≈ 60.53 MVA.
    """
    results = evaluate_transformers(
        active_power_mw=50.0,
        power_factor=0.95,
        growth_percent=15.0,
        transformer_options=[60.0, 75.0, 100.0],
        target_max_loading_percent=85.0,
    )

    assert len(results) == 3

    transformer_60 = results[0]
    transformer_75 = results[1]
    transformer_100 = results[2]

    assert transformer_60["rating_mva"] == 60.0
    assert transformer_60["status"] == "REJECT"

    assert transformer_75["rating_mva"] == 75.0
    assert transformer_75["future_loading_percent"] == pytest.approx(
        80.701754,
        rel=1e-5,
    )
    assert transformer_75["status"] == "RECOMMENDED"

    assert transformer_100["rating_mva"] == 100.0
    assert transformer_100["status"] == "RECOMMENDED"


def test_transformer_low_margin_classification():
    """
    At 30% growth, the 75 MVA transformer remains below
    100% loading but exceeds the 85% planning target.
    """
    results = evaluate_transformers(
        active_power_mw=50.0,
        power_factor=0.95,
        growth_percent=30.0,
        transformer_options=[60.0, 75.0, 100.0],
        target_max_loading_percent=85.0,
    )

    transformer_60 = results[0]
    transformer_75 = results[1]
    transformer_100 = results[2]

    assert transformer_60["status"] == "REJECT"

    assert transformer_75["future_loading_percent"] == pytest.approx(
        91.228070,
        rel=1e-5,
    )
    assert transformer_75["status"] == "ACCEPTABLE, LOW MARGIN"

    assert transformer_100["status"] == "RECOMMENDED"


def test_evaluate_transformers_reports_present_and_future_loading():
    """
    Future loading should increase when positive growth is applied.
    """
    results = evaluate_transformers(
        active_power_mw=50.0,
        power_factor=0.95,
        growth_percent=15.0,
        transformer_options=[75.0],
    )

    result = results[0]

    assert result["present_loading_percent"] == pytest.approx(
        70.1754386
    )

    assert result["future_loading_percent"] == pytest.approx(
        80.7017544
    )

    assert (
        result["future_loading_percent"]
        > result["present_loading_percent"]
    )


def test_evaluate_transformers_sorts_transformer_options():
    """
    Transformer results should be returned from smallest
    to largest MVA rating regardless of input order.
    """
    results = evaluate_transformers(
        active_power_mw=50.0,
        power_factor=0.95,
        growth_percent=15.0,
        transformer_options=[100.0, 60.0, 75.0],
    )

    ratings = [result["rating_mva"] for result in results]

    assert ratings == [60.0, 75.0, 100.0]


def test_custom_loading_target_changes_classification():
    """
    A stricter planning target should change whether a
    transformer is considered recommended.
    """
    results = evaluate_transformers(
        active_power_mw=50.0,
        power_factor=0.95,
        growth_percent=15.0,
        transformer_options=[75.0, 100.0],
        target_max_loading_percent=70.0,
    )

    transformer_75 = results[0]
    transformer_100 = results[1]

    assert transformer_75["status"] == "ACCEPTABLE, LOW MARGIN"
    assert transformer_100["status"] == "RECOMMENDED"


def test_empty_transformer_options_returns_empty_list():
    results = evaluate_transformers(
        active_power_mw=50.0,
        power_factor=0.95,
        growth_percent=15.0,
        transformer_options=[],
    )

    assert results == []


def test_invalid_transformer_option_is_rejected():
    """
    Invalid transformer ratings should propagate the validation
    performed by loading_percent().
    """
    with pytest.raises(ValueError):
        evaluate_transformers(
            active_power_mw=50.0,
            power_factor=0.95,
            growth_percent=15.0,
            transformer_options=[0.0, 75.0],
        )