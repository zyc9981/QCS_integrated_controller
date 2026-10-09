# Clear sticky stream diagnostics through the VIO without reprogramming.
set script_dir [file dirname [file normalize [info script]]]
set ltx_file [file join $script_dir .. bitstreams hh_qsfp_top.ltx]
if {![file isfile $ltx_file]} {
    error "Debug probes file not found: $ltx_file (build the diagnostic bitstream first)"
}

open_hw_manager
connect_hw_server -url TCP:localhost:3121
set targets [get_hw_targets]
if {![llength $targets]} {error "No JTAG target found"}
open_hw_target [lindex $targets 0]

set vu9_devices {}
foreach device [get_hw_devices] {
    if {[string match -nocase *xcvu9p* [get_property PART $device]]} {
        lappend vu9_devices $device
    }
}
if {[llength $vu9_devices] != 1} {
    error "Expected exactly one xcvu9p device; found [llength $vu9_devices]"
}
set device [lindex $vu9_devices 0]
set_property PROBES.FILE $ltx_file $device
refresh_hw_device $device

set diag_vios {}
foreach vio [get_hw_vios -quiet] {
    if {[get_property CELL_NAME $vio] eq "diagnostic_vio_inst" &&
        [llength [get_hw_probes -quiet diag_clear_req -of_objects $vio]] == 1} {
        lappend diag_vios $vio
    }
}
if {[llength $diag_vios] != 1} {
    error "Expected one diagnostic VIO with diag_clear_req output"
}
set diag_vio [lindex $diag_vios 0]
set clear_probe [get_hw_probes diag_clear_req -of_objects $diag_vio]
set_property OUTPUT_VALUE_RADIX HEX $clear_probe
set_property OUTPUT_VALUE 1 $clear_probe
commit_hw_vio $diag_vio
after 100
set_property OUTPUT_VALUE 0 $clear_probe
commit_hw_vio $diag_vio
after 100
refresh_hw_vio $diag_vio
puts "Sticky diagnostic flags cleared."
close_hw_manager
