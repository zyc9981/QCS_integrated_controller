# Restore the volatile Si5341 (U7) clock configuration required by the QSFP
# Aurora design. This programs the FPGA temporarily over JTAG, writes U7 over
# the page-aware FMC I2C VIO, and does not program nonvolatile flash.

set script_dir [file dirname [file normalize [info script]]]
set probe_bit [file join $script_dir .. bitstreams htg930_clock_probe.bit]
set probe_ltx [file join $script_dir .. bitstreams htg930_clock_probe.ltx]
set i2c_helper [file join $script_dir i2c_pages_control_i2c_40bit.tcl]
set register_file [file join $script_dir .. clocks HTG930_U7_155M3087349-Registers.txt]
foreach file [list $probe_bit $probe_ltx $i2c_helper $register_file] {
    if {![file isfile $file]} {
        error "Required clock restore file not found: $file"
    }
}

open_hw_manager
connect_hw_server -url TCP:localhost:3121
set targets [get_hw_targets]
if {![llength $targets]} {
    error "No JTAG target found; check the cable and board power"
}
open_hw_target [lindex $targets 0]

set vu9_devices {}
foreach device [get_hw_devices] {
    set part [get_property PART $device]
    puts "Found JTAG device: $device ($part)"
    if {[string match -nocase *xcvu9p* $part]} {
        lappend vu9_devices $device
    }
}
if {[llength $vu9_devices] != 1} {
    error "Expected exactly one xcvu9p device; found [llength $vu9_devices]"
}
set device [lindex $vu9_devices 0]

# The probe design supplies the I2C engine and VIO used by the saved loader.
set_property PROGRAM.FILE $probe_bit $device
set_property PROBES.FILE $probe_ltx $device
puts "Programming temporary clock-probe image on $device"
program_hw_devices $device
refresh_hw_device $device

set i2c_probes [get_hw_probes -quiet i2c_command]
if {[llength $i2c_probes] != 1} {
    error "Clock-probe image loaded, but its i2c_command VIO probe was not found"
}

# The local helper pads short commands to the 40-bit VIO width. The older
# archived helper formatted short commands as only eight hex digits.
source $i2c_helper

# Confirm the expected Si5341 at FMC branch 0x40 / address 0x77 ACKs before
# writing the full register image. Abort on NACK or I2C engine error.
set ack_status [i2c_command_run 0x40 0x77]
if {!(($ack_status >> 2) & 1) || (($ack_status >> 4) & 15) != 0} {
    error [format "No clean ACK from U7 Si5341 (status 0x%08X); settings not written" $ack_status]
}

# Replay the archived 155.3087349 MHz ClockBuilder register set. Every write
# is checked for I2C completion and ACK before the script continues.
proc wait_i2c_idle {{timeout_ms 3000}} {
    set deadline [expr {[clock milliseconds] + $timeout_ms}]
    set status [i2c_status_read]
    while {$status & 1} {
        if {[clock milliseconds] >= $deadline} {
            error [format "I2C engine stayed busy (status=0x%08X)" $status]
        }
        after 10
        set status [i2c_status_read]
    }
    return $status
}

proc si5341_write {register data} {
    global engine_out engine_vio
    if {$register < 0 || $register > 0x1FFF || $data < 0 || $data > 255} {
        error "Invalid Si5341 register or data"
    }
    # Completion can be reported just before the engine drops its busy bit.
    set before [wait_i2c_idle]
    scan [get_property OUTPUT_VALUE $engine_out] %x old
    set cmd [expr {(($old ^ 0x80000000) & 0x80000000) | ($data << 32) |
        0x4040F700 | (($register >> 8) << 25) | ($register & 255)}]
    set_property OUTPUT_VALUE [format %010x $cmd] $engine_out
    commit_hw_vio $engine_vio
    set deadline [expr {[clock milliseconds] + 3000}]
    while {[clock milliseconds] < $deadline} {
        set status [i2c_status_read]
        if {(($status >> 16) & 65535) != (($before >> 16) & 65535) &&
            ($status & 2)} {
            if {!(($status >> 2) & 1) || (($status >> 4) & 15)} {
                error [format "Si5341 write failed: status=0x%08X" $status]
            }
            wait_i2c_idle
            return $status
        }
        after 10
    }
    error "Si5341 write completion timed out"
}

set fh [open $register_file r]
set contents [read $fh]
close $fh
set write_count 0
foreach line [split $contents "\n"] {
    set line [string trim $line]
    if {[regexp -nocase {^#\s*Delay\s+([0-9]+)\s+msec} $line -> delay_ms]} {
        after $delay_ms
    } elseif {[regexp {^(0x[0-9A-Fa-f]+)\s*,\s*(0x[0-9A-Fa-f]+)$} \
            $line -> register data]} {
        si5341_write [expr {$register}] [expr {$data}]
        incr write_count
        after 20
    }
}
puts "U7 register sequence sent ($write_count writes)."

set verify_status [si5341_read 0x40 0x0102]
if {!(($verify_status >> 2) & 1) || (($verify_status >> 4) & 15) != 0} {
    error [format "U7 post-load read failed (status 0x%08X)" $verify_status]
}
puts "U7 clock register image restored and readback succeeded."
puts "Next run scripts/program_optical.tcl from this bundle."
close_hw_manager
exit
