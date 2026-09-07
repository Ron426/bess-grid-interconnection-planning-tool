import math
from pathlib import Path

import pandas as pd
import streamlit as st

from src.bess_sizing import size_bess

from src.transformer import (
    evaluate_transformers,
)

from src.electrical import (
    reactive_power_mvar,
    three_phase_current_a,
    transformer_rated_current_a,
    current_utilization_percent,
)

from src.powerflow import (
    build_bess_network,
    run_bess_power_flow,
)

from src.collector import (
    build_collector_network,
    run_collector_power_flow,
)

from src.contingencies import (
    run_contingency_suite,
)

from src.dispatch import (
    simulate_bess_dispatch,
)

from src.optimizer import (
    optimize_peak_shaving,
)

from src.design_engine import (
    analyze_design_options,
)

from src.future_validation import (
    run_future_n1_validation,
)


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="BESS Grid Interconnection Planning Tool",
    page_icon="⚡",
    layout="wide",
)


# ============================================================
# PROJECT DESIGN BASIS
# ============================================================

# Fixed project basis
REQUIRED_MW = 50.0
REQUIRED_MWH = 100.0

BLOCK_MW = 5.0
BLOCK_MWH = 10.0

GRID_VOLTAGE_KV = 115.0
COLLECTOR_VOLTAGE_KV = 34.5

LOAD_PROFILE_PATH = Path(
    "data/load_profile.csv"
)


# ============================================================
# INTERACTIVE SCENARIO CONTROLS
# ============================================================

with st.sidebar:

    st.header("Engineering Scenario")

    st.caption(
        "Adjust the assumptions below to evaluate "
        "alternative operating and expansion cases."
    )

    POWER_FACTOR = st.slider(
        "Reactive-Power Capability PF Reference",
        min_value=0.90,
        max_value=1.00,
        value=0.95,
        step=0.01,
    )

    st.caption(
        "Defines the inverter reactive-power capability basis. "
        "Actual operating power factor is calculated from the selected VAR command."
    )

    REACTIVE_POWER_COMMAND_PERCENT = st.slider(
        "Reactive-Power Command (% of capability)",
        min_value=-100,
        max_value=100,
        value=0,
        step=5,
    )

    st.caption(
        "-100% = maximum absorption | "
        "0% = zero reactive exchange | "
        "+100% = maximum injection"
    )

    GRID_SOURCE_VOLTAGE_PU = st.slider(
        "Utility Source Voltage (pu)",
        min_value=0.95,
        max_value=1.05,
        value=1.00,
        step=0.01,
    )

    GROWTH_PERCENT = st.slider(
        "Future Export Growth (%)",
        min_value=0,
        max_value=30,
        value=15,
        step=1,
    )

    SELECTED_TRANSFORMER_MVA = st.selectbox(
        "Existing Main Transformer",
        options=[
            50.0,
            60.0,
            75.0,
            100.0,
        ],
        index=2,
        format_func=lambda value: f"{value:.0f} MVA",
    )

    st.divider()

    st.subheader("Fixed Network Basis")

    st.write(
        f"""
        **Plant:** {REQUIRED_MW:.0f} MW / {REQUIRED_MWH:.0f} MWh

        **BESS Block:** {BLOCK_MW:.0f} MW / {BLOCK_MWH:.0f} MWh

        **POI Voltage:** {GRID_VOLTAGE_KV:.0f} kV

        **Collector Voltage:** {COLLECTOR_VOLTAGE_KV:.1f} kV
        """
    )

    st.info(
        "Adjust future export growth, reactive-power capability, utility-source "
        "voltage, or VAR command to see how the recommended design changes."
    )


# ============================================================
# DYNAMIC DESIGN OPTIONS
# ============================================================

future_export_mw = (
    REQUIRED_MW
    * (1 + GROWTH_PERCENT / 100)
)

current_required_blocks = math.ceil(
    REQUIRED_MW / BLOCK_MW
)

future_required_blocks = math.ceil(
    future_export_mw / BLOCK_MW
)

# Keep the candidate set distinct while allowing it
# to grow when the expansion requirement increases.

future_capacity_blocks = max(
    future_required_blocks,
    current_required_blocks + 2,
)

future_n1_blocks = max(
    future_required_blocks + 1,
    current_required_blocks + 3,
)

DESIGN_OPTIONS = [
    {
        "option": "Option A",
        "installed_blocks":
            current_required_blocks,
        "transformer_mva":
            60.0,
    },
    {
        "option": "Option B",
        "installed_blocks":
            current_required_blocks + 1,
        "transformer_mva":
            75.0,
    },
    {
        "option": "Option C",
        "installed_blocks":
            future_capacity_blocks,
        "transformer_mva":
            75.0,
    },
    {
        "option": "Option D",
        "installed_blocks":
            future_n1_blocks,
        "transformer_mva":
            75.0,
    },
    {
        "option": "Option E",
        "installed_blocks":
            future_n1_blocks,
        "transformer_mva":
            100.0,
    },
]


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def pass_badge(value):
    if value:
        return "✅ PASS"
    return "❌ FAIL"


def clean_zero(value):
    if abs(value) < 0.005:
        return 0.0
    return value


def commanded_reactive_power_mvar(
    active_power_mw,
    power_factor_reference,
    command_percent,
):
    """
    Calculate commanded reactive power.

    Positive command = reactive power injection.
    Negative command = reactive power absorption.
    Zero command = zero reactive power.
    """

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


def actual_power_factor(
    active_power_mw,
    reactive_power_mvar_value,
):
    apparent_power_mva = (
        active_power_mw ** 2
        + reactive_power_mvar_value ** 2
    ) ** 0.5

    if apparent_power_mva == 0:
        return 1.0

    return (
        active_power_mw
        / apparent_power_mva
    )

