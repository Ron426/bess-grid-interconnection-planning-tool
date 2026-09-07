import pandapower as pp


def build_collector_network(
    plant_export_mw: float,
    plant_reactive_mvar: float,
    main_transformer_mva: float,
    grid_voltage_kv: float,
    collector_voltage_kv: float,
    block_voltage_kv: float = 0.8,
    number_of_blocks: int = 11,
    active_blocks: int = 10,
    block_energy_mwh: float = 10.0,
    grid_source_voltage_pu=1.0,
):
    """
    Build a detailed conceptual BESS collector network.

    Topology:
    Utility Grid
        -> 115 kV POI Bus
        -> Main 115/34.5 kV Transformer
        -> 34.5 kV Collector Bus
        -> Individual 34.5 kV Feeders
        -> Individual 34.5/0.8 kV Block Transformers
        -> Individual BESS Blocks
    """

    if active_blocks > number_of_blocks:
        raise ValueError(
            "Active blocks cannot exceed the number of installed blocks."
        )

    # ---------------------------------------------------------
    # CREATE NETWORK
    # ---------------------------------------------------------

    net = pp.create_empty_network(
        name="Detailed BESS Collector System",
        f_hz=60.0,
        sn_mva=100.0,
    )

    # ---------------------------------------------------------
    # MAIN GRID BUSES
    # ---------------------------------------------------------

    poi_bus = pp.create_bus(
        net,
        vn_kv=grid_voltage_kv,
        name="115 kV POI Bus",
    )

    collector_bus = pp.create_bus(
        net,
        vn_kv=collector_voltage_kv,
        name="34.5 kV Main Collector Bus",
    )

    # ---------------------------------------------------------
    # UTILITY GRID
    # ---------------------------------------------------------

    grid = pp.create_ext_grid(
        net,
        bus=poi_bus,
        vm_pu=grid_source_voltage_pu,
        va_degree=0.0,
        name="Utility Grid",
    )

    # ---------------------------------------------------------
    # MAIN TRANSFORMER
    # ---------------------------------------------------------

    main_transformer = pp.create_transformer_from_parameters(
        net,
        hv_bus=poi_bus,
        lv_bus=collector_bus,
        sn_mva=main_transformer_mva,
        vn_hv_kv=grid_voltage_kv,
        vn_lv_kv=collector_voltage_kv,
        vk_percent=10.0,
        vkr_percent=0.5,
        pfe_kw=50.0,
        i0_percent=0.1,
        shift_degree=0.0,
        name="75 MVA 115/34.5 kV Main Transformer",
        max_loading_percent=85.0,
    )

    # ---------------------------------------------------------
    # POWER PER ACTIVE BESS BLOCK
    # ---------------------------------------------------------

    block_active_power_mw = plant_export_mw / active_blocks

    block_reactive_power_mvar = (
        plant_reactive_mvar / active_blocks
        if active_blocks > 0
        else 0.0
    )

    blocks = []

    # ---------------------------------------------------------
    # CREATE 11 INDIVIDUAL BESS BLOCKS
    # ---------------------------------------------------------

    for block_number in range(1, number_of_blocks + 1):

        is_active = block_number <= active_blocks

        # -----------------------------------------------------
        # 34.5 kV LOCAL FEEDER BUS
        # -----------------------------------------------------

        mv_bus = pp.create_bus(
            net,
            vn_kv=collector_voltage_kv,
            name=f"Block {block_number} - 34.5 kV Bus",
        )

        # -----------------------------------------------------
        # 0.8 kV BESS BUS
        # -----------------------------------------------------

        lv_bus = pp.create_bus(
            net,
            vn_kv=block_voltage_kv,
            name=f"Block {block_number} - 0.8 kV Bus",
        )

        # -----------------------------------------------------
        # 34.5 kV COLLECTOR FEEDER
        # -----------------------------------------------------

        feeder = pp.create_line_from_parameters(
            net,
            from_bus=collector_bus,
            to_bus=mv_bus,
            length_km=0.5,
            r_ohm_per_km=0.08,
            x_ohm_per_km=0.12,
            c_nf_per_km=0.0,
            max_i_ka=0.20,
            name=f"Block {block_number} Collector Feeder",
        )

        # -----------------------------------------------------
        # BLOCK STEP-UP TRANSFORMER
        #
        # 34.5 kV / 0.8 kV
        # -----------------------------------------------------

        block_transformer = pp.create_transformer_from_parameters(
            net,
            hv_bus=mv_bus,
            lv_bus=lv_bus,
            sn_mva=6.25,
            vn_hv_kv=collector_voltage_kv,
            vn_lv_kv=block_voltage_kv,
            vk_percent=6.0,
            vkr_percent=0.6,
            pfe_kw=8.0,
            i0_percent=0.2,
            shift_degree=0.0,
            name=f"Block {block_number} Transformer",
            max_loading_percent=100.0,
        )

        # -----------------------------------------------------
        # BESS OPERATING POINT
        # -----------------------------------------------------

        if is_active:
            p_mw = -block_active_power_mw
            q_mvar = -block_reactive_power_mvar
            operating_status = "ACTIVE"

        else:
            p_mw = 0.0
            q_mvar = 0.0
            operating_status = "STANDBY"

        # -----------------------------------------------------
        # BESS STORAGE ELEMENT
        # -----------------------------------------------------

        storage = pp.create_storage(
            net,
            bus=lv_bus,
            p_mw=p_mw,
            q_mvar=q_mvar,
            max_e_mwh=block_energy_mwh,
            min_e_mwh=0.20 * block_energy_mwh,
            soc_percent=80.0,
            name=f"BESS Block {block_number}",
        )

        blocks.append(
            {
                "number": block_number,
                "status": operating_status,
                "mv_bus": mv_bus,
                "lv_bus": lv_bus,
                "feeder": feeder,
                "transformer": block_transformer,
                "storage": storage,
            }
        )

    elements = {
        "poi_bus": poi_bus,
        "collector_bus": collector_bus,
        "grid": grid,
        "main_transformer": main_transformer,
        "blocks": blocks,
    }

    return net, elements


