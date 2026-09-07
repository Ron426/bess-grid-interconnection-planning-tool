from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def simulate_bess_dispatch(
    load_profile_path,
    bess_power_mw=50.0,
    bess_energy_mwh=100.0,
    initial_soc_percent=50.0,
    min_soc_percent=20.0,
    max_soc_percent=90.0,
    charge_efficiency=0.95,
    discharge_efficiency=0.95,
    peak_limit_mw=100.0,
    charge_threshold_mw=65.0,
    max_charge_power_mw=10.0,
    timestep_hours=1.0,
):
    """
    Simulate a simple 24-hour BESS dispatch strategy.

    Positive BESS power = discharging
    Negative BESS power = charging
    """

    # ---------------------------------------------------------
    # INPUT VALIDATION
    # ---------------------------------------------------------

    if bess_power_mw <= 0:
        raise ValueError("BESS power rating must be greater than zero.")

    if bess_energy_mwh <= 0:
        raise ValueError("BESS energy capacity must be greater than zero.")

    if not 0 <= min_soc_percent < max_soc_percent <= 100:
        raise ValueError("Invalid SOC limits.")

    if not min_soc_percent <= initial_soc_percent <= max_soc_percent:
        raise ValueError("Initial SOC must be within the SOC limits.")

    if not 0 < charge_efficiency <= 1:
        raise ValueError("Charge efficiency must be between 0 and 1.")

    if not 0 < discharge_efficiency <= 1:
        raise ValueError("Discharge efficiency must be between 0 and 1.")

    # ---------------------------------------------------------
    # LOAD PROFILE
    # ---------------------------------------------------------

    load_profile = pd.read_csv(load_profile_path)

    required_columns = {"hour", "load_mw"}

    if not required_columns.issubset(load_profile.columns):
        raise ValueError(
            "Load profile must contain 'hour' and 'load_mw' columns."
        )

    # ---------------------------------------------------------
    # ENERGY LIMITS
    # ---------------------------------------------------------

    minimum_energy_mwh = (
        bess_energy_mwh * min_soc_percent / 100
    )

    maximum_energy_mwh = (
        bess_energy_mwh * max_soc_percent / 100
    )

    stored_energy_mwh = (
        bess_energy_mwh * initial_soc_percent / 100
    )

    results = []

    # ---------------------------------------------------------
    # HOURLY DISPATCH
    # ---------------------------------------------------------

    for _, row in load_profile.iterrows():

        hour = int(row["hour"])
        load_mw = float(row["load_mw"])

        energy_before_mwh = stored_energy_mwh

        bess_power_mw_operating = 0.0
        operating_mode = "IDLE"

        # -----------------------------------------------------
        # DISCHARGE DURING PEAK DEMAND
        # -----------------------------------------------------

        if load_mw > peak_limit_mw:

            requested_discharge_mw = (
                load_mw - peak_limit_mw
            )

            available_discharge_mw = max(
                0.0,
                (
                    stored_energy_mwh
                    - minimum_energy_mwh
                )
                * discharge_efficiency
                / timestep_hours
            )

            actual_discharge_mw = min(
                requested_discharge_mw,
                bess_power_mw,
                available_discharge_mw,
            )

            bess_power_mw_operating = (
                actual_discharge_mw
            )

            stored_energy_mwh -= (
                actual_discharge_mw
                * timestep_hours
                / discharge_efficiency
            )

            if actual_discharge_mw > 0:
                operating_mode = "DISCHARGE"

        # -----------------------------------------------------
        # CHARGE DURING LOW-DEMAND HOURS
        # -----------------------------------------------------

        elif load_mw <= charge_threshold_mw:

            available_storage_space_mwh = max(
                0.0,
                maximum_energy_mwh
                - stored_energy_mwh
            )

            allowable_charge_power_mw = (
                available_storage_space_mwh
                / charge_efficiency
                / timestep_hours
            )

            actual_charge_mw = min(
                max_charge_power_mw,
                bess_power_mw,
                allowable_charge_power_mw,
            )

            bess_power_mw_operating = (
                -actual_charge_mw
            )

            stored_energy_mwh += (
                actual_charge_mw
                * timestep_hours
                * charge_efficiency
            )

            if actual_charge_mw > 0:
                operating_mode = "CHARGE"

        # -----------------------------------------------------
        # GRID POWER AFTER BESS RESPONSE
        # -----------------------------------------------------

        grid_power_after_bess_mw = (
            load_mw
            - bess_power_mw_operating
        )

        soc_before_percent = (
            energy_before_mwh
            / bess_energy_mwh
            * 100
        )

        soc_after_percent = (
            stored_energy_mwh
            / bess_energy_mwh
            * 100
        )

        results.append(
            {
                "hour": hour,
                "load_mw": load_mw,
                "mode": operating_mode,
                "bess_power_mw": bess_power_mw_operating,
                "grid_power_after_bess_mw":
                    grid_power_after_bess_mw,
                "energy_before_mwh":
                    energy_before_mwh,
                "energy_after_mwh":
                    stored_energy_mwh,
                "soc_before_percent":
                    soc_before_percent,
                "soc_after_percent":
                    soc_after_percent,
            }
        )

    results_df = pd.DataFrame(results)

    # ---------------------------------------------------------
    # SUMMARY RESULTS
    # ---------------------------------------------------------

    peak_before_mw = float(
        results_df["load_mw"].max()
    )

    peak_after_mw = float(
        results_df[
            "grid_power_after_bess_mw"
        ].max()
    )

    peak_reduction_mw = (
        peak_before_mw
        - peak_after_mw
    )

    total_discharge_mwh = float(
        results_df.loc[
            results_df["bess_power_mw"] > 0,
            "bess_power_mw",
        ].sum()
        * timestep_hours
    )

    total_charge_mwh = float(
        -results_df.loc[
            results_df["bess_power_mw"] < 0,
            "bess_power_mw",
        ].sum()
        * timestep_hours
    )

    summary = {
        "peak_before_mw":
            peak_before_mw,

        "peak_after_mw":
            peak_after_mw,

        "peak_reduction_mw":
            peak_reduction_mw,

        "minimum_soc_percent":
            float(
                results_df[
                    "soc_after_percent"
                ].min()
            ),

        "maximum_soc_percent":
            float(
                results_df[
                    "soc_after_percent"
                ].max()
            ),

        "final_soc_percent":
            float(
                results_df.iloc[-1][
                    "soc_after_percent"
                ]
            ),

        "total_charge_mwh":
            total_charge_mwh,

        "total_discharge_mwh":
            total_discharge_mwh,

        "charging_hours":
            int(
                (
                    results_df["mode"]
                    == "CHARGE"
                ).sum()
            ),

        "discharging_hours":
            int(
                (
                    results_df["mode"]
                    == "DISCHARGE"
                ).sum()
            ),
    }

    return results_df, summary