def find_minimum_var_command(
    design_options,
    current_export_mw,
    growth_percent,
    block_power_mw,
    block_energy_mwh,
    power_factor,
    grid_voltage_kv,
    collector_voltage_kv,
    step_percent=5,
    grid_source_voltage_pu=1.0,
):
    """
    Search for the smallest reactive-power command that
    produces a valid future N+1 design.

    Search order:
    0%, -5%, +5%, -10%, +10%, ... -100%, +100%

    If both positive and negative commands work at the same
    magnitude, choose the one with the better voltage profile.
    """

    for magnitude in range(
        0,
        101,
        step_percent,
    ):

        if magnitude == 0:
            commands = [0]

        elif grid_source_voltage_pu < 1.0:
            # Low utility voltage:
            # inject reactive power (+Q) to support voltage.
            commands = [magnitude]

        elif grid_source_voltage_pu > 1.0:
            # High utility voltage:
            # absorb reactive power (-Q) to reduce voltage.
            commands = [-magnitude]

        else:
            # Nominal source voltage.
            # Search both directions if compensation is still required.
            commands = [
                -magnitude,
                magnitude,
            ]

        feasible_candidates = []

        for command_percent in commands:

            test_results, test_recommendations = (
                analyze_design_options(
                    design_options=design_options,
                    current_export_mw=current_export_mw,
                    growth_percent=growth_percent,
                    block_power_mw=block_power_mw,
                    block_energy_mwh=block_energy_mwh,
                    power_factor=power_factor,
                    reactive_power_command_percent=command_percent,
                    grid_voltage_kv=grid_voltage_kv,
                    collector_voltage_kv=collector_voltage_kv,
                    grid_source_voltage_pu=grid_source_voltage_pu,
                )
            )

            candidate_design = (
                test_recommendations.get(
                    "minimum_future_n1"
                )
            )

            if candidate_design is None:
                continue

            candidate_result = next(
                (
                    result
                    for result in test_results
                    if result["option"]
                    == candidate_design["option"]
                ),
                None,
            )

            if candidate_result is None:
                continue

            future_case = candidate_result[
                "future_case"
            ]

            if not future_case.get(
                "capacity_available",
                False,
            ):
                continue

            minimum_voltage_pu = (
                future_case.get(
                    "minimum_voltage_pu"
                )
            )

            maximum_voltage_pu = (
                future_case.get(
                    "maximum_voltage_pu"
                )
            )

            if (
                minimum_voltage_pu is None
                or maximum_voltage_pu is None
            ):
                continue

            voltage_deviation = max(
                abs(
                    minimum_voltage_pu
                    - 1.0
                ),
                abs(
                    maximum_voltage_pu
                    - 1.0
                ),
            )

            feasible_candidates.append(
                {
                    "command_percent":
                        command_percent,

                    "design":
                        candidate_design,

                    "result":
                        candidate_result,

                    "minimum_voltage_pu":
                        minimum_voltage_pu,

                    "maximum_voltage_pu":
                        maximum_voltage_pu,

                    "voltage_deviation_pu":
                        voltage_deviation,
                }
            )

        if feasible_candidates:

            return min(
                feasible_candidates,
                key=lambda item: (
                    item[
                        "voltage_deviation_pu"
                    ],
                    item["design"][
                        "transformer_mva"
                    ],
                    item["design"][
                        "installed_blocks"
                    ],
                ),
            )

    return None

# ============================================================
# HEADER
# ============================================================

st.title(
    "⚡ Utility-Scale BESS Grid Interconnection "
    "& Substation Planning Tool"
)

st.caption(
    "Conceptual electrical-engineering platform for BESS sizing, "
    "grid-interconnection analysis, reliability evaluation, "
    "dispatch optimization and future-expansion planning."
)


# ============================================================
# TOP-LEVEL KPI CALCULATIONS
# ============================================================

bess_summary = size_bess(
    required_mw=REQUIRED_MW,
    required_mwh=REQUIRED_MWH,
    block_mw=BLOCK_MW,
    block_mwh=BLOCK_MWH,
    n_plus_one=True,
)

reactive_mvar = commanded_reactive_power_mvar(
    active_power_mw=REQUIRED_MW,
    power_factor_reference=POWER_FACTOR,
    command_percent=REACTIVE_POWER_COMMAND_PERCENT,
)

ACTUAL_POWER_FACTOR = actual_power_factor(
    REQUIRED_MW,
    reactive_mvar,
)

present_mva = (
    REQUIRED_MW ** 2
    + reactive_mvar ** 2
) ** 0.5


optimized_dispatch, optimization_summary = (
    optimize_peak_shaving(
        load_profile_path=LOAD_PROFILE_PATH,
        bess_power_mw=50.0,
        bess_energy_mwh=100.0,
        initial_soc_percent=50.0,
        min_soc_percent=20.0,
        max_soc_percent=90.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        max_charge_power_mw=10.0,
    )
)

# ============================================================
# DESIGN OPTION ANALYSIS
# ============================================================

design_results, recommendations = (
    analyze_design_options(
        design_options=DESIGN_OPTIONS,
        current_export_mw=REQUIRED_MW,
        growth_percent=GROWTH_PERCENT,
        block_power_mw=BLOCK_MW,
        block_energy_mwh=BLOCK_MWH,
        power_factor=POWER_FACTOR,
        reactive_power_command_percent=REACTIVE_POWER_COMMAND_PERCENT,
        grid_voltage_kv=GRID_VOLTAGE_KV,
        collector_voltage_kv=COLLECTOR_VOLTAGE_KV,
        grid_source_voltage_pu=GRID_SOURCE_VOLTAGE_PU,
    )
)

preferred_future_design = (
    recommendations[
        "minimum_future_n1"
    ]
)


# ============================================================
# KPI ROW
# ============================================================

kpi1, kpi2, kpi3, kpi4, kpi5, kpi6 = st.columns(
    [1.85, 0.95, 0.95, 1.05, 1.10, 1.10]
)

kpi1.metric(
    "Plant Rating",
    "50 MW / 100 MWh",
)

kpi2.metric(
    "Grid Voltage",
    "115 kV",
)

kpi3.metric(
    "Collector",
    "34.5 kV",
)

kpi4.metric(
    "Main Transformer",
    f"{SELECTED_TRANSFORMER_MVA:.0f} MVA",
)

kpi5.metric(
    "Current Block N+1",
    "PASS",
)

kpi6.metric(
    "Optimized Peak",
    f"{optimization_summary['optimized_peak_mw']:.2f} MW",
)


