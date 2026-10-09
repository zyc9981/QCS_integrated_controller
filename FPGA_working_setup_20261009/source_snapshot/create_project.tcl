# Create the IP foundation for a separate HH -> PCIe -> optical -> PCIe design.
# Vivado 2025.2; target verified against the existing IBERT project.
set script_dir [file dirname [file normalize [info script]]]
set build_dir [file join $script_dir build]
create_project hh_qsfp $build_dir -part xcvu9p-flgb2104-2-e -force
set_property target_language Verilog [current_project]
add_files [file join $script_dir rtl hh_qsfp_top.v]
add_files -fileset constrs_1 [file join $script_dir constraints htg930_qsfp_pcie.xdc]
set_property top hh_qsfp_top [current_fileset]

# A Gen3 x1 link has ample bandwidth for the HydraHarp's 32-bit records.
# The bundled HTG-930 PCIe reference design supplies the X1Y2 block and
# board-specific clock/reset and lane pin assignments.
create_ip -name xdma -vendor xilinx.com -library ip -version 4.2 -module_name pcie_dma
set_property -dict [list \
    CONFIG.pcie_blk_locn X1Y2 \
    CONFIG.pl_link_cap_max_link_width X1 \
    CONFIG.pl_link_cap_max_link_speed 8.0_GT/s \
    CONFIG.xdma_axi_intf_mm AXI_Stream \
    CONFIG.axi_data_width 64_bit \
    CONFIG.xdma_rnum_chnl 1 \
    CONFIG.xdma_wnum_chnl 1 \
] [get_ips pcie_dma]

# QSFP3 TX2 -> fiber -> QSFP4 RX2 is the documented first payload route.
# Each Aurora instance is duplex so its far end can establish a link.
foreach {name lane quad} {
    qsfp3_link X1Y49 X1Y12
    qsfp4_link X1Y58 X1Y14
} {
    create_ip -name aurora_64b66b -vendor xilinx.com -library ip -version 13.0 -module_name $name
    set_property CONFIG.C_START_QUAD Quad_$quad [get_ips $name]
    set_property -dict [list \
        CONFIG.C_AURORA_LANES 1 \
        CONFIG.C_START_LANE $lane \
        CONFIG.C_REFCLK_SOURCE MGTREFCLK0_of_Quad_$quad \
        CONFIG.C_LINE_RATE 25.78125 \
        CONFIG.C_REFCLK_FREQUENCY 155.3087349 \
        CONFIG.C_INIT_CLK 200 \
        CONFIG.SupportLevel 1 \
        CONFIG.drp_mode Native \
        CONFIG.dataflow_config Duplex \
        CONFIG.interface_mode Framing \
    ] [get_ips $name]
}

# A VIO exposes sticky FIFO/Aurora diagnostics and a clear pulse over JTAG.
create_ip -name vio -vendor xilinx.com -library ip -version 3.0 -module_name diagnostic_vio
set_property -dict [list \
    CONFIG.C_NUM_PROBE_IN {1} \
    CONFIG.C_NUM_PROBE_OUT {1} \
    CONFIG.C_PROBE_IN0_WIDTH {9} \
    CONFIG.C_PROBE_OUT0_WIDTH {1} \
] [get_ips diagnostic_vio]

generate_target all [get_ips {pcie_dma qsfp3_link qsfp4_link diagnostic_vio}]

# The Aurora example-design GT wrapper exposes TXDIFFCTRL internally but
# hardwires it to Vivado's default value. Encode the measured IBERT settings
# for the two lanes used by this streaming design:
#   qsfp3_link / GTY X1Y49: 430 mV = 00001
#   qsfp4_link / GTY X1Y58: 490 mV = 00100
# These generated wrappers are part of each Aurora IP fileset and are used by
# the IP synthesis run. Keep this patch here so regenerating the project does
# not silently restore the default swing.
foreach {name swing_code} {
    qsfp3_link 00001
    qsfp4_link 00100
} {
    set gt_wrapper [file join $build_dir hh_qsfp.gen sources_1 ip $name $name example_design gt ${name}_wrapper.v]
    if {![file exists $gt_wrapper]} {
        error "Expected Aurora GT wrapper was not generated: $gt_wrapper"
    }
    set f [open $gt_wrapper r]
    set contents [read $f]
    close $f
    set default_txdiffctrl "{1{5'b01000}}"
    set tuned_txdiffctrl "{1{5'b${swing_code}}}"
    if {[string first $default_txdiffctrl $contents] < 0} {
        error "Could not find the expected default TXDIFFCTRL in $gt_wrapper"
    }
    set contents [string map [list $default_txdiffctrl $tuned_txdiffctrl] $contents]
    set f [open $gt_wrapper w]
    puts -nonewline $f $contents
    close $f
    puts "Set ${name} GT TXDIFFCTRL to $swing_code in $gt_wrapper"
}

update_compile_order -fileset sources_1
puts "Created [current_project] at $build_dir"
