from src.collector import (
    build_collector_network,
    run_collector_power_flow,
)


VOLTAGE_MIN_PU = 0.95
VOLTAGE_MAX_PU = 1.05

MAIN_TRANSFORMER_LIMIT_PERCENT = 85.0
FEEDER_LIMIT_PERCENT = 100.0
BLOCK_TRANSFORMER_LIMIT_PERCENT = 100.0


def get_block(elements, block_number):
    """
    Find one BESS block in the collector-system element list.
    """

    for block in elements["blocks"]:
        if block["number"] == block_number:
            return block

    raise ValueError(
        f"BESS Block {block_number} was not found."
    )


def take_block_out_of_service(net, elements, block_number):
    """
    Remove one BESS storage block from service.

    The feeder and transformer remain energized in this
    simplified model, but the BESS itself produces no power.
    """

    block = get_block(elements, block_number)

    storage_index = block["storage"]

    net.storage.at[storage_index, "p_mw"] = 0.0
    net.storage.at[storage_index, "q_mvar"] = 0.0
    net.storage.at[storage_index, "in_service"] = False

    block["status"] = "FAILED"


def activate_reserve_block(
    net,
    elements,
    block_number,
    active_power_mw,
    reactive_power_mvar,
):
    """
    Activate a standby BESS block.
    """

    block = get_block(elements, block_number)

    storage_index = block["storage"]

    # Pandapower storage sign convention:
    # negative P = discharging/exporting
    net.storage.at[storage_index, "p_mw"] = -active_power_mw
    net.storage.at[storage_index, "q_mvar"] = -reactive_power_mvar
    net.storage.at[storage_index, "in_service"] = True

    block["status"] = "RESERVE"


def calculate_scheduled_bess_output(net):
    """
    Calculate gross scheduled BESS discharge power.
    """

    total_mw = 0.0

    for _, storage in net.storage.iterrows():

        if bool(storage["in_service"]):

            p_mw = float(storage["p_mw"])

            if p_mw < 0:
                total_mw += -p_mw

    return total_mw