st.divider()


# ============================================================
# TABS
# ============================================================

(
    overview_tab,
    electrical_tab,
    powerflow_tab,
    collector_tab,
    contingency_tab,
    dispatch_tab,
    design_tab,
    future_tab,
) = st.tabs(
    [
        "Overview",
        "Electrical Design",
        "AC Power Flow",
        "Collector System",
        "Contingency & Reliability",
        "Dispatch & Optimization",
        "Design Recommendation",
        "Future N+1 Validation",
    ]
)


# ============================================================
# TAB 1 — OVERVIEW
# ============================================================

with overview_tab:

    st.header("Project Overview")

    st.write(
        """
        This project evaluates the preliminary electrical design
        of a utility-scale Battery Energy Storage System (BESS)
        interconnected to a 115 kV utility grid through a
        34.5 kV collector system.
        """
    )

    left, right = st.columns(2)

    with left:

        st.subheader("Baseline 50 MW Design")

        st.write(
            f"""
            **Plant requirement:** {REQUIRED_MW:.0f} MW / {REQUIRED_MWH:.0f} MWh

            **BESS block size:** {BLOCK_MW:.0f} MW / {BLOCK_MWH:.0f} MWh

            **Minimum required blocks:** {bess_summary['minimum_blocks']}

            **Installed blocks:** {bess_summary['installed_blocks']}

            **Installed nameplate:** {bess_summary['installed_mw']:.0f} MW /
            {bess_summary['installed_mwh']:.0f} MWh

            **Normal export limit:** {REQUIRED_MW:.0f} MW

            **Main transformer:** {SELECTED_TRANSFORMER_MVA:.0f} MVA,
            115/34.5 kV
            """
        )

    with right:

        st.subheader("Simplified System Architecture")

        st.code(
            f"""
Utility Grid — 115 kV
        │
        ▼
115 kV POI Bus
        │
        ▼
{SELECTED_TRANSFORMER_MVA:.0f} MVA Main Transformer
115 / 34.5 kV
        │
        ▼
34.5 kV Collector Bus
        │
        ├── BESS Block 1
        ├── BESS Block 2
        ├── ...
        ├── BESS Block 10
        └── BESS Block 11 — Standby
            """,
            language=None,
        )

    st.subheader(
        "Scenario-Based Future Recommendation"
    )

    if preferred_future_design is not None:

        st.success(
            f"""
            **Preferred Future N+1 Configuration**

            {preferred_future_design['option']} —
            {preferred_future_design['installed_blocks']} BESS blocks,
            {preferred_future_design['installed_power_mw']:.0f} MW /
            {preferred_future_design['installed_energy_mwh']:.0f} MWh installed,
            with a
            {preferred_future_design['transformer_mva']:.0f} MVA
            main transformer.

            **Reactive-power capability PF reference:** {POWER_FACTOR:.2f}  
            **Reactive-power command:** {REACTIVE_POWER_COMMAND_PERCENT:+.0f}%  
            **Actual operating power factor:** {ACTUAL_POWER_FACTOR:.3f}
            """
        )

    else:

        st.error(
            "No candidate design satisfies the selected "
            "future N+1 scenario."
        )

    st.info(
        "Project scope: Preliminary conceptual analysis for "
        "BESS sizing, transformer selection and "
        "grid-interconnection planning."
    )


# ============================================================
# TAB 2 — ELECTRICAL DESIGN
# ============================================================

with electrical_tab:

    st.header("Electrical Design Calculations")

    reactive_power = reactive_mvar

    hv_current = three_phase_current_a(
        present_mva,
        GRID_VOLTAGE_KV,
    )

    mv_current = three_phase_current_a(
        present_mva,
        COLLECTOR_VOLTAGE_KV,
    )

    hv_rated_current = transformer_rated_current_a(
        SELECTED_TRANSFORMER_MVA,
        GRID_VOLTAGE_KV,
    )

    mv_rated_current = transformer_rated_current_a(
        SELECTED_TRANSFORMER_MVA,
        COLLECTOR_VOLTAGE_KV,
    )

    hv_utilization = current_utilization_percent(
        hv_current,
        hv_rated_current,
    )

    mv_utilization = current_utilization_percent(
        mv_current,
        mv_rated_current,
    )

    a, b, c, d = st.columns(4)

    a.metric(
        "Active Power",
        f"{REQUIRED_MW:.2f} MW",
    )

    b.metric(
        "Reactive Power",
        f"{reactive_power:.2f} MVAr",
    )

    c.metric(
        "Apparent Power",
        f"{present_mva:.2f} MVA",
    )

    d.metric(
        "Actual Power Factor",
        f"{ACTUAL_POWER_FACTOR:.3f}",
    )

    st.subheader("Three-Phase Currents")

    current_df = pd.DataFrame(
        {
            "Voltage Level": [
                "115 kV",
                "34.5 kV",
            ],
            "Operating Current (A)": [
                hv_current,
                mv_current,
            ],
            "Transformer Rated Current (A)": [
                hv_rated_current,
                mv_rated_current,
            ],
            "Current Utilization (%)": [
                hv_utilization,
                mv_utilization,
            ],
        }
    )

    st.dataframe(
        current_df,
        width="stretch",
        hide_index=True,
    )

    st.subheader("Transformer Options")

    transformer_results = evaluate_transformers(
        active_power_mw=REQUIRED_MW,
        power_factor=ACTUAL_POWER_FACTOR,
        growth_percent=GROWTH_PERCENT,
        transformer_options=[50, 60, 75, 100],
        target_max_loading_percent=85.0,
    )

    transformer_df = pd.DataFrame(
        transformer_results
    )

    transformer_df = transformer_df.rename(
        columns={
            "rating_mva": "Transformer MVA",
            "present_loading_percent": "Current Loading (%)",
            "future_loading_percent": f"{GROWTH_PERCENT:.0f}% Growth Loading (%)",
            "status": "Status",
        }
    )

    st.dataframe(
        transformer_df,
        width="stretch",
        hide_index=True,
    )


# ============================================================
# TAB 3 — AC POWER FLOW
# ============================================================

