# Restricted Si5341 access over the already-loaded controller management VIO.
# This script never programs the FPGA and has no generic register-write mode.
# Arguments: operation expected-count addr value ... target-num(if update)

set root [file normalize [file join [file dirname [info script]] .. ..]]
set ltx [file join $root FPGA_HH_QSFP controller_modes_20261018 hh_qsfp_top.ltx]
set op [lindex $argv 0]
set n [expr {[lindex $argv 1]}]
if {$op ni {read update} || $n < 1 || $n > 64 || [llength $argv] < 2+2*$n} {
    error "Invalid bridge arguments"
}
set expected [dict create]
for {set i 0} {$i < $n} {incr i} {
    set a [expr {[lindex $argv [expr {2+2*$i}]]}]
    set v [expr {[lindex $argv [expr {3+2*$i}]]}]
    if {$a < 0 || $a > 0x1fff || $v < 0 || $v > 255} {error "Invalid expected register"}
    dict set expected $a $v
}
set target_num 0
if {$op eq "update"} {
    if {[llength $argv] != 9+2*$n} {error "Invalid update argument count"}
    set target_num [expr {[lindex $argv [expr {2+2*$n}]]}]
    if {$target_num < 1 || $target_num >= (1<<44)} {error "Invalid N1 numerator"}
    set target_bytes [lrange $argv [expr {3+2*$n}] end]
    if {[llength $target_bytes] != 6} {error "Invalid shared N1 write plan"}
    for {set i 0} {$i<6} {incr i} {
        set expected_byte [expr {($target_num>>(8*$i))&255}]
        set supplied [expr {[lindex $target_bytes $i]}]
        if {$i==5} {set expected_byte [expr {($expected_byte&0x0F)|([dict get $expected 786]&0xF0)}]}
        if {$supplied!=$expected_byte} {error "Python/Tcl N1 byte plan disagreement"}
    }
}

open_hw_manager
connect_hw_server -url TCP:localhost:3121
set targets [get_hw_targets -quiet *210249AE83E1*]
if {[llength $targets] != 1} {error "Expected one documented HTG-930 target"}
open_hw_target [lindex $targets 0]
set devices [get_hw_devices -quiet -filter {PART =~ *xcvu9p*}]
if {[llength $devices] != 1} {error "Expected one VU9P"}
set device [lindex $devices 0]
current_hw_device $device
if {![file isfile $ltx]} {error "Controller probe file missing: $ltx"}
set_property PROBES.FILE $ltx $device
refresh_hw_device -update_hw_probes true $device
proc one {name} {
    set p [get_hw_probes -quiet $name]
    if {[llength $p] != 1} {error "Expected exactly one VIO probe $name"}
    return $p
}
set pin [one mgmt_status]
set pout [one mgmt_command]
set pselect [one module_select_n]
set mgmt [get_hw_vios [get_property HW_VIO $pin]]
set startup [one startup_status]
set startup_vio [get_hw_vios [get_property HW_VIO $startup]]
set_property INPUT_VALUE_RADIX HEX $pin
set_property INPUT_VALUE_RADIX HEX $startup
set_property OUTPUT_VALUE_RADIX HEX $pout
set_property OUTPUT_VALUE_RADIX HEX $pselect
proc hexnum {v} {
    regsub -all {[^0-9A-Fa-f]} $v {} v
    if {$v eq ""} {error "Missing VIO value"}
    return [expr 0x$v]
}
proc sample {} {
    global mgmt pin pout pselect
    refresh_hw_vio -update_output_values $mgmt
    return [list [hexnum [get_property INPUT_VALUE $pin]] \
                 [hexnum [get_property OUTPUT_VALUE $pout]] \
                 [hexnum [get_property OUTPUT_VALUE $pselect]]]
}
refresh_hw_vio $startup_vio
set sv [hexnum [get_property INPUT_VALUE $startup]]
if {($sv >> 224) != 0x42555231 || (($sv >> 38) & 3) != 0} {
    error "Controller signature invalid or payload gate is open"
}
lassign [sample] status last_command saved_select
if {$status & 1} {error "Management I2C controller is busy"}
set seq [expr {($status >> 16) & 65535}]
for {set i 0} {$i<2} {incr i} {
    after 100
    lassign [sample] now cmd select
    if {($now & 1) || (($now>>16)&65535)!=$seq || $cmd!=$last_command || $select!=$saved_select} {
        error "Controller activity or VIO ownership change detected"
    }
}

