import pandapower as pp


def build_bess_network(
    bess_discharge_mw: float,
    bess_reactive_injection_mvar: float,
    bess_energy_mwh: float,
    transformer_mva: float,
    grid_voltage_kv: float,
    collector_voltage_kv: float,
):
    """
    Build the first conceptual BESS grid-interconnection network.

    Network:
    Utility Grid -> 115 kV Bus -> Main Transformer
    -> 34.5 kV Collector Bus -> BESS
    """

    # ---------------------------------------------------------
    # CREATE EMPTY 60-HZ NETWORK
    # ---------------------------------------------------------

    net = pp.create_empty_network(
        name="Utility-Scale BESS Grid Interconnection",
        f_hz=60.0,
        sn_mva=100.0,
    )

    # ---------------------------------------------------------
    # CREATE BUSES
    # ---------------------------------------------------------

    hv_bus = pp.create_bus(
        net,
        vn_kv=grid_voltage_kv,
        name="115 kV POI Bus",
    )

    collector_bus = pp.create_bus(
        net,
        vn_kv=collector_voltage_kv,
        name="34.5 kV Collector Bus",
    )

    # ---------------------------------------------------------
    # CREATE UTILITY GRID / SLACK BUS
    # ---------------------------------------------------------

    grid = pp.create_ext_grid(
        net,
        bus=hv_bus,
        vm_pu=1.0,
        va_degree=0.0,
        name="Utility Grid",
    )

    # ---------------------------------------------------------
    # CREATE MAIN TRANSFORMER
    # ---------------------------------------------------------

    transformer = pp.create_transformer_from_parameters(
        net,
        hv_bus=hv_bus,
        lv_bus=collector_bus,
        sn_mva=transformer_mva,
        vn_hv_kv=grid_voltage_kv,
        vn_lv_kv=collector_voltage_kv,

        # Preliminary conceptual transformer parameters
        vk_percent=10.0,
        vkr_percent=0.5,
        pfe_kw=50.0,
        i0_percent=0.1,
        shift_degree=0.0,

        name="75 MVA 115/34.5 kV Main Transformer",
        max_loading_percent=85.0,
    )

    # ---------------------------------------------------------
    # CREATE BESS
    # ---------------------------------------------------------

    # Pandapower storage uses the consumer sign convention:
    #
    # Positive P = charging
    # Negative P = discharging
    #
    # Therefore -50 MW represents 50 MW being exported
    # from the battery into the electrical system.

    storage = pp.create_storage(
        net,
        bus=collector_bus,
        p_mw=-bess_discharge_mw,
        q_mvar=-bess_reactive_injection_mvar,
        max_e_mwh=bess_energy_mwh,
        min_e_mwh=0.20 * bess_energy_mwh,
        soc_percent=80.0,
        name="BESS",
    )

    elements = {
        "hv_bus": hv_bus,
        "collector_bus": collector_bus,
        "grid": grid,
        "transformer": transformer,
        "storage": storage,
    }

    return net, elements


def run_bess_power_flow(net, elements):
    """
    Solve the AC power flow and return key engineering results.
    """

    pp.runpp(
        net,
        algorithm="nr",
        calculate_voltage_angles=True,
        trafo_loading="current",
        numba=False,
    )

    hv_bus = elements["hv_bus"]
    collector_bus = elements["collector_bus"]
    transformer = elements["transformer"]
    grid = elements["grid"]

    results = {
        "converged": bool(net.converged),

        "hv_voltage_pu":
            float(net.res_bus.at[hv_bus, "vm_pu"]),

        "collector_voltage_pu":
            float(net.res_bus.at[collector_bus, "vm_pu"]),

        "hv_voltage_angle_deg":
            float(net.res_bus.at[hv_bus, "va_degree"]),

        "collector_voltage_angle_deg":
            float(net.res_bus.at[collector_bus, "va_degree"]),

        "transformer_loading_percent":
            float(net.res_trafo.at[transformer, "loading_percent"]),

        "transformer_hv_current_a":
            float(net.res_trafo.at[transformer, "i_hv_ka"]) * 1000,

        "transformer_lv_current_a":
            float(net.res_trafo.at[transformer, "i_lv_ka"]) * 1000,

        "transformer_active_loss_mw":
            float(net.res_trafo.at[transformer, "pl_mw"]),

        "transformer_reactive_loss_mvar":
            float(net.res_trafo.at[transformer, "ql_mvar"]),

        "grid_active_power_mw":
            float(net.res_ext_grid.at[grid, "p_mw"]),

        "grid_reactive_power_mvar":
            float(net.res_ext_grid.at[grid, "q_mvar"]),
    }

    return results