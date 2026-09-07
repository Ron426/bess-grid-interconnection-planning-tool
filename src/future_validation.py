import math

from src.collector import (
    build_collector_network,
    run_collector_power_flow,
)

from src.contingencies import (
    take_block_out_of_service,
    activate_reserve_block,
    calculate_scheduled_bess_output,
)

from src.electrical import reactive_power_mvar


VOLTAGE_MIN_PU = 0.95
VOLTAGE_MAX_PU = 1.05

MAIN_TRANSFORMER_LIMIT_PERCENT = 85.0
FEEDER_LIMIT_PERCENT = 100.0
BLOCK_TRANSFORMER_LIMIT_PERCENT = 100.0


def run_future_scenario(
    scenario_name,
    failed_blocks,
    activate_reserve,
    installed_blocks,
    current_export_mw,
    growth_percent,
    block_power_mw,
    power_factor,
    reactive_power_command_percent,
    main_transformer_mva,
    grid_voltage_kv,
    collector_voltage_kv,
):
    """
    Build and solve one future-expansion BESS scenario.
    """

    # ---------------------------------------------------------
    # FUTURE PLANT REQUIREMENT
    # ---------------------------------------------------------

    future_export_mw = (
        current_export_mw
        * (1 + growth_percent / 100)
    )

    required_active_blocks = math.ceil(
        future_export_mw
        / block_power_mw
    )

    if installed_blocks < required_active_blocks:

        raise ValueError(
            "Installed blocks are insufficient "
            "for the future export requirement."
        )

    # ---------------------------------------------------------
    # SHARE FUTURE EXPORT ACROSS REQUIRED ACTIVE BLOCKS
    # ---------------------------------------------------------

    block_active_power_mw = (
        future_export_mw
        / required_active_blocks
    )

    future_reactive_magnitude = reactive_power_mvar(
        future_export_mw,
        power_factor,
    )

    future_reactive_mvar = (
        future_reactive_magnitude
        * reactive_power_command_percent
        / 100.0
    )

    block_reactive_power_mvar = (
        future_reactive_mvar
        / required_active_blocks
    )

    # ---------------------------------------------------------
    # BUILD FUTURE NETWORK
    #
    # Example for Option D:
    # 13 installed
    # 12 active
    # 1 standby
    # ---------------------------------------------------------

    net, elements = build_collector_network(
        plant_export_mw=future_export_mw,
        plant_reactive_mvar=future_reactive_mvar,
        main_transformer_mva=main_transformer_mva,
        grid_voltage_kv=grid_voltage_kv,
        collector_voltage_kv=collector_voltage_kv,
        block_voltage_kv=0.8,
        number_of_blocks=installed_blocks,
        active_blocks=required_active_blocks,
        block_energy_mwh=10.0,
    )

    # ---------------------------------------------------------
    # APPLY FAILED BLOCKS
    # ---------------------------------------------------------

    for block_number in failed_blocks:

        take_block_out_of_service(
            net,
            elements,
            block_number,
        )

    # ---------------------------------------------------------
    # ACTIVATE FINAL INSTALLED BLOCK AS RESERVE
    # ---------------------------------------------------------

    reserve_block_number = installed_blocks

    if activate_reserve:

        activate_reserve_block(
            net,
            elements,
            block_number=reserve_block_number,
            active_power_mw=block_active_power_mw,
            reactive_power_mvar=block_reactive_power_mvar,
        )

    # ---------------------------------------------------------
    # RUN AC POWER FLOW
    # ---------------------------------------------------------

    results = run_collector_power_flow(
        net,
        elements,
    )

    scheduled_output_mw = (
        calculate_scheduled_bess_output(net)
    )

    capacity_margin_mw = (
        scheduled_output_mw
        - future_export_mw
    )

    # ---------------------------------------------------------
    # ENGINEERING CHECKS
    # ---------------------------------------------------------

    capacity_pass = (
        scheduled_output_mw
        >= future_export_mw - 1e-6
    )

    voltage_pass = (
        results["minimum_block_voltage_pu"]
        >= VOLTAGE_MIN_PU
        and
        results["maximum_block_voltage_pu"]
        <= VOLTAGE_MAX_PU
    )

    main_transformer_pass = (
        results[
            "main_transformer_loading_percent"
        ]
        <= MAIN_TRANSFORMER_LIMIT_PERCENT
    )

    feeder_pass = (
        results[
            "maximum_feeder_loading_percent"
        ]
        <= FEEDER_LIMIT_PERCENT
    )

    block_transformer_pass = (
        results[
            "maximum_block_transformer_loading_percent"
        ]
        <= BLOCK_TRANSFORMER_LIMIT_PERCENT
    )

    convergence_pass = (
        results["converged"]
    )

    checks = {
        "Power-flow convergence":
            convergence_pass,

        "Future BESS capacity":
            capacity_pass,

        "Voltage limits":
            voltage_pass,

        "Main transformer loading":
            main_transformer_pass,

        "Collector feeder loading":
            feeder_pass,

        "Block transformer loading":
            block_transformer_pass,
    }

    failed_checks = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    overall_pass = all(
        checks.values()
    )

    return {
        "scenario":
            scenario_name,

        "future_export_mw":
            future_export_mw,

        "required_active_blocks":
            required_active_blocks,

        "installed_blocks":
            installed_blocks,

        "reserve_block":
            reserve_block_number,

        "block_active_power_mw":
            block_active_power_mw,

        "failed_blocks":
            failed_blocks,

        "reserve_activated":
            activate_reserve,

        "scheduled_output_mw":
            scheduled_output_mw,

        "capacity_margin_mw":
            capacity_margin_mw,

        "grid_active_power_mw":
            results[
                "grid_active_power_mw"
            ],

        "collector_voltage_pu":
            results[
                "collector_voltage_pu"
            ],

        "minimum_voltage_pu":
            results[
                "minimum_block_voltage_pu"
            ],

        "maximum_voltage_pu":
            results[
                "maximum_block_voltage_pu"
            ],

        "main_transformer_loading_percent":
            results[
                "main_transformer_loading_percent"
            ],

        "maximum_feeder_loading_percent":
            results[
                "maximum_feeder_loading_percent"
            ],

        "maximum_block_transformer_loading_percent":
            results[
                "maximum_block_transformer_loading_percent"
            ],

        "network_losses_mw":
            results[
                "total_network_losses_mw"
            ],

        "checks":
            checks,

        "failed_checks":
            failed_checks,

        "overall_pass":
            overall_pass,
    }