def run_collector_power_flow(net, elements):
    """
    Run AC power flow and extract collector-system results.
    """

    pp.runpp(
        net,
        algorithm="nr",
        calculate_voltage_angles=True,
        trafo_loading="current",
        numba=False,
    )

    collector_bus = elements["collector_bus"]
    main_transformer = elements["main_transformer"]
    grid = elements["grid"]

    block_results = []

    for block in elements["blocks"]:

        block_number = block["number"]

        feeder = block["feeder"]
        transformer = block["transformer"]
        storage = block["storage"]

        mv_bus = block["mv_bus"]
        lv_bus = block["lv_bus"]

        configured_power_mw = -float(
            net.storage.at[storage, "p_mw"]
        )

        block_results.append(
            {
                "block": block_number,
                "status": block["status"],

                "power_mw":
                    configured_power_mw,

                "mv_voltage_pu":
                    float(
                        net.res_bus.at[mv_bus, "vm_pu"]
                    ),

                "lv_voltage_pu":
                    float(
                        net.res_bus.at[lv_bus, "vm_pu"]
                    ),

                "feeder_loading_percent":
                    float(
                        net.res_line.at[
                            feeder,
                            "loading_percent"
                        ]
                    ),

                "block_transformer_loading_percent":
                    float(
                        net.res_trafo.at[
                            transformer,
                            "loading_percent"
                        ]
                    ),
            }
        )

    # ---------------------------------------------------------
    # SYSTEM LOSSES
    # ---------------------------------------------------------

    total_line_losses_mw = float(
        net.res_line["pl_mw"].sum()
    )

    total_transformer_losses_mw = float(
        net.res_trafo["pl_mw"].sum()
    )

    total_network_losses_mw = (
        total_line_losses_mw
        + total_transformer_losses_mw
    )

    results = {
        "converged":
            bool(net.converged),

        "collector_voltage_pu":
            float(
                net.res_bus.at[
                    collector_bus,
                    "vm_pu"
                ]
            ),

        "main_transformer_loading_percent":
            float(
                net.res_trafo.at[
                    main_transformer,
                    "loading_percent"
                ]
            ),

        "grid_active_power_mw":
            float(
                net.res_ext_grid.at[
                    grid,
                    "p_mw"
                ]
            ),

        "total_line_losses_mw":
            total_line_losses_mw,

        "total_transformer_losses_mw":
            total_transformer_losses_mw,

        "total_network_losses_mw":
            total_network_losses_mw,

        "maximum_feeder_loading_percent":
            max(
                result["feeder_loading_percent"]
                for result in block_results
            ),

        "maximum_block_transformer_loading_percent":
            max(
                result[
                    "block_transformer_loading_percent"
                ]
                for result in block_results
            ),

        "minimum_block_voltage_pu":
            min(
                result["lv_voltage_pu"]
                for result in block_results
            ),

        "maximum_block_voltage_pu":
            max(
                result["lv_voltage_pu"]
                for result in block_results
            ),

        "block_results":
            block_results,
    }

    return results