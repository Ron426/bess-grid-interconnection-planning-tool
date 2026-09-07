import src.design_engine as design_engine


def test_analyze_design_options_returns_all_candidates(monkeypatch):
    """
    Every candidate design should be evaluated and returned.
    """

    def fake_evaluate_design_option(**kwargs):
        return {
            "option": kwargs["option_name"],
            "installed_blocks": kwargs["installed_blocks"],
            "transformer_mva": kwargs["transformer_mva"],
            "future_ready_pass": True,
            "future_n1_ready_pass": True,
        }

    monkeypatch.setattr(
        design_engine,
        "evaluate_design_option",
        fake_evaluate_design_option,
    )

    design_options = [
        {
            "option": "Option A",
            "installed_blocks": 10,
            "transformer_mva": 60.0,
        },
        {
            "option": "Option B",
            "installed_blocks": 11,
            "transformer_mva": 75.0,
        },
        {
            "option": "Option C",
            "installed_blocks": 12,
            "transformer_mva": 75.0,
        },
    ]

    results, recommendations = design_engine.analyze_design_options(
        design_options
    )

    assert len(results) == 3
    assert [result["option"] for result in results] == [
        "Option A",
        "Option B",
        "Option C",
    ]


def test_selects_smallest_future_ready_design(monkeypatch):
    """
    The minimum future-ready design should use the fewest
    installed blocks among candidates that pass.
    """

    passing_options = {
        "Option A": False,
        "Option B": True,
        "Option C": True,
    }

    def fake_evaluate_design_option(**kwargs):
        name = kwargs["option_name"]

        return {
            "option": name,
            "installed_blocks": kwargs["installed_blocks"],
            "transformer_mva": kwargs["transformer_mva"],
            "future_ready_pass": passing_options[name],
            "future_n1_ready_pass": False,
        }

    monkeypatch.setattr(
        design_engine,
        "evaluate_design_option",
        fake_evaluate_design_option,
    )

    design_options = [
        {
            "option": "Option A",
            "installed_blocks": 10,
            "transformer_mva": 60.0,
        },
        {
            "option": "Option B",
            "installed_blocks": 11,
            "transformer_mva": 75.0,
        },
        {
            "option": "Option C",
            "installed_blocks": 12,
            "transformer_mva": 75.0,
        },
    ]

    _, recommendations = design_engine.analyze_design_options(
        design_options
    )

    selected = recommendations["minimum_future_ready"]

    assert selected is not None
    assert selected["option"] == "Option B"
    assert selected["installed_blocks"] == 11
    assert selected["transformer_mva"] == 75.0


def test_selects_smallest_future_n1_design(monkeypatch):
    """
    Future N+1 selection should independently choose the
    smallest candidate that satisfies N+1 requirements.
    """

    n1_status = {
        "Option A": False,
        "Option B": False,
        "Option C": True,
        "Option D": True,
    }

    def fake_evaluate_design_option(**kwargs):
        name = kwargs["option_name"]

        return {
            "option": name,
            "installed_blocks": kwargs["installed_blocks"],
            "transformer_mva": kwargs["transformer_mva"],
            "future_ready_pass": True,
            "future_n1_ready_pass": n1_status[name],
        }

    monkeypatch.setattr(
        design_engine,
        "evaluate_design_option",
        fake_evaluate_design_option,
    )

    design_options = [
        {
            "option": "Option A",
            "installed_blocks": 10,
            "transformer_mva": 60.0,
        },
        {
            "option": "Option B",
            "installed_blocks": 11,
            "transformer_mva": 75.0,
        },
        {
            "option": "Option C",
            "installed_blocks": 12,
            "transformer_mva": 75.0,
        },
        {
            "option": "Option D",
            "installed_blocks": 13,
            "transformer_mva": 100.0,
        },
    ]

    _, recommendations = design_engine.analyze_design_options(
        design_options
    )

    selected = recommendations["minimum_future_n1"]

    assert selected is not None
    assert selected["option"] == "Option C"
    assert selected["installed_blocks"] == 12


def test_transformer_rating_breaks_block_count_tie(monkeypatch):
    """
    If two passing designs use the same number of BESS blocks,
    the smaller transformer should be preferred.
    """

    def fake_evaluate_design_option(**kwargs):
        return {
            "option": kwargs["option_name"],
            "installed_blocks": kwargs["installed_blocks"],
            "transformer_mva": kwargs["transformer_mva"],
            "future_ready_pass": True,
            "future_n1_ready_pass": True,
        }

    monkeypatch.setattr(
        design_engine,
        "evaluate_design_option",
        fake_evaluate_design_option,
    )

    design_options = [
        {
            "option": "Option Large Transformer",
            "installed_blocks": 13,
            "transformer_mva": 100.0,
        },
        {
            "option": "Option Small Transformer",
            "installed_blocks": 13,
            "transformer_mva": 75.0,
        },
    ]

    _, recommendations = design_engine.analyze_design_options(
        design_options
    )

    future_selected = recommendations["minimum_future_ready"]
    n1_selected = recommendations["minimum_future_n1"]

    assert future_selected["option"] == "Option Small Transformer"
    assert n1_selected["option"] == "Option Small Transformer"


