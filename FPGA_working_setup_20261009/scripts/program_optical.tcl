# Program the VIO-enabled stream diagnostic image over the HTG-930 JTAG link.
set script_dir [file dirname [file normalize [info script]]]
set bit_file [file join $script_dir .. bitstreams hh_qsfp_top.bit]
set ltx_file [file join $script_dir .. bitstreams hh_qsfp_top.ltx]
foreach path [list $bit_file $ltx_file] {
    if {![file isfile $path]} {error "Required programming file not found: $path"}
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
current_hw_device $device
set_property PROGRAM.FILE $bit_file $device
set_property PROBES.FILE $ltx_file $device
program_hw_devices $device
refresh_hw_device $device
puts "Diagnostic image programmed: $bit_file"
close_hw_manager
exit
