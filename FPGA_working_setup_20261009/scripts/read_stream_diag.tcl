# Read sticky QSFP stream diagnostics from the currently programmed image.
# The design must have been rebuilt with diagnostic_vio and its matching LTX.
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
    # Vivado may name a probe after its connected net (diag_sync2), rather
    # than the VIO port name (probe_in0).
    if {[get_property CELL_NAME $vio] eq "diagnostic_vio_inst" &&
        [llength [get_hw_probes -quiet diag_sync2 -of_objects $vio]] == 1} {
        lappend diag_vios $vio
    }
}
if {[llength $diag_vios] != 1} {
    error "Expected one diagnostic_vio_inst with diag_sync2 input; found [llength $diag_vios]"
}
set diag_vio [lindex $diag_vios 0]
set diag_probe [get_hw_probes diag_sync2 -of_objects $diag_vio]
set_property INPUT_VALUE_RADIX HEX $diag_probe
refresh_hw_vio $diag_vio
scan [get_property INPUT_VALUE $diag_probe] %x diag

puts [format "Diagnostic bits (hex): 0x%03X" $diag]
puts [format "TX channel up:       %d" [expr {($diag >> 0) & 1}]]
puts [format "RX channel up:       %d" [expr {($diag >> 1) & 1}]]
puts [format "RX FIFO overflow:    %d" [expr {($diag >> 2) & 1}]]
puts [format "RX FIFO full:        %d" [expr {($diag >> 3) & 1}]]
puts [format "RX FIFO write busy:  %d" [expr {($diag >> 4) & 1}]]
puts [format "TX Aurora hard err:  %d" [expr {($diag >> 5) & 1}]]
puts [format "TX Aurora soft err:  %d" [expr {($diag >> 6) & 1}]]
puts [format "RX Aurora hard err:  %d" [expr {($diag >> 7) & 1}]]
puts [format "RX Aurora soft err:  %d" [expr {($diag >> 8) & 1}]]

close_hw_manager