def test_returns_none_when_no_future_ready_candidate(monkeypatch):
    """
    If no design satisfies future-ready criteria,
    the recommendation should be None.
    """

    def fake_evaluate_design_option(**kwargs):
        return {
            "option": kwargs["option_name"],
            "installed_blocks": kwargs["installed_blocks"],
            "transformer_mva": kwargs["transformer_mva"],
            "future_ready_pass": False,
            "future_n1_ready_pass": False,
        }

    monkeypatch.setattr(
        design_engine,
        "evaluate_design_option",
        fake_evaluate_design_option,
    )

    design_options = [
        {
            "option": "Option A",
            "installed_blocks": 10,
            "transformer_mva": 60.0,
        },
        {
            "option": "Option B",
            "installed_blocks": 11,
            "transformer_mva": 75.0,
        },
    ]

    _, recommendations = design_engine.analyze_design_options(
        design_options
    )

    assert recommendations["minimum_future_ready"] is None
    assert recommendations["minimum_future_n1"] is None


def test_future_ready_and_n1_recommendations_can_differ(monkeypatch):
    """
    A design may satisfy future capacity requirements without
    satisfying the stricter future N+1 requirement.
    """

    statuses = {
        "Option B": (True, False),
        "Option D": (True, True),
    }

    def fake_evaluate_design_option(**kwargs):
        name = kwargs["option_name"]

        future_pass, n1_pass = statuses[name]

        return {
            "option": name,
            "installed_blocks": kwargs["installed_blocks"],
            "transformer_mva": kwargs["transformer_mva"],
            "future_ready_pass": future_pass,
            "future_n1_ready_pass": n1_pass,
        }

    monkeypatch.setattr(
        design_engine,
        "evaluate_design_option",
        fake_evaluate_design_option,
    )

    design_options = [
        {
            "option": "Option B",
            "installed_blocks": 11,
            "transformer_mva": 75.0,
        },
        {
            "option": "Option D",
            "installed_blocks": 13,
            "transformer_mva": 75.0,
        },
    ]

    _, recommendations = design_engine.analyze_design_options(
        design_options
    )

    assert (
        recommendations["minimum_future_ready"]["option"]
        == "Option B"
    )

    assert (
        recommendations["minimum_future_n1"]["option"]
        == "Option D"
    )


def test_scenario_parameters_are_forwarded(monkeypatch):
    """
    Scenario assumptions supplied to analyze_design_options()
    must reach evaluate_design_option() unchanged.
    """

    captured_calls = []

    def fake_evaluate_design_option(**kwargs):
        captured_calls.append(kwargs)

        return {
            "option": kwargs["option_name"],
            "installed_blocks": kwargs["installed_blocks"],
            "transformer_mva": kwargs["transformer_mva"],
            "future_ready_pass": True,
            "future_n1_ready_pass": True,
        }

    monkeypatch.setattr(
        design_engine,
        "evaluate_design_option",
        fake_evaluate_design_option,
    )

    design_options = [
        {
            "option": "Option Test",
            "installed_blocks": 13,
            "transformer_mva": 75.0,
        }
    ]

    design_engine.analyze_design_options(
        design_options=design_options,
        current_export_mw=50.0,
        growth_percent=20.0,
        block_power_mw=5.0,
        block_energy_mwh=10.0,
        power_factor=0.95,
        reactive_power_command_percent=15.0,
        grid_voltage_kv=115.0,
        collector_voltage_kv=34.5,
        grid_source_voltage_pu=0.95,
    )

    call = captured_calls[0]

    assert call["current_export_mw"] == 50.0
    assert call["growth_percent"] == 20.0
    assert call["block_power_mw"] == 5.0
    assert call["block_energy_mwh"] == 10.0
    assert call["power_factor"] == 0.95
    assert call["reactive_power_command_percent"] == 15.0
    assert call["grid_voltage_kv"] == 115.0
    assert call["collector_voltage_kv"] == 34.5
    assert call["grid_source_voltage_pu"] == 0.95

# ============================================================
# REAL ENGINEERING INTEGRATION TESTS
# ============================================================

REAL_DESIGN_OPTIONS = [
    {
        "option": "Option A",
        "installed_blocks": 10,
        "transformer_mva": 60.0,
    },
    {
        "option": "Option B",
        "installed_blocks": 11,
        "transformer_mva": 75.0,
    },
    {
        "option": "Option C",
        "installed_blocks": 12,
        "transformer_mva": 75.0,
    },
    {
        "option": "Option D",
        "installed_blocks": 13,
        "transformer_mva": 75.0,
    },
    {
        "option": "Option E",
        "installed_blocks": 14,
        "transformer_mva": 100.0,
    },
]


