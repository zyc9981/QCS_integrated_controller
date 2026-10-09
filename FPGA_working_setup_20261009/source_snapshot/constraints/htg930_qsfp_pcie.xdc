# HTG-930 VU9P PCIe pins from vendor pcie_gen3_x16_ex reference design.
set_property IOSTANDARD LVCMOS18 [get_ports sys_rst_n]
set_property PULLUP true [get_ports sys_rst_n]
set_property LOC [get_package_pins -filter {PIN_FUNC == IO_T3U_N12_PERSTN0_65}] [get_ports sys_rst_n]
set_property LOC AT11 [get_ports sys_clk_p]
set_property LOC AT10 [get_ports sys_clk_n]
set_property LOC AF2 [get_ports pci_exp_rxp]
set_property LOC AF7 [get_ports pci_exp_txp]
create_clock -name pcie_refclk -period 10.000 [get_ports sys_clk_p]
set_false_path -from [get_ports sys_rst_n]

# Known-good IBERT reference-clock pins on the QSFP FMC extension board.
set_property PACKAGE_PIN BA34 [get_ports init_clk_p]
set_property IOSTANDARD DIFF_HSTL_I_12 [get_ports init_clk_p]
create_clock -name init_refclk -period 5.000 [get_ports init_clk_p]
set_property PACKAGE_PIN M11 [get_ports qsfp3_refclk_p]
set_property PACKAGE_PIN M10 [get_ports qsfp3_refclk_n]
set_property PACKAGE_PIN D11 [get_ports qsfp4_refclk_p]
set_property PACKAGE_PIN D10 [get_ports qsfp4_refclk_n]
create_clock -name qsfp3_refclk -period 6.439 [get_ports qsfp3_refclk_p]
create_clock -name qsfp4_refclk -period 6.439 [get_ports qsfp4_refclk_p]

# PCIe, the two recovered GT clock trees, and the board init clock are
# independent sources. Data crosses between these domains only through the
# XPM asynchronous FIFOs or the explicit three-stage status/reset synchronizers.
# Keep each IP's related clocks timed against one another while excluding
# unrelated clock-domain crossings from setup/hold analysis.
set_clock_groups -asynchronous \
    -group [get_clocks -include_generated_clocks -of_objects [get_ports sys_clk_p]] \
    -group [get_clocks -include_generated_clocks -of_objects [get_ports qsfp3_refclk_p]] \
    -group [get_clocks -include_generated_clocks -of_objects [get_ports qsfp4_refclk_p]] \
    -group [get_clocks -include_generated_clocks -of_objects [get_ports init_clk_p]]

# FMC_A controls; 1.8 V VADJ per HTG-930 FMC-x4-QSFP28 mapping.
set_property PACKAGE_PIN C21 [get_ports qsfp3_reset_n]
set_property PACKAGE_PIN B20 [get_ports qsfp4_reset_n]
set_property PACKAGE_PIN M20 [get_ports qsfp3_lpmode]
set_property PACKAGE_PIN L19 [get_ports qsfp4_lpmode]
set_property IOSTANDARD LVCMOS18 [get_ports {qsfp3_reset_n qsfp4_reset_n qsfp3_lpmode qsfp4_lpmode}]
set_property DRIVE 4 [get_ports {qsfp3_reset_n qsfp4_reset_n qsfp3_lpmode qsfp4_lpmode}]

# LEDs: TX channel up, RX channel up, sticky RX FIFO overflow.
set_property PACKAGE_PIN R20 [get_ports {status_led[0]}]
set_property PACKAGE_PIN P20 [get_ports {status_led[1]}]
set_property PACKAGE_PIN N21 [get_ports {status_led[2]}]
set_property IOSTANDARD LVCMOS18 [get_ports {status_led[*]}]
set_property DRIVE 4 [get_ports {status_led[*]}]