def save_dispatch_outputs(
    results_df,
    results_directory="results",
):
    """
    Save the dispatch table and graphs.
    """

    results_path = Path(results_directory)

    results_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ---------------------------------------------------------
    # SAVE CSV
    # ---------------------------------------------------------

    csv_path = (
        results_path
        / "dispatch_results.csv"
    )

    results_df.to_csv(
        csv_path,
        index=False,
    )

    # ---------------------------------------------------------
    # LOAD VS GRID POWER GRAPH
    # ---------------------------------------------------------

    plt.figure()

    plt.plot(
        results_df["hour"],
        results_df["load_mw"],
        marker="o",
        label="Original Load",
    )

    plt.plot(
        results_df["hour"],
        results_df[
            "grid_power_after_bess_mw"
        ],
        marker="o",
        label="Grid Power After BESS",
    )

    plt.axhline(
        100.0,
        linestyle="--",
        label="100 MW Peak Target",
    )

    plt.xlabel("Hour")
    plt.ylabel("Power (MW)")
    plt.title(
        "24-Hour Load Profile and BESS Peak Shaving"
    )
    plt.grid(True)
    plt.legend()
    plt.tight_layout()

    load_plot_path = (
        results_path
        / "load_vs_grid_power.png"
    )

    plt.savefig(
        load_plot_path,
        dpi=200,
    )

    plt.close()

    # ---------------------------------------------------------
    # SOC GRAPH
    # ---------------------------------------------------------

    plt.figure()

    plt.plot(
        results_df["hour"],
        results_df[
            "soc_after_percent"
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
        "BESS State of Charge Over 24 Hours"
    )
    plt.grid(True)
    plt.legend()
    plt.tight_layout()

    soc_plot_path = (
        results_path
        / "soc_profile.png"
    )

    plt.savefig(
        soc_plot_path,
        dpi=200,
    )

    plt.close()

    # ---------------------------------------------------------
    # BESS POWER GRAPH
    # ---------------------------------------------------------

    plt.figure()

    plt.bar(
        results_df["hour"],
        results_df["bess_power_mw"],
    )

    plt.axhline(
        0.0,
        linewidth=1,
    )

    plt.xlabel("Hour")
    plt.ylabel("BESS Power (MW)")
    plt.title(
        "BESS Charging and Discharging Schedule"
    )

    plt.tight_layout()

    bess_power_plot_path = (
        results_path
        / "bess_power_schedule.png"
    )

    plt.savefig(
        bess_power_plot_path,
        dpi=200,
    )

    plt.close()

    return {
        "csv":
            str(csv_path),

        "load_plot":
            str(load_plot_path),

        "soc_plot":
            str(soc_plot_path),

        "bess_power_plot":
            str(bess_power_plot_path),
    }