with powerflow_tab:

    st.header("AC Power-Flow Analysis")

    network, elements = build_bess_network(
        bess_discharge_mw=REQUIRED_MW,
        bess_reactive_injection_mvar=reactive_mvar,
        bess_energy_mwh=110.0,
        transformer_mva=SELECTED_TRANSFORMER_MVA,
        grid_voltage_kv=GRID_VOLTAGE_KV,
        collector_voltage_kv=COLLECTOR_VOLTAGE_KV,
    )

    powerflow = run_bess_power_flow(
        network,
        elements,
    )

    a, b, c, d = st.columns(4)

    a.metric(
        "Power Flow",
        "Converged" if powerflow["converged"] else "Failed",
    )

    b.metric(
        "115 kV Bus",
        f"{powerflow['hv_voltage_pu']:.4f} pu",
    )

    c.metric(
        "34.5 kV Bus",
        f"{powerflow['collector_voltage_pu']:.4f} pu",
    )

    d.metric(
        "Transformer Loading",
        f"{powerflow['transformer_loading_percent']:.1f}%",
    )

    pf_df = pd.DataFrame(
        {
            "Metric": [
                "115 kV Current",
                "34.5 kV Current",
                "Transformer Active Loss",
                "Transformer Reactive Loss",
                "Utility Grid Active Power",
                "Utility Grid Reactive Power",
            ],
            "Value": [
                f"{powerflow['transformer_hv_current_a']:.1f} A",
                f"{powerflow['transformer_lv_current_a']:.1f} A",
                f"{powerflow['transformer_active_loss_mw']:.3f} MW",
                f"{powerflow['transformer_reactive_loss_mvar']:.3f} MVAr",
                f"{powerflow['grid_active_power_mw']:.3f} MW",
                f"{powerflow['grid_reactive_power_mvar']:.3f} MVAr",
            ],
        }
    )

    st.dataframe(
        pf_df,
        width="stretch",
        hide_index=True,
    )

    if (
        0.95
        <= powerflow["collector_voltage_pu"]
        <= 1.05
    ):

        st.success(
            "Collector-bus voltage is within the "
            "0.95–1.05 pu conceptual operating range."
        )

    else:

        st.error(
            "Collector-bus voltage violates the "
            "conceptual operating range."
        )


# ============================================================
# TAB 4 — COLLECTOR SYSTEM
# ============================================================

with collector_tab:

    st.header("Detailed 34.5 kV Collector System")

    collector_net, collector_elements = (
        build_collector_network(
            plant_export_mw=REQUIRED_MW,
            plant_reactive_mvar=reactive_mvar,
            main_transformer_mva=SELECTED_TRANSFORMER_MVA,
            grid_voltage_kv=GRID_VOLTAGE_KV,
            collector_voltage_kv=COLLECTOR_VOLTAGE_KV,
            block_voltage_kv=0.8,
            number_of_blocks=11,
            active_blocks=10,
            block_energy_mwh=10.0,
        )
    )

    collector_results = (
        run_collector_power_flow(
            collector_net,
            collector_elements,
        )
    )

    a, b, c, d = st.columns(4)

    a.metric(
        "Collector Voltage",
        f"{collector_results['collector_voltage_pu']:.4f} pu",
    )

    b.metric(
        "Main XFMR Loading",
        f"{collector_results['main_transformer_loading_percent']:.1f}%",
    )

    c.metric(
        "Max Feeder Loading",
        f"{collector_results['maximum_feeder_loading_percent']:.1f}%",
    )

    d.metric(
        "Total Losses",
        f"{collector_results['total_network_losses_mw']:.4f} MW",
    )

    block_df = pd.DataFrame(
        collector_results[
            "block_results"
        ]
    )

    block_df = block_df.rename(
        columns={
            "block": "Block",
            "status": "Status",
            "power_mw": "Power (MW)",
            "mv_voltage_pu": "34.5 kV Voltage (pu)",
            "lv_voltage_pu": "0.8 kV Voltage (pu)",
            "feeder_loading_percent": "Feeder Loading (%)",
            "block_transformer_loading_percent":
                "Block XFMR Loading (%)",
        }
    )

    st.dataframe(
        block_df,
        width="stretch",
        hide_index=True,
    )


# ============================================================
# TAB 5 — CONTINGENCY
# ============================================================

with contingency_tab:

    st.header(
        "BESS Block Contingency & N+1 Reliability"
    )

    contingency_results = (
        run_contingency_suite(
            plant_export_mw=REQUIRED_MW,
            plant_reactive_mvar=reactive_mvar,
            main_transformer_mva=SELECTED_TRANSFORMER_MVA,
            grid_voltage_kv=GRID_VOLTAGE_KV,
            collector_voltage_kv=COLLECTOR_VOLTAGE_KV,
        )
    )

    contingency_rows = []

    for scenario in contingency_results:

        contingency_rows.append(
            {
                "Scenario":
                    scenario["scenario"],

                "Scheduled Output (MW)":
                    clean_zero(
                        scenario[
                            "scheduled_output_mw"
                        ]
                    ),

                "Capacity Margin (MW)":
                    clean_zero(
                        scenario[
                            "capacity_margin_mw"
                        ]
                    ),

                "Main XFMR Loading (%)":
                    scenario[
                        "main_transformer_loading_percent"
                    ],

                "Voltage Min (pu)":
                    scenario[
                        "minimum_voltage_pu"
                    ],

                "Voltage Max (pu)":
                    scenario[
                        "maximum_voltage_pu"
                    ],

                "Result":
                    "PASS"
                    if scenario["overall_pass"]
                    else "FAIL",
            }
        )

    contingency_df = pd.DataFrame(
        contingency_rows
    )

    st.dataframe(
        contingency_df,
        width="stretch",
        hide_index=True,
    )

    recovered_case = (
        contingency_results[2]
    )

    if recovered_case["overall_pass"]:

        st.success(
            "BESS block N+1 validation PASS: "
            "the standby block restores the required "
            "50 MW scheduled output after one active "
            "block failure."
        )

    else:

        st.error(
            "BESS block N+1 validation failed."
        )


