# Load once with python_controller closed. Mode changes then require no programming.
set root [file normalize [file join [file dirname [info script]] ..]]
set image [file join $root FPGA_HH_QSFP controller_modes_20261018 hh_qsfp_top.bit]
set probes [file join $root FPGA_HH_QSFP controller_modes_20261018 hh_qsfp_top.ltx]
foreach file [list $image $probes] {if {![file isfile $file]} {error "Missing $file"}}
if {![catch {exec fuser /dev/xdma0_h2c_0 /dev/xdma0_c2h_0} owners]} {
    error "Close XDMA clients before programming: $owners"
}
open_hw_manager
connect_hw_server -url TCP:localhost:3121
set targets [get_hw_targets -quiet *210249AE83E1*]
if {[llength $targets]!=1} {error "Expected one HTG-930 target"}
open_hw_target [lindex $targets 0]
set device [lindex [get_hw_devices -filter {PART =~ *xcvu9p*}] 0]
if {$device eq ""} {error "xcvu9p not found"}
current_hw_device $device
set_property PROGRAM.FILE $image $device
set_property PROBES.FILE $probes $device
program_hw_devices $device
refresh_hw_device $device
close_hw_manager
puts "Mode-capable image loaded. Rescan PCIe before opening python_controller."
exit