def run_future_n1_validation(
    installed_blocks=13,
    current_export_mw=50.0,
    growth_percent=15.0,
    block_power_mw=5.0,
    power_factor=0.95,
    reactive_power_command_percent=0.0,
    main_transformer_mva=75.0,
    grid_voltage_kv=115.0,
    collector_voltage_kv=34.5,
):
    """
    Validate the preferred future-ready Option D design.
    """

    common_arguments = {
        "installed_blocks":
            installed_blocks,

        "current_export_mw":
            current_export_mw,

        "growth_percent":
            growth_percent,

        "block_power_mw":
            block_power_mw,

        "power_factor":
            power_factor,

        "reactive_power_command_percent":
            reactive_power_command_percent,

        "main_transformer_mva":
            main_transformer_mva,

        "grid_voltage_kv":
            grid_voltage_kv,

        "collector_voltage_kv":
            collector_voltage_kv,
    }

    # ---------------------------------------------------------
    # FUTURE NORMAL OPERATION
    # ---------------------------------------------------------

    normal_future = run_future_scenario(
        scenario_name="FUTURE NORMAL OPERATION",
        failed_blocks=[],
        activate_reserve=False,
        **common_arguments,
    )

    # ---------------------------------------------------------
    # ONE BLOCK FAILS BEFORE RESERVE RESPONSE
    # ---------------------------------------------------------

    one_failure_before_reserve = (
        run_future_scenario(
            scenario_name=(
                "FUTURE BLOCK 4 FAILURE - "
                "BEFORE RESERVE"
            ),
            failed_blocks=[4],
            activate_reserve=False,
            **common_arguments,
        )
    )

    # ---------------------------------------------------------
    # BLOCK 13 REPLACES FAILED BLOCK
    # ---------------------------------------------------------

    one_failure_recovered = (
        run_future_scenario(
            scenario_name=(
                "FUTURE BLOCK 4 FAILURE - "
                "BLOCK 13 ACTIVATED"
            ),
            failed_blocks=[4],
            activate_reserve=True,
            **common_arguments,
        )
    )

    # ---------------------------------------------------------
    # TWO BLOCKS FAIL WITH ONLY ONE RESERVE
    # ---------------------------------------------------------

    two_failures = run_future_scenario(
        scenario_name=(
            "FUTURE BLOCKS 4 & 7 FAILURE - "
            "BLOCK 13 ACTIVATED"
        ),
        failed_blocks=[4, 7],
        activate_reserve=True,
        **common_arguments,
    )

    scenarios = [
        normal_future,
        one_failure_before_reserve,
        one_failure_recovered,
        two_failures,
    ]

    future_n1_pass = all(
        [
            normal_future["overall_pass"],
            one_failure_recovered[
                "overall_pass"
            ],
        ]
    )

    return scenarios, future_n1_pass