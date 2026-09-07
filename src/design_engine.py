import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.collector import (
    build_collector_network,
    run_collector_power_flow,
)

from src.electrical import reactive_power_mvar

VOLTAGE_MIN_PU = 0.95
VOLTAGE_MAX_PU = 1.05

MAIN_TRANSFORMER_TARGET_PERCENT = 85.0
FEEDER_LIMIT_PERCENT = 100.0
BLOCK_TRANSFORMER_LIMIT_PERCENT = 100.0

def get_commanded_reactive_power(
    active_power_mw,
    power_factor_reference,
    command_percent,
):

    if abs(command_percent) < 1e-9:
        return 0.0

    q_max_magnitude = reactive_power_mvar(
        active_power_mw,
        power_factor_reference,
    )

    return (
        q_max_magnitude
        * command_percent
        / 100.0
    )
    if reactive_power_mode == "Unity Power Factor (Q = 0)":
        return 0.0

    q_magnitude = reactive_power_mvar(
        active_power_mw,
        power_factor,
    )

    if reactive_power_mode == "Inject Reactive Power (+Q)":
        return q_magnitude

    if reactive_power_mode == "Absorb Reactive Power (-Q)":
        return -q_magnitude

    raise ValueError(
        "Unknown reactive power mode."
    )

def apparent_power_from_pq(
    active_power_mw,
    reactive_power_mvar_value,
):
    return (
        active_power_mw ** 2
        + reactive_power_mvar_value ** 2
    ) ** 0.5

def run_design_operating_case(
    installed_blocks,
    active_blocks,
    export_mw,
    transformer_mva,
    power_factor,
    reactive_power_command_percent,
    grid_voltage_kv,
    collector_voltage_kv,
    grid_source_voltage_pu=1.0,
):
    """
    Run one AC collector-system operating case.
    """

    if installed_blocks < active_blocks:

        return {
            "capacity_available": False,
            "operating_pass": False,
            "converged": False,
        }

    reactive_mvar = get_commanded_reactive_power(
        active_power_mw=export_mw,
        power_factor_reference=power_factor,
        command_percent=reactive_power_command_percent,
    )

    net, elements = build_collector_network(
        plant_export_mw=export_mw,
        plant_reactive_mvar=reactive_mvar,
        main_transformer_mva=transformer_mva,
        grid_voltage_kv=grid_voltage_kv,
        collector_voltage_kv=collector_voltage_kv,
        block_voltage_kv=0.8,
        number_of_blocks=installed_blocks,
        active_blocks=active_blocks,
        block_energy_mwh=10.0,
        grid_source_voltage_pu=grid_source_voltage_pu,
    )

    try:

        results = run_collector_power_flow(
            net,
            elements,
        )

    except Exception as error:

        return {
            "capacity_available": True,
            "operating_pass": False,
            "converged": False,
            "error": str(error),
        }

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
        <= MAIN_TRANSFORMER_TARGET_PERCENT
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

    operating_pass = all(
        [
            results["converged"],
            voltage_pass,
            main_transformer_pass,
            feeder_pass,
            block_transformer_pass,
        ]
    )

    return {
        "capacity_available":
            True,

        "operating_pass":
            operating_pass,

        "converged":
            results["converged"],

        "minimum_voltage_pu":
            results["minimum_block_voltage_pu"],

        "maximum_voltage_pu":
            results["maximum_block_voltage_pu"],

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
            results["total_network_losses_mw"],

        "grid_active_power_mw":
            results["grid_active_power_mw"],
    }