proc transaction {op reg page {value 0}} {
    global mgmt pin pout pselect last_command seq saved_select
    if {$op ni {read write} || $reg<0 || $reg>255 || $page<0 || $page>31} {error "Invalid I2C transaction"}
    lassign [sample] before old select
    if {($before&1) || (($before>>16)&65535)!=$seq || $old!=$last_command || $select!=$saved_select} {
        error "I2C ownership lost before transaction"
    }
    set cmd [expr {(($old^0x80000000)&0x80000000)|0x00407700|$reg}]
    if {$op eq "read"} {
        set cmd [expr {$cmd|0x01000000|0x40000000|($page<<25)}]
    } else {
        if {$value<0 || $value>255} {error "Invalid write byte"}
        set cmd [expr {$cmd|0x00008000|($value<<32)|($page<<25)}]
    }
    set previous $seq
    set last_command $cmd
    set_property OUTPUT_VALUE [format %010X $cmd] $pout
    commit_hw_vio $mgmt
    set deadline [expr {[clock milliseconds]+5000}]
    while {[clock milliseconds]<$deadline} {
        lassign [sample] current command select_now
        if {$command!=$cmd || $select_now!=$saved_select} {error "Concurrent VIO request/selector change"}
        set newseq [expr {($current>>16)&65535}]
        if {$newseq!=$previous} {
            set seq $newseq
            if {$newseq!=(($previous+1)&65535) || ($current&0xFF)!=6} {
                error [format "I2C completion/ACK failure status=0x%08X" $current]
            }
            set data [expr {($current>>8)&255}]
            puts [format "QCS_I2C %s page=%02X reg=%02X value=%02X seq=%d->%d status=%08X mux=0x40_then_zero" $op $page $reg $data $previous $newseq $current]
            return $data
        }
        after 2
    }
    error "I2C transaction timed out"
}
proc read_reg {address} {return [transaction read [expr {$address&255}] [expr {$address>>8}]]}
proc write_reg {address value} {return [transaction write [expr {$address&255}] [expr {$address>>8}] $value]}

set original_page [read_reg 1]
if {$original_page>31} {error "Invalid Si5341 page readback"}
set restore_ok 0
set failure {}
set answer [dict create]
set failed [catch {
    set ready [read_reg 0x00FE]
    set idlo [read_reg 0x0002]
    set idhi [read_reg 0x0003]
    set grade [read_reg 0x0004]
    set revision [read_reg 0x0005]
    if {$ready!=0x0F || $idlo!=0x41 || $idhi!=0x53 || $grade!=0x00 || $revision!=0x03} {
        error "U7 Si5341 grade/revision/readiness check failed"
    }
    dict set answer device_id [format "%02X%02X grade=%02X revision=%02X" $idhi $idlo $grade $revision]
    foreach address [dict keys $expected] {
        set page [expr {$address>>8}]
        set reg [expr {$address&255}]
        set value [transaction read $reg $page]
        dict set answer $address $value
        if {$value != [dict get $expected $address]} {
            error [format "Precondition mismatch 0x%04X: got 0x%02X expected 0x%02X" $address $value [dict get $expected $address]]
        }
    }
    if {$op eq "read"} {
        for {set address 0x030D} {$address<=0x0312} {incr address} {
            dict set answer $address [read_reg $address]
        }
    }
    if {$op eq "update"} {
        # This whitelist is the entire operational write surface: N1 NUM only.
        set allowed {304 305 306 307 781 782 783 784 785 786 787 788 789 790 2563 2564 2565 2890}
        if {[lsort -integer [dict keys $expected]] ne $allowed} {
            error "Unexpected precondition register set"
        }
        for {set i 0} {$i<6} {incr i} {
            set address [expr {0x030D+$i}]
            set byte [expr {[lindex $target_bytes $i]}]
            write_reg $address $byte
        }
        for {set i 0} {$i<6} {incr i} {
            set address [expr {0x030D+$i}]
            set actual [read_reg $address]
            set wanted [expr {($target_num>>(8*$i))&255}]
            if {$i==5} {set wanted [expr {($wanted&0x0F)|([dict get $answer $address]&0xF0)}]}
            if {$actual!=$wanted} {error [format "N1 staged readback mismatch 0x%04X" $address]}
        }
        set update_before [read_reg 0x0317]
        write_reg 0x0317 [expr {$update_before|1}]
        set applied_utc_us [clock microseconds]
        set deadline [expr {[clock milliseconds]+2000}]
        while {[clock milliseconds]<$deadline} {
            if {([read_reg 0x0317]&1)==0} {break}
            after 10
        }
        if {[read_reg 0x0317]&1} {error "N1 update bit did not self-clear"}
        for {set i 0} {$i<6} {incr i} {
            set address [expr {0x030D+$i}]
            set actual [read_reg $address]
            set wanted [expr {($target_num>>(8*$i))&255}]
            if {$i==5} {set wanted [expr {($wanted&0x0F)|([dict get $answer $address]&0xF0)}]}
            if {$actual!=$wanted} {error [format "N1 final readback mismatch 0x%04X" $address]}
        }
        dict set answer applied_num $target_num
        dict set answer update_latched 1
        puts "QCS_APPLIED_UTC_US=$applied_utc_us"
    }
} failure]
set page_error [catch {
    write_reg 1 $original_page
    if {[read_reg 1]!=$original_page} {error "Si5341 page restore readback mismatch"}
    set restore_ok 1
} page_msg]
if {!$restore_ok} {error "Page restore failed: $page_msg"}
if {$failed} {error "Clock transaction failed: $failure"}
puts "QCS_RESULT $answer"
close_hw_target
close_hw_manager
exit
