from src.bess_sizing import size_bess
from src.transformer import required_mva, evaluate_transformers
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
from src.contingencies import run_contingency_suite
from src.dispatch import (
    simulate_bess_dispatch,
    save_dispatch_outputs,
)
from src.optimizer import (
    optimize_peak_shaving,
    save_optimization_outputs,
)
from src.design_engine import (
    analyze_design_options,
    save_design_outputs,
)
from src.future_validation import (
    run_future_n1_validation,
)
# ---------------------------------------------------------
# VERSION 0.1 DESIGN BASIS
# ---------------------------------------------------------
REQUIRED_MW = 50.0
REQUIRED_MWH = 100.0
BLOCK_MW = 5.0
BLOCK_MWH = 10.0
POWER_FACTOR = 0.95
GROWTH_PERCENT = 15.0
TARGET_MAX_TRANSFORMER_LOADING = 85.0
TRANSFORMER_OPTIONS_MVA = [50, 60, 75, 100]
GRID_VOLTAGE_KV = 115.0
COLLECTOR_VOLTAGE_KV = 34.5
SELECTED_TRANSFORMER_MVA = 75.0

DESIGN_OPTIONS = [
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
        "installed_blocks": 13,
        "transformer_mva": 100.0,
    },
]

def main():
    print("=" * 64)
    print("UTILITY-SCALE BESS GRID INTERCONNECTION PLANNING TOOL")
    print("Version 0.9 - Future Expansion & N+1 AC Validation")
    print("=" * 64)

    bess = size_bess(
        required_mw=REQUIRED_MW,
        required_mwh=REQUIRED_MWH,
        block_mw=BLOCK_MW,
        block_mwh=BLOCK_MWH,
        n_plus_one=True,
    )

    print("\n1) BESS SIZING")
    print("-" * 64)
    print(f"Plant export requirement : {REQUIRED_MW:.1f} MW")
    print(f"Energy requirement       : {REQUIRED_MWH:.1f} MWh")
    print(f"Block size               : {BLOCK_MW:.1f} MW / {BLOCK_MWH:.1f} MWh")
    print(f"Minimum blocks required  : {bess['minimum_blocks']}")
    print(f"Installed blocks (N+1)   : {bess['installed_blocks']}")
    print(f"Installed nameplate      : {bess['installed_mw']:.1f} MW / {bess['installed_mwh']:.1f} MWh")
    print(f"Normal export limit      : {REQUIRED_MW:.1f} MW")
    print(f"Reserve blocks           : {bess['reserve_blocks']}")

    present_mva = required_mva(REQUIRED_MW, POWER_FACTOR)
    future_mw = REQUIRED_MW * (1 + GROWTH_PERCENT / 100)
    future_mva = required_mva(future_mw, POWER_FACTOR)

    print("\n2) APPARENT POWER REQUIREMENT")
    print("-" * 64)
    print(f"Present: {REQUIRED_MW:.1f} MW / {POWER_FACTOR:.2f} PF = {present_mva:.2f} MVA")
    print(f"Future (+{GROWTH_PERCENT:.0f}%): {future_mw:.1f} MW / {POWER_FACTOR:.2f} PF = {future_mva:.2f} MVA")

    evaluations = evaluate_transformers(
        active_power_mw=REQUIRED_MW,
        power_factor=POWER_FACTOR,
        growth_percent=GROWTH_PERCENT,
        transformer_options=TRANSFORMER_OPTIONS_MVA,
        target_max_loading_percent=TARGET_MAX_TRANSFORMER_LOADING,
    )

    print("\n3) TRANSFORMER OPTIONS")
    print("-" * 64)
    print(f"{'Rating':>10} | {'Present':>10} | {'+15% Growth':>12} | Status")
    print("-" * 64)

    recommended = None

    for item in evaluations:
        print(
            f"{item['rating_mva']:>8.0f} MVA | "
            f"{item['present_loading_percent']:>8.1f}% | "
            f"{item['future_loading_percent']:>10.1f}% | "
            f"{item['status']}"
        )
        if recommended is None and item["status"] == "RECOMMENDED":
            recommended = item

    print("\n4) ENGINEERING RECOMMENDATION")
    print("-" * 64)

    if recommended:
        print(f"Recommended main transformer: {recommended['rating_mva']:.0f} MVA")
        print(
            f"Reason: It keeps projected transformer loading at "
            f"{recommended['future_loading_percent']:.1f}%, below the "
            f"{TARGET_MAX_TRANSFORMER_LOADING:.0f}% conceptual design target."
        )
    else:
        print("No listed transformer satisfies the conceptual loading target.")
        print("Evaluate a larger transformer rating.")

    # ---------------------------------------------------------
    # THREE-PHASE ELECTRICAL ANALYSIS
    # ---------------------------------------------------------

    reactive_mvar = reactive_power_mvar(
        REQUIRED_MW,
        POWER_FACTOR
    )

    hv_current_a = three_phase_current_a(
        present_mva,
        GRID_VOLTAGE_KV
    )

    collector_current_a = three_phase_current_a(
        present_mva,
        COLLECTOR_VOLTAGE_KV
    )

    hv_rated_current_a = transformer_rated_current_a(
        SELECTED_TRANSFORMER_MVA,
        GRID_VOLTAGE_KV
    )

    collector_rated_current_a = transformer_rated_current_a(
        SELECTED_TRANSFORMER_MVA,
        COLLECTOR_VOLTAGE_KV
    )

    hv_utilization = current_utilization_percent(
        hv_current_a,
        hv_rated_current_a
    )

    collector_utilization = current_utilization_percent(
        collector_current_a,
        collector_rated_current_a
    )

    print("\n5) THREE-PHASE ELECTRICAL ANALYSIS")
    print("-" * 64)

    print(f"Active power              : {REQUIRED_MW:.2f} MW")
    print(f"Reactive power magnitude  : {reactive_mvar:.2f} MVAr")
    print(f"Apparent power            : {present_mva:.2f} MVA")
    print(f"Power factor              : {POWER_FACTOR:.2f}")

    print("\nOperating Currents")
    print(f"115 kV side               : {hv_current_a:.1f} A")
    print(f"34.5 kV collector side    : {collector_current_a:.1f} A")

    print("\n75 MVA Transformer Rated Currents")
    print(f"115 kV side               : {hv_rated_current_a:.1f} A")
    print(f"34.5 kV side              : {collector_rated_current_a:.1f} A")

    print("\nCurrent Utilization")
    print(f"115 kV side               : {hv_utilization:.1f}%")
    print(f"34.5 kV side              : {collector_utilization:.1f}%")

    # ---------------------------------------------------------
    # AC POWER-FLOW MODEL
    # ---------------------------------------------------------

    net, network_elements = build_bess_network(
        bess_discharge_mw=REQUIRED_MW,
        bess_reactive_injection_mvar=reactive_mvar,
        bess_energy_mwh=110.0,
        transformer_mva=SELECTED_TRANSFORMER_MVA,
        grid_voltage_kv=GRID_VOLTAGE_KV,
        collector_voltage_kv=COLLECTOR_VOLTAGE_KV,
    )

    powerflow_results = run_bess_power_flow(
        net,
        network_elements,
    )

    print("\n6) AC POWER-FLOW ANALYSIS")
    print("-" * 64)

    print(
        f"Power flow converged       : "
        f"{powerflow_results['converged']}"
    )

    print("\nBus Voltages")

    print(
        f"115 kV POI bus            : "
        f"{powerflow_results['hv_voltage_pu']:.4f} pu"
    )

    print(
        f"34.5 kV collector bus     : "
        f"{powerflow_results['collector_voltage_pu']:.4f} pu"
    )

    print("\nVoltage Angles")

    print(
        f"115 kV POI bus            : "
        f"{powerflow_results['hv_voltage_angle_deg']:.3f} deg"
    )

    print(
        f"34.5 kV collector bus     : "
        f"{powerflow_results['collector_voltage_angle_deg']:.3f} deg"
    )

    print("\nTransformer")

    print(
        f"Loading                   : "
        f"{powerflow_results['transformer_loading_percent']:.1f}%"
    )

    print(
        f"115 kV current            : "
        f"{powerflow_results['transformer_hv_current_a']:.1f} A"
    )

    print(
        f"34.5 kV current           : "
        f"{powerflow_results['transformer_lv_current_a']:.1f} A"
    )

    print(
        f"Active power loss         : "
        f"{powerflow_results['transformer_active_loss_mw']:.3f} MW"
    )

    print(
        f"Reactive power loss       : "
        f"{powerflow_results['transformer_reactive_loss_mvar']:.3f} MVAr"
    )

    print("\nUtility Grid Exchange")

    print(
        f"Grid active power         : "
        f"{powerflow_results['grid_active_power_mw']:.3f} MW"
    )

    print(
        f"Grid reactive power       : "
        f"{powerflow_results['grid_reactive_power_mvar']:.3f} MVAr"
    )

    # ---------------------------------------------------------
    # DETAILED 34.5 kV COLLECTOR SYSTEM
    # ---------------------------------------------------------

    detailed_net, collector_elements = build_collector_network(
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

    collector_results = run_collector_power_flow(
        detailed_net,
        collector_elements,
    )

    print("\n7) DETAILED 34.5 kV COLLECTOR SYSTEM")
    print("-" * 64)

    print(
        f"Power flow converged       : "
        f"{collector_results['converged']}"
    )

    print(f"Installed BESS blocks      : 11")
    print(f"Active BESS blocks         : 10")
    print(f"Standby BESS blocks        : 1")
    print(f"Active block output        : 5.00 MW")
    print(f"Total scheduled export     : {REQUIRED_MW:.2f} MW")

    print("\nCollector-System Results")

    print(
        f"Main collector voltage     : "
        f"{collector_results['collector_voltage_pu']:.4f} pu"
    )

    print(
        f"Main transformer loading   : "
        f"{collector_results['main_transformer_loading_percent']:.1f}%"
    )

    print(
        f"Maximum feeder loading     : "
        f"{collector_results['maximum_feeder_loading_percent']:.1f}%"
    )

    print(
        f"Maximum block XFMR loading : "
        f"{collector_results['maximum_block_transformer_loading_percent']:.1f}%"
    )

    print(
        f"Minimum BESS bus voltage   : "
        f"{collector_results['minimum_block_voltage_pu']:.4f} pu"
    )

    print(
        f"Maximum BESS bus voltage   : "
        f"{collector_results['maximum_block_voltage_pu']:.4f} pu"
    )

    print("\nNetwork Losses")

    print(
        f"Collector feeder losses    : "
        f"{collector_results['total_line_losses_mw']:.4f} MW"
    )

    print(
        f"Transformer losses         : "
        f"{collector_results['total_transformer_losses_mw']:.4f} MW"
    )

    print(
        f"Total modeled losses       : "
        f"{collector_results['total_network_losses_mw']:.4f} MW"
    )

    print(
        f"Utility grid active power  : "
        f"{collector_results['grid_active_power_mw']:.3f} MW"
    )

    print("\nIndividual BESS Blocks")

    print(
        f"{'Block':>5} | "
        f"{'Status':>8} | "
        f"{'MW':>6} | "
        f"{'LV Voltage':>10} | "
        f"{'Feeder':>8} | "
        f"{'XFMR':>8}"
    )

    print("-" * 64)

    for block in collector_results["block_results"]:

        print(
            f"{block['block']:>5} | "
            f"{block['status']:>8} | "
            f"{block['power_mw']:>6.2f} | "
            f"{block['lv_voltage_pu']:>8.4f} pu | "
            f"{block['feeder_loading_percent']:>6.1f}% | "
            f"{block['block_transformer_loading_percent']:>6.1f}%"
        )

    # ---------------------------------------------------------
    # CONTINGENCY & N+1 RELIABILITY ANALYSIS
    # ---------------------------------------------------------

    contingency_results = run_contingency_suite(
        plant_export_mw=REQUIRED_MW,
        plant_reactive_mvar=reactive_mvar,
        main_transformer_mva=SELECTED_TRANSFORMER_MVA,
        grid_voltage_kv=GRID_VOLTAGE_KV,
        collector_voltage_kv=COLLECTOR_VOLTAGE_KV,
    )

    print("\n8) CONTINGENCY & N+1 RELIABILITY ANALYSIS")
    print("-" * 64)

    for scenario in contingency_results:

        result_text = (
            "PASS"
            if scenario["overall_pass"]
            else "FAIL"
        )

        print(f"\n{scenario['scenario']}")
        print("-" * 64)

        print(
            f"Scheduled BESS output      : "
            f"{scenario['scheduled_output_mw']:.2f} MW"
        )

        print(
            f"Capacity margin            : "
            f"{scenario['capacity_margin_mw']:+.2f} MW"
        )

        print(
            f"Utility grid active power  : "
            f"{scenario['grid_active_power_mw']:.3f} MW"
        )

        print(
            f"Collector voltage          : "
            f"{scenario['collector_voltage_pu']:.4f} pu"
        )

        print(
            f"BESS voltage range         : "
            f"{scenario['minimum_voltage_pu']:.4f} - "
            f"{scenario['maximum_voltage_pu']:.4f} pu"
        )

        print(
            f"Main transformer loading   : "
            f"{scenario['main_transformer_loading_percent']:.1f}%"
        )

        print(
            f"Maximum feeder loading     : "
            f"{scenario['maximum_feeder_loading_percent']:.1f}%"
        )

        print(
            f"Maximum block XFMR loading : "
            f"{scenario['maximum_block_transformer_loading_percent']:.1f}%"
        )

        print(
            f"Total modeled losses       : "
            f"{scenario['network_losses_mw']:.4f} MW"
        )

        print(
            f"OVERALL RESULT             : "
            f"{result_text}"
        )

        if scenario["failed_checks"]:

            print(
                "Failed checks              : "
                + ", ".join(
                    scenario["failed_checks"]
                )
            )

    single_failure_recovered = contingency_results[2]

    print("\nBESS BLOCK N+1 RELIABILITY CONCLUSION")
    print("-" * 64)

    if single_failure_recovered["overall_pass"]:

        print(
            "PASS: The modeled system maintains the required "
            "50 MW scheduled output after one BESS block failure "
            "by activating the standby block."
        )

    else:

        print(
            "FAIL: The modeled system does not satisfy all "
            "design criteria after one BESS block failure."
        )

    # ---------------------------------------------------------
    # 24-HOUR BESS DISPATCH & SOC ANALYSIS
    # ---------------------------------------------------------

    dispatch_results, dispatch_summary = simulate_bess_dispatch(
        load_profile_path="data/load_profile.csv",
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

    saved_dispatch_files = save_dispatch_outputs(
        dispatch_results,
        results_directory="results",
    )

    print("\n9) 24-HOUR BESS DISPATCH & STATE-OF-CHARGE ANALYSIS")
    print("-" * 64)

    print(
        f"Original system peak       : "
        f"{dispatch_summary['peak_before_mw']:.1f} MW"
    )

    print(
        f"Peak after BESS            : "
        f"{dispatch_summary['peak_after_mw']:.1f} MW"
    )

    print(
        f"Peak reduction             : "
        f"{dispatch_summary['peak_reduction_mw']:.1f} MW"
    )

    print(
        f"Minimum SOC                : "
        f"{dispatch_summary['minimum_soc_percent']:.1f}%"
    )

    print(
        f"Maximum SOC                : "
        f"{dispatch_summary['maximum_soc_percent']:.1f}%"
    )

    print(
        f"Final SOC                  : "
        f"{dispatch_summary['final_soc_percent']:.1f}%"
    )

    print(
        f"Grid-side energy charged   : "
        f"{dispatch_summary['total_charge_mwh']:.2f} MWh"
    )

    print(
        f"Grid-side energy discharged: "
        f"{dispatch_summary['total_discharge_mwh']:.2f} MWh"
    )

    print(
        f"Charging hours             : "
        f"{dispatch_summary['charging_hours']}"
    )

    print(
        f"Discharging hours          : "
        f"{dispatch_summary['discharging_hours']}"
    )

    print("\nHourly Dispatch")

    print(
        f"{'Hr':>2} | "
        f"{'Load':>7} | "
        f"{'Mode':>9} | "
        f"{'BESS MW':>8} | "
        f"{'Grid MW':>8} | "
        f"{'SOC':>7}"
    )

    print("-" * 64)

    for _, row in dispatch_results.iterrows():

        print(
            f"{int(row['hour']):>2} | "
            f"{row['load_mw']:>7.1f} | "
            f"{row['mode']:>9} | "
            f"{row['bess_power_mw']:>8.2f} | "
            f"{row['grid_power_after_bess_mw']:>8.2f} | "
            f"{row['soc_after_percent']:>6.1f}%"
        )

    print("\nSaved Dispatch Outputs")

    print(
        f"CSV results                : "
        f"{saved_dispatch_files['csv']}"
    )

    print(
        f"Load comparison graph      : "
        f"{saved_dispatch_files['load_plot']}"
    )

    print(
        f"SOC graph                  : "
        f"{saved_dispatch_files['soc_plot']}"
    )

    print(
        f"BESS power graph           : "
        f"{saved_dispatch_files['bess_power_plot']}"
    )

    # ---------------------------------------------------------
    # OPTIMIZATION-BASED BESS DISPATCH
    # ---------------------------------------------------------

    optimized_dispatch, optimization_summary = (
        optimize_peak_shaving(
            load_profile_path="data/load_profile.csv",
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

    optimization_files = (
        save_optimization_outputs(
            optimized_dispatch,
            rule_based_results=dispatch_results,
            results_directory="results",
        )
    )

    print(
        "\n10) OPTIMIZATION-BASED BESS DISPATCH"
    )

    print("-" * 64)

    print(
        f"Optimization successful    : "
        f"{optimization_summary['optimization_success']}"
    )

    print(
        f"Original system peak       : "
        f"{optimization_summary['original_peak_mw']:.2f} MW"
    )

    print(
        f"Rule-based peak            : "
        f"{dispatch_summary['peak_after_mw']:.2f} MW"
    )

    print(
        f"Optimized system peak      : "
        f"{optimization_summary['optimized_peak_mw']:.2f} MW"
    )

    print(
        f"Optimized peak reduction   : "
        f"{optimization_summary['peak_reduction_mw']:.2f} MW"
    )

    improvement_vs_rule = (
        dispatch_summary["peak_after_mw"]
        - optimization_summary[
            "optimized_peak_mw"
        ]
    )

    print(
        f"Improvement vs rule-based  : "
        f"{improvement_vs_rule:.2f} MW"
    )

    print(
        f"Minimum optimized SOC      : "
        f"{optimization_summary['minimum_soc_percent']:.1f}%"
    )

    print(
        f"Maximum optimized SOC      : "
        f"{optimization_summary['maximum_soc_percent']:.1f}%"
    )

    print(
        f"Final optimized SOC        : "
        f"{optimization_summary['final_soc_percent']:.1f}%"
    )

    print(
        f"Optimized energy charged   : "
        f"{optimization_summary['total_charge_mwh']:.2f} MWh"
    )

    print(
        f"Optimized energy discharged: "
        f"{optimization_summary['total_discharge_mwh']:.2f} MWh"
    )

    print("\nOptimized Hourly Dispatch")

    print(
        f"{'Hr':>2} | "
        f"{'Load':>7} | "
        f"{'Mode':>9} | "
        f"{'Charge':>7} | "
        f"{'Disch.':>7} | "
        f"{'Grid':>7} | "
        f"{'SOC':>7}"
    )

    print("-" * 74)

    for _, row in optimized_dispatch.iterrows():

        print(
            f"{int(row['hour']):>2} | "
            f"{row['load_mw']:>7.1f} | "
            f"{row['mode']:>9} | "
            f"{row['charge_mw']:>7.2f} | "
            f"{row['discharge_mw']:>7.2f} | "
            f"{row['grid_power_mw']:>7.2f} | "
            f"{row['soc_percent']:>6.1f}%"
        )

    print("\nSaved Optimization Outputs")

    print(
        f"Optimized CSV              : "
        f"{optimization_files['csv']}"
    )

    print(
        f"Optimized peak graph       : "
        f"{optimization_files['optimized_plot']}"
    )

    print(
        f"Optimized SOC graph        : "
        f"{optimization_files['optimized_soc']}"
    )

    print(
        f"Dispatch comparison graph  : "
        f"{optimization_files['comparison_plot']}"
    )

    # ---------------------------------------------------------
    # AUTOMATED ENGINEERING DESIGN RECOMMENDATION
    # ---------------------------------------------------------

    design_results, design_recommendations = (
        analyze_design_options(
            design_options=DESIGN_OPTIONS,
            current_export_mw=REQUIRED_MW,
            growth_percent=GROWTH_PERCENT,
            block_power_mw=BLOCK_MW,
            block_energy_mwh=BLOCK_MWH,
            power_factor=POWER_FACTOR,
            grid_voltage_kv=GRID_VOLTAGE_KV,
            collector_voltage_kv=COLLECTOR_VOLTAGE_KV,
        )
    )

    design_files = save_design_outputs(
        design_results,
        results_directory="results",
    )

    print(
        "\n11) AUTOMATED ENGINEERING DESIGN RECOMMENDATION"
    )

    print("-" * 88)

    print(
        f"{'Option':>8} | "
        f"{'Blocks':>6} | "
        f"{'XFMR':>7} | "
        f"{'Now N+1':>7} | "
        f"{'Future':>7} | "
        f"{'Fut N+1':>7} | "
        f"{'Now XFMR':>8} | "
        f"{'Fut XFMR':>8}"
    )

    print("-" * 88)

    for design in design_results:

        current_n1_text = (
            "PASS"
            if design["current_n1_pass"]
            else "FAIL"
        )

        future_capacity_text = (
            "PASS"
            if design["future_capacity_pass"]
            else "FAIL"
        )

        future_n1_text = (
            "PASS"
            if design["future_n1_pass"]
            else "FAIL"
        )

        print(
            f"{design['option']:>8} | "
            f"{design['installed_blocks']:>6} | "
            f"{design['transformer_mva']:>5.0f} MVA | "
            f"{current_n1_text:>7} | "
            f"{future_capacity_text:>7} | "
            f"{future_n1_text:>7} | "
            f"{design['current_transformer_loading_percent']:>7.1f}% | "
            f"{design['future_transformer_loading_percent']:>7.1f}%"
        )

    print("\nDesign Qualification")

    for design in design_results:

        future_ready_text = (
            "PASS"
            if design["future_ready_pass"]
            else "FAIL"
        )

        future_n1_ready_text = (
            "PASS"
            if design["future_n1_ready_pass"]
            else "FAIL"
        )

        print(
            f"{design['option']}: "
            f"Future-ready = {future_ready_text}, "
            f"Future N+1 = {future_n1_ready_text}"
        )

    print("\nENGINEERING RECOMMENDATION")
    print("-" * 88)

    minimum_future_ready = (
        design_recommendations[
            "minimum_future_ready"
        ]
    )

    minimum_future_n1 = (
        design_recommendations[
            "minimum_future_n1"
        ]
    )

    if minimum_future_ready is not None:

        print(
            "Minimum design for current N+1 plus "
            "15% future normal capacity:"
        )

        print(
            f"  {minimum_future_ready['option']} - "
            f"{minimum_future_ready['installed_blocks']} blocks, "
            f"{minimum_future_ready['installed_power_mw']:.0f} MW / "
            f"{minimum_future_ready['installed_energy_mwh']:.0f} MWh installed, "
            f"{minimum_future_ready['transformer_mva']:.0f} MVA main transformer."
        )

    else:
        print(
            "No candidate design satisfies the modeled "
            "future-ready requirements."
        )

    print()

    if minimum_future_n1 is not None:

        print(
            "Minimum design that also preserves N+1 "
            "after 15% expansion:"
        )

        print(
            f"  {minimum_future_n1['option']} - "
            f"{minimum_future_n1['installed_blocks']} blocks, "
            f"{minimum_future_n1['installed_power_mw']:.0f} MW / "
            f"{minimum_future_n1['installed_energy_mwh']:.0f} MWh installed, "
            f"{minimum_future_n1['transformer_mva']:.0f} MVA main transformer."
        )

    else:
        print(
            "No candidate design preserves the modeled "
            "N+1 requirement after future expansion."
        )

    print("\nDESIGN RATIONALE")
    print("-" * 88)

    print(
        "The recommendation separates transformer capability "
        "from BESS block capacity."
    )

    print(
        "A 75 MVA transformer can accommodate the modeled "
        "15% increase from 50 MW to 57.5 MW while remaining "
        "below the 85% conceptual loading target."
    )

    print(
        "However, 11 installed 5 MW blocks provide only "
        "55 MW of nameplate power, so additional BESS blocks "
        "are required for a 57.5 MW future export requirement."
    )

    print("\nSaved Design Outputs")

    print(
        f"Design comparison CSV       : "
        f"{design_files['csv']}"
    )

    print(
        f"Transformer comparison graph: "
        f"{design_files['transformer_graph']}"
    )

    # ---------------------------------------------------------
    # FUTURE EXPANSION & N+1 AC VALIDATION
    # ---------------------------------------------------------

    future_scenarios, future_n1_pass = (
        run_future_n1_validation(
            installed_blocks=13,
            current_export_mw=REQUIRED_MW,
            growth_percent=GROWTH_PERCENT,
            block_power_mw=BLOCK_MW,
            power_factor=POWER_FACTOR,
            main_transformer_mva=75.0,
            grid_voltage_kv=GRID_VOLTAGE_KV,
            collector_voltage_kv=COLLECTOR_VOLTAGE_KV,
        )
    )

    print(
        "\n12) FUTURE EXPANSION & N+1 AC VALIDATION"
    )

    print("-" * 82)

    reference_scenario = (
        future_scenarios[0]
    )

    print(
        f"Future export requirement  : "
        f"{reference_scenario['future_export_mw']:.2f} MW"
    )

    print(
        f"Installed BESS blocks      : "
        f"{reference_scenario['installed_blocks']}"
    )

    print(
        f"Required active blocks     : "
        f"{reference_scenario['required_active_blocks']}"
    )

    print(
        f"Future standby block       : "
        f"{reference_scenario['reserve_block']}"
    )

    print(
        f"Scheduled output per block : "
        f"{reference_scenario['block_active_power_mw']:.3f} MW"
    )

    for scenario in future_scenarios:

        result_text = (
            "PASS"
            if scenario["overall_pass"]
            else "FAIL"
        )

        print(
            f"\n{scenario['scenario']}"
        )

        print("-" * 82)

        print(
            f"Scheduled BESS output      : "
            f"{scenario['scheduled_output_mw']:.2f} MW"
        )

        print(
            f"Capacity margin            : "
            f"{scenario['capacity_margin_mw']:+.2f} MW"
        )

        print(
            f"Utility grid active power  : "
            f"{scenario['grid_active_power_mw']:.3f} MW"
        )

        print(
            f"Collector voltage          : "
            f"{scenario['collector_voltage_pu']:.4f} pu"
        )

        print(
            f"BESS voltage range         : "
            f"{scenario['minimum_voltage_pu']:.4f} - "
            f"{scenario['maximum_voltage_pu']:.4f} pu"
        )

        print(
            f"Main transformer loading   : "
            f"{scenario['main_transformer_loading_percent']:.1f}%"
        )

        print(
            f"Maximum feeder loading     : "
            f"{scenario['maximum_feeder_loading_percent']:.1f}%"
        )

        print(
            f"Maximum block XFMR loading : "
            f"{scenario['maximum_block_transformer_loading_percent']:.1f}%"
        )

        print(
            f"Total modeled losses       : "
            f"{scenario['network_losses_mw']:.4f} MW"
        )

        print(
            f"OVERALL RESULT             : "
            f"{result_text}"
        )

        if scenario["failed_checks"]:

            print(
                "Failed checks              : "
                + ", ".join(
                    scenario[
                        "failed_checks"
                    ]
                )
            )

    print(
        "\nOPTION D FUTURE N+1 VALIDATION CONCLUSION"
    )

    print("-" * 82)

    if future_n1_pass:

        print(
            "PASS: The modeled 13-block / 75 MVA configuration "
            "supports the 57.5 MW future operating requirement "
            "and restores full scheduled output following the "
            "loss of one active BESS block by activating Block 13."
        )

    else:

        print(
            "FAIL: The modeled Option D configuration does not "
            "satisfy all future N+1 operating criteria."
        )

    print("\nPROJECT SCOPE:")
    print("Preliminary conceptual analysis for BESS sizing, transformer selection,")
    print("and grid-interconnection planning.")


if __name__ == "__main__":
    main()