def evaluate_design_option(
    option_name,
    installed_blocks,
    transformer_mva,
    current_export_mw,
    growth_percent,
    block_power_mw,
    block_energy_mwh,
    power_factor,
    reactive_power_command_percent,
    grid_voltage_kv,
    collector_voltage_kv,
    grid_source_voltage_pu=1.0,
):
    """
    Evaluate one physical BESS design.
    """

    future_export_mw = (
        current_export_mw
        * (1 + growth_percent / 100)
    )

    current_reactive_mvar = get_commanded_reactive_power(
        active_power_mw=current_export_mw,
        power_factor_reference=power_factor,
        command_percent=reactive_power_command_percent,
    )

    future_reactive_mvar = get_commanded_reactive_power(
        active_power_mw=future_export_mw,
        power_factor_reference=power_factor,
        command_percent=reactive_power_command_percent,
    )

    current_apparent_mva = apparent_power_from_pq(
        active_power_mw=current_export_mw,
        reactive_power_mvar_value=current_reactive_mvar,
    )

    future_apparent_mva = apparent_power_from_pq(
        active_power_mw=future_export_mw,
        reactive_power_mvar_value=future_reactive_mvar,
    )

    # ---------------------------------------------------------
    # BLOCK REQUIREMENTS
    # ---------------------------------------------------------

    current_required_blocks = math.ceil(
        current_export_mw
        / block_power_mw
    )

    future_required_blocks = math.ceil(
        future_export_mw
        / block_power_mw
    )

    current_capacity_pass = (
        installed_blocks
        >= current_required_blocks
    )

    current_n1_pass = (
        installed_blocks
        >= current_required_blocks + 1
    )

    future_capacity_pass = (
        installed_blocks
        >= future_required_blocks
    )

    future_n1_pass = (
        installed_blocks
        >= future_required_blocks + 1
    )

    # ---------------------------------------------------------
    # INSTALLED NAMEPLATE
    # ---------------------------------------------------------

    installed_power_mw = (
        installed_blocks
        * block_power_mw
    )

    installed_energy_mwh = (
        installed_blocks
        * block_energy_mwh
    )

    # ---------------------------------------------------------
    # PRELIMINARY TRANSFORMER LOADING
    # ---------------------------------------------------------

    current_transformer_loading = (
        current_apparent_mva
        / transformer_mva
        * 100.0
    )

    future_transformer_loading = (
        future_apparent_mva
        / transformer_mva
        * 100.0
    )

    current_transformer_pass = (
        current_transformer_loading
        <= MAIN_TRANSFORMER_TARGET_PERCENT
    )

    future_transformer_pass = (
        future_transformer_loading
        <= MAIN_TRANSFORMER_TARGET_PERCENT
    )

    # ---------------------------------------------------------
    # CURRENT AC POWER FLOW
    # ---------------------------------------------------------

    current_case = run_design_operating_case(
        installed_blocks=installed_blocks,
        active_blocks=current_required_blocks,
        export_mw=current_export_mw,
        transformer_mva=transformer_mva,
        power_factor=power_factor,
        reactive_power_command_percent=reactive_power_command_percent,
        grid_voltage_kv=grid_voltage_kv,
        collector_voltage_kv=collector_voltage_kv,
        grid_source_voltage_pu=grid_source_voltage_pu,
    )

    # ---------------------------------------------------------
    # FUTURE AC POWER FLOW
    # ---------------------------------------------------------

    if future_capacity_pass:

        future_case = run_design_operating_case(
            installed_blocks=installed_blocks,
            active_blocks=future_required_blocks,
            export_mw=future_export_mw,
            transformer_mva=transformer_mva,
            power_factor=power_factor,
            reactive_power_command_percent=reactive_power_command_percent,
            grid_voltage_kv=grid_voltage_kv,
            collector_voltage_kv=collector_voltage_kv,
            grid_source_voltage_pu=grid_source_voltage_pu,
        )

    else:

        future_case = {
            "capacity_available": False,
            "operating_pass": False,
            "converged": False,
        }

    # ---------------------------------------------------------
    # DESIGN POLICIES
    # ---------------------------------------------------------

    # Requirement Set 1:
    #
    # - meet current capacity
    # - provide N+1 block redundancy today
    # - support 15% future expansion
    # - satisfy transformer target
    # - satisfy AC operating limits

    future_ready_pass = all(
        [
            current_capacity_pass,
            current_n1_pass,
            future_capacity_pass,
            current_transformer_pass,
            future_transformer_pass,
            current_case["operating_pass"],
            future_case["operating_pass"],
        ]
    )

    # Requirement Set 2:
    #
    # Everything above PLUS
    # preserve one-block N+1 redundancy
    # after the 15% expansion.

    future_n1_ready_pass = (
        future_ready_pass
        and future_n1_pass
    )

    return {
        "option":
            option_name,

        "installed_blocks":
            installed_blocks,

        "installed_power_mw":
            installed_power_mw,

        "installed_energy_mwh":
            installed_energy_mwh,

        "transformer_mva":
            transformer_mva,

        "current_required_blocks":
            current_required_blocks,

        "future_required_blocks":
            future_required_blocks,

        "current_capacity_pass":
            current_capacity_pass,

        "current_n1_pass":
            current_n1_pass,

        "future_capacity_pass":
            future_capacity_pass,

        "future_n1_pass":
            future_n1_pass,

        "current_transformer_loading_percent":
            current_transformer_loading,

        "future_transformer_loading_percent":
            future_transformer_loading,

        "current_transformer_pass":
            current_transformer_pass,

        "future_transformer_pass":
            future_transformer_pass,

        "current_operating_pass":
            current_case["operating_pass"],

        "future_operating_pass":
            future_case["operating_pass"],

        "current_case":
            current_case,

        "future_case":
            future_case,

        "future_ready_pass":
            future_ready_pass,

        "future_n1_ready_pass":
            future_n1_ready_pass,
    }


