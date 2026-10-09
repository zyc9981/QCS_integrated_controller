# Run after create_project.tcl. This builds but does not program the board.
set script_dir [file dirname [file normalize [info script]]]
open_project [file join $script_dir build hh_qsfp.xpr]

# The run may have been left in a failed state after a previous build attempt.
# Reset the top-level implementation/synthesis runs and generated IP runs so
# Vivado can launch a clean build on the next invocation.
foreach run_name {synth_1 impl_1 pcie_dma_synth_1 qsfp3_link_synth_1 qsfp4_link_synth_1} {
    set run_obj [get_runs -quiet $run_name]
    if {[llength $run_obj]} {
        reset_run $run_obj
    }
}

launch_runs synth_1 -jobs 8
wait_on_run synth_1
if {[get_property STATUS [get_runs synth_1]] ne "synth_design Complete!"} {
    error "Synthesis failed: [get_property STATUS [get_runs synth_1]]"
}
launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
if {[get_property STATUS [get_runs impl_1]] ne "write_bitstream Complete!"} {
    error "Implementation failed: [get_property STATUS [get_runs impl_1]]"
}
open_run impl_1
report_timing_summary -file [file join $script_dir build hh_qsfp_timing_summary.rpt]
set worst_setup_path [get_timing_paths -setup -max_paths 1]
if {![llength $worst_setup_path]} {
    error "No constrained setup path found; inspect the timing summary before programming"
}
set worst_setup_slack [get_property SLACK $worst_setup_path]
if {$worst_setup_slack < 0.0} {
    error "Timing constraints are not met (WNS=${worst_setup_slack} ns); do not program this bitstream"
}
puts "Bitstream: [file join $script_dir build hh_qsfp.runs impl_1 hh_qsfp_top.bit]"
