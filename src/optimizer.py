from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import linprog


def optimize_peak_shaving(
    load_profile_path,
    bess_power_mw=50.0,
    bess_energy_mwh=100.0,
    initial_soc_percent=50.0,
    min_soc_percent=20.0,
    max_soc_percent=90.0,
    charge_efficiency=0.95,
    discharge_efficiency=0.95,
    max_charge_power_mw=10.0,
    timestep_hours=1.0,
):
    """
    Determine the minimum achievable 24-hour grid peak
    using linear programming.

    Decision variables for every hour:
    - charging power
    - discharging power
    - stored battery energy

    Plus:
    - one optimized peak-power variable
    """

    # ---------------------------------------------------------
    # INPUT CHECKS
    # ---------------------------------------------------------

    if bess_power_mw <= 0:
        raise ValueError(
            "BESS power rating must be greater than zero."
        )

    if bess_energy_mwh <= 0:
        raise ValueError(
            "BESS energy capacity must be greater than zero."
        )

    if max_charge_power_mw <= 0:
        raise ValueError(
            "Maximum charge power must be greater than zero."
        )

    if not 0 < charge_efficiency <= 1:
        raise ValueError(
            "Charge efficiency must be between 0 and 1."
        )

    if not 0 < discharge_efficiency <= 1:
        raise ValueError(
            "Discharge efficiency must be between 0 and 1."
        )

    if not (
        0
        <= min_soc_percent
        < max_soc_percent
        <= 100
    ):
        raise ValueError(
            "Invalid SOC limits."
        )

    if not (
        min_soc_percent
        <= initial_soc_percent
        <= max_soc_percent
    ):
        raise ValueError(
            "Initial SOC must lie within SOC limits."
        )

    # ---------------------------------------------------------
    # LOAD PROFILE
    # ---------------------------------------------------------

    load_profile = pd.read_csv(
        load_profile_path
    )

    if not {
        "hour",
        "load_mw",
    }.issubset(load_profile.columns):

        raise ValueError(
            "Load profile must contain "
            "'hour' and 'load_mw' columns."
        )

    hours = (
        load_profile["hour"]
        .astype(int)
        .to_numpy()
    )

    loads_mw = (
        load_profile["load_mw"]
        .astype(float)
        .to_numpy()
    )

    number_of_hours = len(loads_mw)

    # ---------------------------------------------------------
    # ENERGY LIMITS
    # ---------------------------------------------------------

    initial_energy_mwh = (
        bess_energy_mwh
        * initial_soc_percent
        / 100
    )

    minimum_energy_mwh = (
        bess_energy_mwh
        * min_soc_percent
        / 100
    )

    maximum_energy_mwh = (
        bess_energy_mwh
        * max_soc_percent
        / 100
    )

    # ---------------------------------------------------------
    # DECISION-VARIABLE INDEXING
    #
    # Variables are arranged:
    #
    # charge[0:24]
    # discharge[0:24]
    # energy[0:24]
    # optimized_peak
    # ---------------------------------------------------------

    charge_start = 0

    discharge_start = (
        number_of_hours
    )

    energy_start = (
        2 * number_of_hours
    )

    peak_index = (
        3 * number_of_hours
    )

    number_of_variables = (
        3 * number_of_hours
        + 1
    )

    # ---------------------------------------------------------
    # OBJECTIVE FUNCTION
    #
    # Primary objective:
    # minimize grid peak.
    #
    # A tiny throughput penalty discourages unnecessary
    # simultaneous charging/discharging.
    # ---------------------------------------------------------

    objective = np.zeros(
        number_of_variables
    )

    objective[peak_index] = 1.0

    throughput_penalty = 1e-6

    objective[
        charge_start:
        discharge_start
    ] = throughput_penalty

    objective[
        discharge_start:
        energy_start
    ] = throughput_penalty

    # ---------------------------------------------------------
    # EQUALITY CONSTRAINTS
    #
    # Battery energy:
    #
    # E(t) =
    # E(t-1)
    # + charge * efficiency
    # - discharge / efficiency
    # ---------------------------------------------------------

    equality_matrix = []
    equality_rhs = []

    for hour_index in range(
        number_of_hours
    ):

        row = np.zeros(
            number_of_variables
        )

        energy_variable = (
            energy_start
            + hour_index
        )

        charge_variable = (
            charge_start
            + hour_index
        )

        discharge_variable = (
            discharge_start
            + hour_index
        )

        row[energy_variable] = 1.0

        row[charge_variable] = (
            -charge_efficiency
            * timestep_hours
        )

        row[discharge_variable] = (
            timestep_hours
            / discharge_efficiency
        )

        if hour_index == 0:

            equality_rhs.append(
                initial_energy_mwh
            )

        else:

            previous_energy_variable = (
                energy_start
                + hour_index
                - 1
            )

            row[
                previous_energy_variable
            ] = -1.0

            equality_rhs.append(
                0.0
            )

        equality_matrix.append(
            row
        )

    # ---------------------------------------------------------
    # FINAL SOC REQUIREMENT
    #
    # Final SOC must equal initial SOC.
    #
    # This prevents the optimizer from lowering the peak
    # simply by draining the battery.
    # ---------------------------------------------------------

    final_soc_row = np.zeros(
        number_of_variables
    )

    final_soc_row[
        energy_start
        + number_of_hours
        - 1
    ] = 1.0

    equality_matrix.append(
        final_soc_row
    )

    equality_rhs.append(
        initial_energy_mwh
    )

    # ---------------------------------------------------------
    # PEAK CONSTRAINT
    #
    # Grid power =
    # Load + Charge - Discharge
    #
    # Require:
    #
    # Grid power <= Optimized Peak
    # ---------------------------------------------------------

    inequality_matrix = []
    inequality_rhs = []

    for hour_index, load_mw in enumerate(
        loads_mw
    ):

        row = np.zeros(
            number_of_variables
        )

        row[
            charge_start
            + hour_index
        ] = 1.0

        row[
            discharge_start
            + hour_index
        ] = -1.0

        row[peak_index] = -1.0

        inequality_matrix.append(
            row
        )

        inequality_rhs.append(
            -load_mw
        )

    # ---------------------------------------------------------
    # VARIABLE BOUNDS
    # ---------------------------------------------------------

    bounds = []

    # Charge power
    for _ in range(
        number_of_hours
    ):

        bounds.append(
            (
                0.0,
                max_charge_power_mw,
            )
        )

    # Discharge power
    for _ in range(
        number_of_hours
    ):

        bounds.append(
            (
                0.0,
                bess_power_mw,
            )
        )

    # Stored energy
    for _ in range(
        number_of_hours
    ):

        bounds.append(
            (
                minimum_energy_mwh,
                maximum_energy_mwh,
            )
        )

    # Optimized grid peak
    bounds.append(
        (
            0.0,
            None,
        )
    )

    # ---------------------------------------------------------
    # RUN LINEAR PROGRAM
    # ---------------------------------------------------------

    optimization_result = linprog(
        objective,
        A_ub=np.array(
            inequality_matrix
        ),
        b_ub=np.array(
            inequality_rhs
        ),
        A_eq=np.array(
            equality_matrix
        ),
        b_eq=np.array(
            equality_rhs
        ),
        bounds=bounds,
        method="highs",
    )

    if not optimization_result.success:

        raise RuntimeError(
            "Optimization failed: "
            + optimization_result.message
        )

    solution = (
        optimization_result.x
    )

    # ---------------------------------------------------------
    # EXTRACT SOLUTION
    # ---------------------------------------------------------

    charging_mw = solution[
        charge_start:
        discharge_start
    ]

    discharging_mw = solution[
        discharge_start:
        energy_start
    ]

    stored_energy_mwh = solution[
        energy_start:
        peak_index
    ]

    optimized_peak_mw = float(
        solution[peak_index]
    )

    net_bess_power_mw = (
        discharging_mw
        - charging_mw
    )

    grid_power_mw = (
        loads_mw
        + charging_mw
        - discharging_mw
    )

    soc_percent = (
        stored_energy_mwh
        / bess_energy_mwh
        * 100
    )

    # ---------------------------------------------------------
    # OPERATING MODE
    # ---------------------------------------------------------

    operating_modes = []

    for charge_mw, discharge_mw in zip(
        charging_mw,
        discharging_mw,
    ):

        if discharge_mw > 1e-6:
            operating_modes.append(
                "DISCHARGE"
            )

        elif charge_mw > 1e-6:
            operating_modes.append(
                "CHARGE"
            )

        else:
            operating_modes.append(
                "IDLE"
            )

    # ---------------------------------------------------------
    # RESULTS TABLE
    # ---------------------------------------------------------

    results_df = pd.DataFrame(
        {
            "hour":
                hours,

            "load_mw":
                loads_mw,

            "mode":
                operating_modes,

            "charge_mw":
                charging_mw,

            "discharge_mw":
                discharging_mw,

            "bess_power_mw":
                net_bess_power_mw,

            "grid_power_mw":
                grid_power_mw,

            "energy_mwh":
                stored_energy_mwh,

            "soc_percent":
                soc_percent,
        }
    )

    original_peak_mw = float(
        loads_mw.max()
    )

    peak_reduction_mw = (
        original_peak_mw
        - optimized_peak_mw
    )

    total_charge_mwh = float(
        charging_mw.sum()
        * timestep_hours
    )

    total_discharge_mwh = float(
        discharging_mw.sum()
        * timestep_hours
    )

    summary = {
        "optimization_success":
            optimization_result.success,

        "original_peak_mw":
            original_peak_mw,

        "optimized_peak_mw":
            optimized_peak_mw,

        "peak_reduction_mw":
            peak_reduction_mw,

        "initial_soc_percent":
            initial_soc_percent,

        "final_soc_percent":
            float(
                soc_percent[-1]
            ),

        "minimum_soc_percent":
            float(
                soc_percent.min()
            ),

        "maximum_soc_percent":
            float(
                soc_percent.max()
            ),

        "total_charge_mwh":
            total_charge_mwh,

        "total_discharge_mwh":
            total_discharge_mwh,
    }

    return results_df, summary