def analyze_design_options(
    design_options,
    current_export_mw=50.0,
    growth_percent=15.0,
    block_power_mw=5.0,
    block_energy_mwh=10.0,
    power_factor=0.95,
    reactive_power_command_percent=0.0,
    grid_voltage_kv=115.0,
    collector_voltage_kv=34.5,
    grid_source_voltage_pu=1.0,
):
    """
    Evaluate all candidate designs and make recommendations.
    """

    results = []

    for option in design_options:

        result = evaluate_design_option(
            option_name=option["option"],
            installed_blocks=option[
                "installed_blocks"
            ],
            transformer_mva=option[
                "transformer_mva"
            ],
            current_export_mw=current_export_mw,
            growth_percent=growth_percent,
            block_power_mw=block_power_mw,
            block_energy_mwh=block_energy_mwh,
            power_factor=power_factor,
            reactive_power_command_percent=reactive_power_command_percent,
            grid_voltage_kv=grid_voltage_kv,
            collector_voltage_kv=collector_voltage_kv,
            grid_source_voltage_pu=grid_source_voltage_pu,
        )

        results.append(
            result
        )

    # ---------------------------------------------------------
    # MINIMUM FUTURE-READY DESIGN
    # ---------------------------------------------------------

    future_ready_candidates = [
        result
        for result in results
        if result["future_ready_pass"]
    ]

    if future_ready_candidates:

        minimum_future_ready = min(
            future_ready_candidates,
            key=lambda x: (
                x["installed_blocks"],
                x["transformer_mva"],
            ),
        )

    else:

        minimum_future_ready = None

    # ---------------------------------------------------------
    # MINIMUM FUTURE N+1 DESIGN
    # ---------------------------------------------------------

    future_n1_candidates = [
        result
        for result in results
        if result["future_n1_ready_pass"]
    ]

    if future_n1_candidates:

        minimum_future_n1 = min(
            future_n1_candidates,
            key=lambda x: (
                x["installed_blocks"],
                x["transformer_mva"],
            ),
        )

    else:

        minimum_future_n1 = None

    recommendations = {
        "minimum_future_ready":
            minimum_future_ready,

        "minimum_future_n1":
            minimum_future_n1,
    }

    return results, recommendations


def save_design_outputs(
    design_results,
    results_directory="results",
):
    """
    Save design comparison CSV and transformer-loading graph.
    """

    results_path = Path(
        results_directory
    )

    results_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    rows = []

    for result in design_results:

        rows.append(
            {
                "option":
                    result["option"],

                "installed_blocks":
                    result["installed_blocks"],

                "installed_power_mw":
                    result["installed_power_mw"],

                "installed_energy_mwh":
                    result["installed_energy_mwh"],

                "transformer_mva":
                    result["transformer_mva"],

                "current_n1_pass":
                    result["current_n1_pass"],

                "future_capacity_pass":
                    result["future_capacity_pass"],

                "future_n1_pass":
                    result["future_n1_pass"],

                "current_transformer_loading_percent":
                    result[
                        "current_transformer_loading_percent"
                    ],

                "future_transformer_loading_percent":
                    result[
                        "future_transformer_loading_percent"
                    ],

                "current_operating_pass":
                    result["current_operating_pass"],

                "future_operating_pass":
                    result["future_operating_pass"],

                "future_ready_pass":
                    result["future_ready_pass"],

                "future_n1_ready_pass":
                    result["future_n1_ready_pass"],
            }
        )

    dataframe = pd.DataFrame(
        rows
    )

    csv_path = (
        results_path
        / "design_option_comparison.csv"
    )

    dataframe.to_csv(
        csv_path,
        index=False,
    )

    # ---------------------------------------------------------
    # TRANSFORMER LOADING GRAPH
    # ---------------------------------------------------------

    option_names = dataframe[
        "option"
    ].tolist()

    current_loading = dataframe[
        "current_transformer_loading_percent"
    ].to_numpy()

    future_loading = dataframe[
        "future_transformer_loading_percent"
    ].to_numpy()

    positions = np.arange(
        len(option_names)
    )

    bar_width = 0.35

    plt.figure()

    plt.bar(
        positions - bar_width / 2,
        current_loading,
        width=bar_width,
        label="Current 50 MW",
    )

    plt.bar(
        positions + bar_width / 2,
        future_loading,
        width=bar_width,
        label="15% Expansion",
    )

    plt.axhline(
        85.0,
        linestyle="--",
        label="85% Design Target",
    )

    plt.xticks(
        positions,
        option_names,
    )

    plt.ylabel(
        "Transformer Loading (%)"
    )

    plt.xlabel(
        "Design Option"
    )

    plt.title(
        "Main Transformer Design Comparison"
    )

    plt.grid(
        True,
        axis="y",
    )

    plt.legend()

    plt.tight_layout()

    graph_path = (
        results_path
        / "design_transformer_comparison.png"
    )

    plt.savefig(
        graph_path,
        dpi=200,
    )

    plt.close()

    return {
        "csv":
            str(csv_path),

        "transformer_graph":
            str(graph_path),
    }