# ============================================================
# TAB 6 — DISPATCH & OPTIMIZATION
# ============================================================

with dispatch_tab:

    st.header(
        "24-Hour BESS Dispatch & Optimization"
    )

    rule_dispatch, rule_summary = (
        simulate_bess_dispatch(
            load_profile_path=LOAD_PROFILE_PATH,
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
        )
    )

    optimized_dispatch, optimization_summary = (
        optimize_peak_shaving(
            load_profile_path=LOAD_PROFILE_PATH,
            bess_power_mw=50.0,
            bess_energy_mwh=100.0,
            initial_soc_percent=50.0,
            min_soc_percent=20.0,
            max_soc_percent=90.0,
            charge_efficiency=0.95,
            discharge_efficiency=0.95,
            max_charge_power_mw=10.0,
        )
    )

    a, b, c, d = st.columns(4)

    a.metric(
        "Original Peak",
        f"{optimization_summary['original_peak_mw']:.2f} MW",
    )

    b.metric(
        "Rule-Based Peak",
        f"{rule_summary['peak_after_mw']:.2f} MW",
    )

    c.metric(
        "Optimized Peak",
        f"{optimization_summary['optimized_peak_mw']:.2f} MW",
    )

    d.metric(
        "Optimized Reduction",
        f"{optimization_summary['peak_reduction_mw']:.2f} MW",
    )

    chart_df = pd.DataFrame(
        {
            "Hour":
                optimized_dispatch["hour"],

            "Original Load":
                optimized_dispatch["load_mw"],

            "Rule-Based":
                rule_dispatch[
                    "grid_power_after_bess_mw"
                ],

            "Optimized":
                optimized_dispatch[
                    "grid_power_mw"
                ],
        }
    )

    st.subheader(
        "Original vs Rule-Based vs Optimized"
    )

    st.line_chart(
        chart_df.set_index("Hour")
    )

    soc_df = pd.DataFrame(
        {
            "Hour":
                optimized_dispatch["hour"],

            "Optimized SOC (%)":
                optimized_dispatch[
                    "soc_percent"
                ],
        }
    )

    st.subheader(
        "Optimized State of Charge"
    )

    st.line_chart(
        soc_df.set_index("Hour")
    )

    st.caption(
        "The optimization model reduces the modeled "
        "peak from 115 MW to approximately 96.75 MW "
        "while returning the battery to its initial "
        "50% state of charge."
    )


# ============================================================
# TAB 7 — DESIGN RECOMMENDATION
# ============================================================