def test_real_option_d_at_15_percent_growth():
    """
    Real electrical-model check for the nominal planning case.

    50 MW with 15% growth gives 57.5 MW future export.
    With 5 MW blocks:
        12 blocks are required for future capacity
        13 blocks are required for future N+1

    Therefore a 13-block / 75 MVA design should satisfy
    the future N+1 requirement under normal grid conditions.
    """

    result = design_engine.evaluate_design_option(
        option_name="Option D",
        installed_blocks=13,
        transformer_mva=75.0,
        current_export_mw=50.0,
        growth_percent=15.0,
        block_power_mw=5.0,
        block_energy_mwh=10.0,
        power_factor=0.95,
        reactive_power_command_percent=0.0,
        grid_voltage_kv=115.0,
        collector_voltage_kv=34.5,
        grid_source_voltage_pu=1.0,
    )

    assert result["current_required_blocks"] == 10
    assert result["future_required_blocks"] == 12

    assert result["current_capacity_pass"] is True
    assert result["current_n1_pass"] is True

    assert result["future_capacity_pass"] is True
    assert result["future_n1_pass"] is True

    assert result["current_transformer_pass"] is True
    assert result["future_transformer_pass"] is True

    assert result["current_operating_pass"] is True
    assert result["future_operating_pass"] is True

    assert result["future_ready_pass"] is True
    assert result["future_n1_ready_pass"] is True


def test_real_option_c_fails_future_n1_at_15_percent_growth():
    """
    Twelve blocks can meet the 57.5 MW future export requirement,
    but cannot preserve one-block redundancy after expansion.
    """

    result = design_engine.evaluate_design_option(
        option_name="Option C",
        installed_blocks=12,
        transformer_mva=75.0,
        current_export_mw=50.0,
        growth_percent=15.0,
        block_power_mw=5.0,
        block_energy_mwh=10.0,
        power_factor=0.95,
        reactive_power_command_percent=0.0,
        grid_voltage_kv=115.0,
        collector_voltage_kv=34.5,
        grid_source_voltage_pu=1.0,
    )

    assert result["future_required_blocks"] == 12
    assert result["future_capacity_pass"] is True
    assert result["future_n1_pass"] is False

    assert result["future_ready_pass"] is True
    assert result["future_n1_ready_pass"] is False


def test_real_growth_scenarios_select_expected_future_n1_designs():
    """
    Validate the real planning-engine recommendation sequence
    under normal voltage and zero reactive-power command.

    Expected:
        0% growth  -> Option B
        15% growth -> Option D
        30% growth -> Option E
    """

    scenarios = [
        (0.0, "Option B"),
        (15.0, "Option D"),
        (30.0, "Option E"),
    ]

    for growth_percent, expected_option in scenarios:

        results, recommendations = (
            design_engine.analyze_design_options(
                design_options=REAL_DESIGN_OPTIONS,
                current_export_mw=50.0,
                growth_percent=growth_percent,
                block_power_mw=5.0,
                block_energy_mwh=10.0,
                power_factor=0.95,
                reactive_power_command_percent=0.0,
                grid_voltage_kv=115.0,
                collector_voltage_kv=34.5,
                grid_source_voltage_pu=1.0,
            )
        )

        selected = recommendations["minimum_future_n1"]

        assert selected is not None
        assert selected["option"] == expected_option


def test_real_30_percent_growth_requires_100_mva_for_target_loading():
    """
    At 30% growth:

        Future export = 65 MW

    A 75 MVA transformer would operate above the modeled
    85% planning target, while 100 MVA remains below it.
    """

    option_d = design_engine.evaluate_design_option(
        option_name="Option D",
        installed_blocks=13,
        transformer_mva=75.0,
        current_export_mw=50.0,
        growth_percent=30.0,
        block_power_mw=5.0,
        block_energy_mwh=10.0,
        power_factor=0.95,
        reactive_power_command_percent=0.0,
        grid_voltage_kv=115.0,
        collector_voltage_kv=34.5,
        grid_source_voltage_pu=1.0,
    )

    option_e = design_engine.evaluate_design_option(
        option_name="Option E",
        installed_blocks=14,
        transformer_mva=100.0,
        current_export_mw=50.0,
        growth_percent=30.0,
        block_power_mw=5.0,
        block_energy_mwh=10.0,
        power_factor=0.95,
        reactive_power_command_percent=0.0,
        grid_voltage_kv=115.0,
        collector_voltage_kv=34.5,
        grid_source_voltage_pu=1.0,
    )

    assert option_d["future_transformer_loading_percent"] > 85.0
    assert option_d["future_transformer_pass"] is False

    assert option_e["future_transformer_loading_percent"] < 85.0
    assert option_e["future_transformer_pass"] is True

    assert option_e["future_n1_ready_pass"] is True