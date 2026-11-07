# Passive VIO reads only; never commits VIO outputs or programs hardware.
set ltx [file normalize [lindex $argv 0]]
set windows [lindex $argv 1]
if {![string is integer -strict $windows] || $windows<1} {error "invalid window count"}
open_hw_manager
connect_hw_server -url TCP:localhost:3121
set targets [get_hw_targets -quiet *210249AE83E1*]
if {[llength $targets]!=1} {error "expected HTG-930 target"}
open_hw_target [lindex $targets 0]
set devices [get_hw_devices -quiet -filter {PART =~ *xcvu9p*}]
if {[llength $devices]!=1} {error "expected one VU9P"}
set d [lindex $devices 0]
current_hw_device $d
set_property PROBES.FILE $ltx $d
refresh_hw_device -update_hw_probes true $d
# The QSFP timing diagnostic names this probe timing_diag/timing_status;
# the isolated FPGA_node PCIe image exposes the same 256-bit monitor as
# timing_status. Resolve both without committing or changing any VIO output.
set p [get_hw_probes -quiet timing_diag/timing_status]
if {[llength $p]!=1} {set p [get_hw_probes -quiet timing_status]}
if {[llength $p]!=1} {error "timing_status probe missing"}
set v [get_hw_vios [get_property HW_VIO $p]]
set_property INPUT_VALUE_RADIX HEX $p
set last -1
set skip 2
set count 0
set deadline [expr {[clock milliseconds]+($windows+15)*1000}]
set previous_ref -1
set previous_stop -1
while {[clock milliseconds]<$deadline && $count<$windows} {
    refresh_hw_vio $v
    set raw [get_property INPUT_VALUE $p]
    set x [expr 0x$raw]
    if {($x>>224)!=0x54494D31} {error "TIM1 signature missing"}
    set seq [expr {($x>>192)&0xffffffff}]
    if {$seq!=$last} {
        if {$count>0 && $seq != (($last+1)&0xffffffff)} {error "missed counter window"}
        set last $seq
        if {$skip>0} {incr skip -1} else {
            set gate [expr {($x>>96)&0xffffffff}]
            set edges [expr {($x>>64)&0xffffffff}]
            set stopped [expr {($x>>32)&0xffffffff}]
            set ref [expr {($x>>128)&0xffffffffffffffff}]
            if {$count>0 && ($ref-$previous_ref!=$gate || $stopped!=$previous_stop)} {error "counter timestamp/clock continuity lost"}
            if {$gate!=200000000 || $edges==0 || ($x&3)!=3} {error "OUT8 counter window invalid: $raw"}
            set previous_ref $ref
            set previous_stop $stopped
            puts "QCS_FREQ $seq $edges $gate"
            incr count
        }
    }
    after 200
}
close_hw_target
close_hw_manager
if {$count!=$windows} {error "frequency measurement timed out"}
exit