def run_block_contingency(
    scenario_name,
    failed_blocks,
    activate_reserve,
    plant_export_mw,
    plant_reactive_mvar,
    main_transformer_mva,
    grid_voltage_kv,
    collector_voltage_kv,
):
    """
    Build and solve one BESS contingency scenario.
    """

    # ---------------------------------------------------------
    # BUILD NORMAL NETWORK
    # ---------------------------------------------------------

    net, elements = build_collector_network(
        plant_export_mw=plant_export_mw,
        plant_reactive_mvar=plant_reactive_mvar,
        main_transformer_mva=main_transformer_mva,
        grid_voltage_kv=grid_voltage_kv,
        collector_voltage_kv=collector_voltage_kv,
        block_voltage_kv=0.8,
        number_of_blocks=11,
        active_blocks=10,
        block_energy_mwh=10.0,
    )

    # Each normally active block supplies 1/10 of plant output.
    block_active_power_mw = plant_export_mw / 10.0

    block_reactive_power_mvar = (
        plant_reactive_mvar / 10.0
    )

    # ---------------------------------------------------------
    # APPLY FAILURES
    # ---------------------------------------------------------

    for block_number in failed_blocks:

        take_block_out_of_service(
            net,
            elements,
            block_number,
        )

    # ---------------------------------------------------------
    # ACTIVATE STANDBY BLOCK 11 IF REQUESTED
    # ---------------------------------------------------------

    if activate_reserve:

        activate_reserve_block(
            net,
            elements,
            block_number=11,
            active_power_mw=block_active_power_mw,
            reactive_power_mvar=block_reactive_power_mvar,
        )

    # ---------------------------------------------------------
    # RUN POWER FLOW
    # ---------------------------------------------------------

    collector_results = run_collector_power_flow(
        net,
        elements,
    )

    scheduled_output_mw = calculate_scheduled_bess_output(
        net
    )

    capacity_margin_mw = (
        scheduled_output_mw
        - plant_export_mw
    )

    # ---------------------------------------------------------
    # ENGINEERING CHECKS
    # ---------------------------------------------------------

    capacity_pass = (
        scheduled_output_mw
        >= plant_export_mw - 1e-6
    )

    voltage_pass = (
        collector_results["minimum_block_voltage_pu"]
        >= VOLTAGE_MIN_PU
        and
        collector_results["maximum_block_voltage_pu"]
        <= VOLTAGE_MAX_PU
    )

    main_transformer_pass = (
        collector_results[
            "main_transformer_loading_percent"
        ]
        <= MAIN_TRANSFORMER_LIMIT_PERCENT
    )

    feeder_pass = (
        collector_results[
            "maximum_feeder_loading_percent"
        ]
        <= FEEDER_LIMIT_PERCENT
    )

    block_transformer_pass = (
        collector_results[
            "maximum_block_transformer_loading_percent"
        ]
        <= BLOCK_TRANSFORMER_LIMIT_PERCENT
    )

    convergence_pass = collector_results["converged"]

    checks = {
        "Power-flow convergence":
            convergence_pass,

        "Required BESS capacity":
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
        check_name
        for check_name, passed in checks.items()
        if not passed
    ]

    overall_pass = all(checks.values())

    return {
        "scenario": scenario_name,

        "failed_blocks": failed_blocks,

        "reserve_activated":
            activate_reserve,

        "scheduled_output_mw":
            scheduled_output_mw,

        "capacity_margin_mw":
            capacity_margin_mw,

        "grid_active_power_mw":
            collector_results[
                "grid_active_power_mw"
            ],

        "collector_voltage_pu":
            collector_results[
                "collector_voltage_pu"
            ],

        "minimum_voltage_pu":
            collector_results[
                "minimum_block_voltage_pu"
            ],

        "maximum_voltage_pu":
            collector_results[
                "maximum_block_voltage_pu"
            ],

        "main_transformer_loading_percent":
            collector_results[
                "main_transformer_loading_percent"
            ],

        "maximum_feeder_loading_percent":
            collector_results[
                "maximum_feeder_loading_percent"
            ],

        "maximum_block_transformer_loading_percent":
            collector_results[
                "maximum_block_transformer_loading_percent"
            ],

        "network_losses_mw":
            collector_results[
                "total_network_losses_mw"
            ],

        "checks":
            checks,

        "failed_checks":
            failed_checks,

        "overall_pass":
            overall_pass,
    }


def run_contingency_suite(
    plant_export_mw,
    plant_reactive_mvar,
    main_transformer_mva,
    grid_voltage_kv,
    collector_voltage_kv,
):
    """
    Run the Version 0.5 contingency study.
    """

    common_arguments = {
        "plant_export_mw":
            plant_export_mw,

        "plant_reactive_mvar":
            plant_reactive_mvar,

        "main_transformer_mva":
            main_transformer_mva,

        "grid_voltage_kv":
            grid_voltage_kv,

        "collector_voltage_kv":
            collector_voltage_kv,
    }

    normal = run_block_contingency(
        scenario_name="NORMAL OPERATION",
        failed_blocks=[],
        activate_reserve=False,
        **common_arguments,
    )

    single_failure_before_reserve = run_block_contingency(
        scenario_name="BLOCK 4 FAILURE - BEFORE RESERVE",
        failed_blocks=[4],
        activate_reserve=False,
        **common_arguments,
    )

    single_failure_recovered = run_block_contingency(
        scenario_name="BLOCK 4 FAILURE - RESERVE ACTIVATED",
        failed_blocks=[4],
        activate_reserve=True,
        **common_arguments,
    )

    double_failure = run_block_contingency(
        scenario_name="BLOCKS 4 & 7 FAILURE - RESERVE ACTIVATED",
        failed_blocks=[4, 7],
        activate_reserve=True,
        **common_arguments,
    )

    return [
        normal,
        single_failure_before_reserve,
        single_failure_recovered,
        double_failure,
    ]