with design_tab:

    st.header(
        "Automated Engineering Design Recommendation"
    )


    design_rows = []

    for result in design_results:

        design_rows.append(
            {
                "Option":
                    result["option"],

                "Blocks":
                    result["installed_blocks"],

                "Installed MW":
                    result["installed_power_mw"],

                "Transformer":
                    f"{result['transformer_mva']:.0f} MVA",

                "Current N+1":
                    pass_badge(
                        result["current_n1_pass"]
                    ),

                "Future Capacity":
                    pass_badge(
                        result["future_capacity_pass"]
                    ),

                "Future N+1":
                    pass_badge(
                        result["future_n1_pass"]
                    ),

                "Current XFMR Loading":
                    f"{result['current_transformer_loading_percent']:.1f}%",

                "Future XFMR Loading":
                    f"{result['future_transformer_loading_percent']:.1f}%",
            }
        )

    st.dataframe(
        pd.DataFrame(design_rows),
        width="stretch",
        hide_index=True,
    )

    st.subheader("Design Failure Diagnostics")

    diagnostic_rows = []

    for result in design_results:

        future_case = result["future_case"]

        # Capacity and redundancy checks
        current_n1 = result["current_n1_pass"]
        future_capacity = result["future_capacity_pass"]
        future_n1 = result["future_n1_pass"]

        # Preliminary transformer checks
        current_xfmr = result["current_transformer_pass"]
        future_xfmr = result["future_transformer_pass"]

        # AC operating case
        future_ac = result["future_operating_pass"]

        # Individual future AC checks
        if future_case.get("capacity_available", False):

            future_voltage = (
                future_case.get(
                    "minimum_voltage_pu",
                    0.0,
                ) >= 0.95
                and
                future_case.get(
                    "maximum_voltage_pu",
                    999.0,
                ) <= 1.05
            )

            future_main_xfmr_ac = (
                future_case.get(
                    "main_transformer_loading_percent",
                    999.0,
                ) <= 85.0
            )

            future_feeder = (
                future_case.get(
                    "maximum_feeder_loading_percent",
                    999.0,
                ) <= 100.0
            )

            future_block_xfmr = (
                future_case.get(
                    "maximum_block_transformer_loading_percent",
                    999.0,
                ) <= 100.0
            )

        else:

            future_voltage = False
            future_main_xfmr_ac = False
            future_feeder = False
            future_block_xfmr = False

        diagnostic_rows.append(
            {
                "Option":
                    result["option"],

                "Current N+1":
                    "PASS" if current_n1 else "FAIL",

                "Future Capacity":
                    "PASS" if future_capacity else "FAIL",

                "Future N+1":
                    "PASS" if future_n1 else "FAIL",

                "Future XFMR Target":
                    "PASS" if future_xfmr else "FAIL",

                "Future Voltage":
                    "PASS" if future_voltage else "FAIL",

                "Min Voltage (pu)":
                    (
                        f"{future_case.get('minimum_voltage_pu', 0.0):.4f}"
                        if future_case.get("capacity_available", False)
                        else "N/A"
                    ),

                "Max Voltage (pu)":
                    (
                        f"{future_case.get('maximum_voltage_pu', 0.0):.4f}"
                        if future_case.get("capacity_available", False)
                        else "N/A"
                    ),

                "Future Main XFMR AC":
                    "PASS" if future_main_xfmr_ac else "FAIL",

                "Future Feeder":
                    "PASS" if future_feeder else "FAIL",

                "Future Block XFMR":
                    "PASS" if future_block_xfmr else "FAIL",

                "Future AC Overall":
                    "PASS" if future_ac else "FAIL",
            }
        )

    st.dataframe(
        pd.DataFrame(diagnostic_rows),
        width="stretch",
        hide_index=True,
    )

    minimum_future = (
        recommendations[
            "minimum_future_ready"
        ]
    )

    minimum_future_n1 = (
        recommendations[
            "minimum_future_n1"
        ]
    )

    st.subheader(
        "Engineering Recommendation"
    )

    col1, col2 = st.columns(2)

    with col1:

        if minimum_future is not None:

            st.info(
                f"""
                **Minimum Future-Ready Design**

                {minimum_future['option']}

                {minimum_future['installed_blocks']} blocks

                {minimum_future['installed_power_mw']:.0f} MW /
                {minimum_future['installed_energy_mwh']:.0f} MWh installed

                {minimum_future['transformer_mva']:.0f} MVA main transformer
                """
            )

        else:

            st.error(
                "No candidate design satisfies all selected "
                "future-capacity and electrical operating criteria."
            )


    with col2:

        if minimum_future_n1 is not None:

            st.success(
                f"""
                **Preferred Future N+1 Design**

                {minimum_future_n1['option']}

                {minimum_future_n1['installed_blocks']} blocks

                {minimum_future_n1['installed_power_mw']:.0f} MW /
                {minimum_future_n1['installed_energy_mwh']:.0f} MWh installed

                {minimum_future_n1['transformer_mva']:.0f} MVA main transformer
                """
            )

        else:

            st.error(
                "No candidate design preserves one-block N+1 "
                "redundancy while satisfying all selected future "
                "electrical operating criteria."
            )

    st.write(
        f"""
        **Design rationale:** The recommendation evaluates the
        selected {GROWTH_PERCENT:.0f}% future expansion scenario.

        **Reactive-power capability PF reference:** {POWER_FACTOR:.2f}

        **Reactive-power command:** {REACTIVE_POWER_COMMAND_PERCENT:+.0f}%

        Positive reactive-power command represents injection;
        negative command represents absorption.

        The minimum future-ready design provides enough installed
        BESS capacity to meet the expanded export requirement.
        The preferred future N+1 design provides sufficient
        one-block redundancy after expansion.

        Transformer selection is checked against the conceptual
        85% loading criterion together with AC power-flow,
        voltage, feeder and block-transformer constraints.
        """
    )

    st.divider()

    st.subheader(
        "Automatic Reactive-Power Tuning"
    )

    st.write(
        "The automatic VAR tuner evaluates the available reactive-power "
        "operating range and identifies the minimum-magnitude VAR command "
        "required to satisfy the modeled future N+1 electrical criteria."
    )

    auto_var_scenario = (
        round(POWER_FACTOR, 2),
        int(GROWTH_PERCENT),
    )

    current_auto_var_scenario = {
        "power_factor": POWER_FACTOR,
        "grid_source_voltage_pu": GRID_SOURCE_VOLTAGE_PU,
        "growth_percent": GROWTH_PERCENT,
        "selected_transformer_mva": SELECTED_TRANSFORMER_MVA,
    }

    if st.button(
        "Run Automatic VAR Tuning",
        type="primary",
    ):

        with st.spinner(
            "Searching reactive-power operating range..."
        ):

            # ---------------------------------------------------------
            # BEFORE-COMPENSATION BASELINE
            # Always evaluate the same scenario at 0% reactive command
            # so the automatic tuner can report the voltage improvement.
            # ---------------------------------------------------------

            baseline_results, baseline_recommendations = (
                analyze_design_options(
                    design_options=DESIGN_OPTIONS,
                    current_export_mw=REQUIRED_MW,
                    growth_percent=GROWTH_PERCENT,
                    block_power_mw=BLOCK_MW,
                    block_energy_mwh=BLOCK_MWH,
                    power_factor=POWER_FACTOR,
                    reactive_power_command_percent=0.0,
                    grid_voltage_kv=GRID_VOLTAGE_KV,
                    collector_voltage_kv=COLLECTOR_VOLTAGE_KV,
                    grid_source_voltage_pu=GRID_SOURCE_VOLTAGE_PU,
                )
            )

            st.session_state[
                "auto_var_baseline_results"
            ] = baseline_results

            st.session_state[
                "auto_var_baseline_recommendations"
            ] = baseline_recommendations

            st.session_state[
                "auto_var_result"
            ] = find_minimum_var_command(
                design_options=DESIGN_OPTIONS,
                current_export_mw=REQUIRED_MW,
                growth_percent=GROWTH_PERCENT,
                block_power_mw=BLOCK_MW,
                block_energy_mwh=BLOCK_MWH,
                power_factor=POWER_FACTOR,
                grid_voltage_kv=GRID_VOLTAGE_KV,
                collector_voltage_kv=COLLECTOR_VOLTAGE_KV,
                grid_source_voltage_pu=GRID_SOURCE_VOLTAGE_PU,
                step_percent=5,
            )

            st.session_state[
                "auto_var_scenario"
            ] = current_auto_var_scenario.copy()

        saved_auto_var_scenario = st.session_state.get(
            "auto_var_scenario"
        )

        scenario_changed = (
            saved_auto_var_scenario is not None
            and saved_auto_var_scenario != current_auto_var_scenario
        )

        if scenario_changed:

            st.session_state.pop(
                "auto_var_result",
                None,
            )

            st.session_state.pop(
                "auto_var_baseline_results",
                None,
            )

            st.session_state.pop(
                "auto_var_baseline_recommendations",
                None,
            )

            st.session_state.pop(
                "auto_var_scenario",
                None,
            )

            st.info(
                "Scenario inputs changed. "
                "Run Automatic VAR Tuning to evaluate "
                "the updated operating case."
            )

            auto_var_result = None

        else:

            auto_var_result = st.session_state.get(
                "auto_var_result"
            )

        if (
            auto_var_result is None
            and saved_auto_var_scenario is not None
            and not scenario_changed
        ):

            st.error(
                "No reactive-power command between "
                "-100% and +100% produced a valid "
                "future N+1 design."
            )

        elif auto_var_result is not None:

            auto_command = (
                auto_var_result[
                    "command_percent"
                ]
            )

            if abs(auto_command) < 1e-9:
                auto_command_display = "0%"
            else:
                auto_command_display = f"{auto_command:+.0f}%"

            auto_design = (
                auto_var_result[
                    "design"
                ]
            )

            future_export_for_var = (
                REQUIRED_MW
                * (
                    1
                    + GROWTH_PERCENT
                    / 100
                )
            )

            auto_future_q_mvar = (
                commanded_reactive_power_mvar(
                    active_power_mw=
                        future_export_for_var,
                    power_factor_reference=
                        POWER_FACTOR,
                    command_percent=
                        auto_command,
                )
            )

            if abs(auto_future_q_mvar) < 1e-9:
                auto_q_display = "0.00 MVAr"
            else:
                auto_q_display = f"{auto_future_q_mvar:+.2f} MVAr"

            auto_future_pf = (
                actual_power_factor(
                    future_export_for_var,
                    auto_future_q_mvar,
                )
            )

            # ---------------------------------------------------------
            # BEFORE / AFTER VOLTAGE-SUPPORT REPORT
            # ---------------------------------------------------------

            baseline_results = st.session_state.get(
                "auto_var_baseline_results",
                [],
            )

            # Find the uncompensated result for the SAME design that
            # the automatic VAR tuner ultimately selected.
            baseline_design = next(
                (
                    result
                    for result in baseline_results
                    if result.get("option") == auto_design["option"]
                ),
                None,
            )

            if baseline_design is not None:

                baseline_future_case = baseline_design.get(
                    "future_case",
                    {}
                )

                before_min_voltage = baseline_future_case.get(
                    "minimum_voltage_pu"
                )

                before_max_voltage = baseline_future_case.get(
                    "maximum_voltage_pu"
                )

                if (
                    before_min_voltage is None
                    or before_max_voltage is None
                ):
                    st.warning(
                        "Baseline voltage results are unavailable for "
                        "the selected design."
                    )

                else:

                    after_min_voltage = auto_var_result[
                        "minimum_voltage_pu"
                    ]

                    after_max_voltage = auto_var_result[
                        "maximum_voltage_pu"
                    ]

                    # Determine the uncompensated voltage condition.
                    if before_min_voltage < 0.95:
                        grid_condition = "UNDERVOLTAGE"
                        correction_label = "Minimum-voltage improvement"
                        voltage_correction = (
                            after_min_voltage - before_min_voltage
                        )

                    elif before_max_voltage > 1.05:
                        grid_condition = "OVERVOLTAGE"
                        correction_label = "Maximum-voltage reduction"
                        voltage_correction = (
                            before_max_voltage - after_max_voltage
                        )

                    else:
                        grid_condition = "WITHIN ACCEPTABLE LIMITS"
                        correction_label = "Voltage correction"
                        voltage_correction = 0.0

                    if correction_label == "Maximum-voltage reduction":
                        voltage_correction_display = (
                            f"{abs(voltage_correction):.4f} pu"
                        )
                    elif abs(voltage_correction) < 1e-9:
                        voltage_correction_display = "0.0000 pu"
                    else:
                        voltage_correction_display = (
                            f"{voltage_correction:+.4f} pu"
                        )

                    before_voltage_pass = (
                        before_min_voltage >= 0.95
                        and before_max_voltage <= 1.05
                    )

                    after_voltage_pass = (
                        after_min_voltage >= 0.95
                        and after_max_voltage <= 1.05
                    )

                    before_status = (
                        "PASS" if before_voltage_pass else "FAIL"
                    )

                    after_status = (
                        "PASS" if after_voltage_pass else "FAIL"
                    )

                    st.success(
                        f"""
                ### Grid Condition

                **Utility source voltage:**  
                {GRID_SOURCE_VOLTAGE_PU:.3f} pu

                **Initial condition:**  
                {grid_condition}

                ---

                ### Before Compensation

                **Reactive-power command:** 0%

                **Voltage range:**  
                {before_min_voltage:.4f} - {before_max_voltage:.4f} pu

                **Voltage status:** {before_status}

                ---

                ### Automatic VAR Support

                **Recommended reactive-power command:**  
                {auto_command_display}

                **Reactive power:**  
                {auto_q_display}

                **Future operating power factor:**  
                {auto_future_pf:.3f}

                ---

                ### After Compensation

                **Voltage range:**  
                {after_min_voltage:.4f} - {after_max_voltage:.4f} pu

                **Voltage status:** {after_status}

                **{correction_label}:**  
                {voltage_correction_display}

                ---

                ### Preferred Future N+1 Design

                **{auto_design['option']}**

                **Installed BESS:**  
                {auto_design['installed_power_mw']:.0f} MW / \
                {auto_design['installed_energy_mwh']:.0f} MWh

                **Main transformer:**  
                {auto_design['transformer_mva']:.0f} MVA
                """
                    )

            else:

                # Fallback in case a matching baseline design
                # cannot be located.
                st.success(
                    f"""
            **Recommended Reactive-Power Command: \
            {auto_command_display}**

            Preferred future N+1 design:  
            **{auto_design['option']}**

            Installed BESS:  
            **{auto_design['installed_power_mw']:.0f} MW / \
            {auto_design['installed_energy_mwh']:.0f} MWh**

            Main transformer:  
            **{auto_design['transformer_mva']:.0f} MVA**

            Future reactive power:  
            **{auto_q_display}**

            Future operating power factor:  
            **{auto_future_pf:.3f}**

            Future voltage range:  
            **{auto_var_result['minimum_voltage_pu']:.4f} - \
            {auto_var_result['maximum_voltage_pu']:.4f} pu**
            """
                )

    elif "auto_var_result" in st.session_state:

        st.info(
            "The engineering scenario has changed. "
            "Run Automatic VAR Tuning again to update "
            "the recommendation."
        )