def save_optimization_outputs(
    optimized_results,
    rule_based_results=None,
    results_directory="results",
):
    """
    Save optimized dispatch outputs and comparison graphs.
    """

    results_path = Path(
        results_directory
    )

    results_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ---------------------------------------------------------
    # CSV
    # ---------------------------------------------------------

    csv_path = (
        results_path
        / "optimized_dispatch_results.csv"
    )

    optimized_results.to_csv(
        csv_path,
        index=False,
    )

    # ---------------------------------------------------------
    # OPTIMIZED LOAD GRAPH
    # ---------------------------------------------------------

    plt.figure()

    plt.plot(
        optimized_results["hour"],
        optimized_results["load_mw"],
        marker="o",
        label="Original Load",
    )

    plt.plot(
        optimized_results["hour"],
        optimized_results[
            "grid_power_mw"
        ],
        marker="o",
        label="Optimized Grid Power",
    )

    optimized_peak = (
        optimized_results[
            "grid_power_mw"
        ].max()
    )

    plt.axhline(
        optimized_peak,
        linestyle="--",
        label=(
            f"Optimized Peak "
            f"{optimized_peak:.2f} MW"
        ),
    )

    plt.xlabel("Hour")
    plt.ylabel("Power (MW)")

    plt.title(
        "Optimization-Based BESS Peak Shaving"
    )

    plt.grid(True)
    plt.legend()
    plt.tight_layout()

    optimized_plot_path = (
        results_path
        / "optimized_peak_shaving.png"
    )

    plt.savefig(
        optimized_plot_path,
        dpi=200,
    )

    plt.close()

    # ---------------------------------------------------------
    # OPTIMIZED SOC GRAPH
    # ---------------------------------------------------------

    plt.figure()

    plt.plot(
        optimized_results["hour"],
        optimized_results[
            "soc_percent"
        ],
        marker="o",
    )

    plt.axhline(
        20.0,
        linestyle="--",
        label="Minimum SOC",
    )

    plt.axhline(
        90.0,
        linestyle="--",
        label="Maximum SOC",
    )

    plt.xlabel("Hour")
    plt.ylabel("State of Charge (%)")

    plt.title(
        "Optimized BESS State of Charge"
    )

    plt.grid(True)
    plt.legend()
    plt.tight_layout()

    optimized_soc_path = (
        results_path
        / "optimized_soc_profile.png"
    )

    plt.savefig(
        optimized_soc_path,
        dpi=200,
    )

    plt.close()

    # ---------------------------------------------------------
    # RULE-BASED VS OPTIMIZED COMPARISON
    # ---------------------------------------------------------

    comparison_path = None

    if rule_based_results is not None:

        plt.figure()

        plt.plot(
            optimized_results["hour"],
            optimized_results["load_mw"],
            label="Original Load",
        )

        plt.plot(
            rule_based_results["hour"],
            rule_based_results[
                "grid_power_after_bess_mw"
            ],
            label="Rule-Based Dispatch",
        )

        plt.plot(
            optimized_results["hour"],
            optimized_results[
                "grid_power_mw"
            ],
            label="Optimized Dispatch",
        )

        plt.xlabel("Hour")
        plt.ylabel("Grid Power (MW)")

        plt.title(
            "Rule-Based vs Optimized BESS Dispatch"
        )

        plt.grid(True)
        plt.legend()
        plt.tight_layout()

        comparison_path = (
            results_path
            / "dispatch_comparison.png"
        )

        plt.savefig(
            comparison_path,
            dpi=200,
        )

        plt.close()

    return {
        "csv":
            str(csv_path),

        "optimized_plot":
            str(optimized_plot_path),

        "optimized_soc":
            str(optimized_soc_path),

        "comparison_plot":
            (
                str(comparison_path)
                if comparison_path
                else None
            ),
    }