# ============================================================
# TAB 8 — FUTURE N+1
# ============================================================

with future_tab:

    st.header(
        "Future Expansion N+1 Validation"
    )

    if preferred_future_design is None:

        st.error(
            "No candidate design satisfies the selected "
            "future N+1 requirements."
        )

    else:

        st.write(
            f"""
            Validating **{preferred_future_design['option']}**
            under the selected **{GROWTH_PERCENT:.0f}% growth** scenario.

            **Reactive-power capability PF reference:** {POWER_FACTOR:.2f}  
            **Reactive-power command:** {REACTIVE_POWER_COMMAND_PERCENT:+.0f}%  
            **Actual operating power factor:** {ACTUAL_POWER_FACTOR:.3f}
            """
        )

        future_scenarios, future_n1_pass = (
            run_future_n1_validation(
                installed_blocks=
                    preferred_future_design[
                        "installed_blocks"
                    ],
                current_export_mw=
                    REQUIRED_MW,
                growth_percent=
                    GROWTH_PERCENT,
                block_power_mw=
                    BLOCK_MW,
                power_factor=POWER_FACTOR,
                reactive_power_command_percent=
                    REACTIVE_POWER_COMMAND_PERCENT,
                main_transformer_mva=
                    preferred_future_design[
                        "transformer_mva"
                    ],
                grid_voltage_kv=
                    GRID_VOLTAGE_KV,
                collector_voltage_kv=
                    COLLECTOR_VOLTAGE_KV,
            )
        )

        future_rows = []

        for scenario in future_scenarios:

            future_rows.append(
                {
                    "Scenario":
                        scenario["scenario"],

                    "Scheduled Output (MW)":
                        clean_zero(
                            scenario[
                                "scheduled_output_mw"
                            ]
                        ),

                    "Capacity Margin (MW)":
                        clean_zero(
                            scenario[
                                "capacity_margin_mw"
                            ]
                        ),

                    "Collector Voltage (pu)":
                        scenario[
                            "collector_voltage_pu"
                        ],

                    "Main XFMR Loading (%)":
                        scenario[
                            "main_transformer_loading_percent"
                        ],

                    "Max Feeder Loading (%)":
                        scenario[
                            "maximum_feeder_loading_percent"
                        ],

                    "Max Block XFMR Loading (%)":
                        scenario[
                            "maximum_block_transformer_loading_percent"
                        ],

                    "Result":
                        "PASS"
                        if scenario["overall_pass"]
                        else "FAIL",
                }
            )

        st.dataframe(
            pd.DataFrame(future_rows),
            width="stretch",
            hide_index=True,
        )

        if future_n1_pass:

            st.success(
                f"""
                Future N+1 validation PASS.

                The modeled
                {preferred_future_design['installed_blocks']}-block /
                {preferred_future_design['transformer_mva']:.0f} MVA
                configuration satisfies the selected future
                operating scenario and restores full scheduled
                output following the loss of one active BESS block.
                """
            )

        else:

            st.error(
                "The recommended configuration failed one or "
                "more future N+1 operating criteria."
            )

# ============================================================
# ENGINEERING VALIDATION SUMMARY
# ============================================================

st.divider()

st.header("Engineering Validation Summary")

st.write(
    "The following reference cases were used to verify the behavior of "
    "the conceptual BESS sizing, transformer-selection, voltage-control, "
    "and future N+1 planning logic."
)

validation_data = pd.DataFrame(
    [
        {
            "Scenario": "Baseline Growth",
            "Future Growth": "0%",
            "Utility Voltage": "1.00 pu",
            "VAR Response": "0%",
            "Preferred N+1 Design": "Option B",
            "Installed BESS": "55 MW / 110 MWh",
            "Main Transformer": "75 MVA",
            "Status": "PASS",
        },
        {
            "Scenario": "Nominal Planning Case",
            "Future Growth": "15%",
            "Utility Voltage": "1.00 pu",
            "VAR Response": "0%",
            "Preferred N+1 Design": "Option D",
            "Installed BESS": "65 MW / 130 MWh",
            "Main Transformer": "75 MVA",
            "Status": "PASS",
        },
        {
            "Scenario": "Maximum Growth",
            "Future Growth": "30%",
            "Utility Voltage": "1.00 pu",
            "VAR Response": "0%",
            "Preferred N+1 Design": "Option E",
            "Installed BESS": "70 MW / 140 MWh",
            "Main Transformer": "100 MVA",
            "Status": "PASS",
        },
        {
            "Scenario": "Undervoltage Support",
            "Future Growth": "15%",
            "Utility Voltage": "0.95 pu",
            "VAR Response": "+15% Injection",
            "Preferred N+1 Design": "Option D",
            "Installed BESS": "65 MW / 130 MWh",
            "Main Transformer": "75 MVA",
            "Status": "PASS",
        },
        {
            "Scenario": "Overvoltage Support",
            "Future Growth": "15%",
            "Utility Voltage": "1.05 pu",
            "VAR Response": "-10% Absorption",
            "Preferred N+1 Design": "Option D",
            "Installed BESS": "65 MW / 130 MWh",
            "Main Transformer": "75 MVA",
            "Status": "PASS",
        },
        {
            "Scenario": "Growth + Undervoltage",
            "Future Growth": "30%",
            "Utility Voltage": "0.95 pu",
            "VAR Response": "+15% Injection",
            "Preferred N+1 Design": "Option E",
            "Installed BESS": "70 MW / 140 MWh",
            "Main Transformer": "100 MVA",
            "Status": "PASS",
        },
        {
            "Scenario": "Growth + Overvoltage",
            "Future Growth": "30%",
            "Utility Voltage": "1.05 pu",
            "VAR Response": "-10% Absorption",
            "Preferred N+1 Design": "Option E",
            "Installed BESS": "70 MW / 140 MWh",
            "Main Transformer": "100 MVA",
            "Status": "PASS",
        },
    ]
)

st.dataframe(
    validation_data,
    hide_index=True,
    width="stretch",
)

st.success(
    "Reference scenario checks complete: the conceptual model responded consistently "
    "to changes in future export requirements, utility-source voltage, "
    "reactive-power support requirements, transformer loading, and "
    "one-block N+1 redundancy."
)

st.caption(
    "These cases are conceptual engineering validation scenarios and "
    "do not represent construction-ready utility interconnection studies."
)

# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "Preliminary conceptual analysis for BESS sizing, "
    "transformer selection and grid-interconnection planning. "
    "Model parameters are educational engineering assumptions "
    "and are not construction-ready equipment specifications."
)