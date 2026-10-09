# Page-aware I2C VIO helper for the 40-bit i2c_command bus in
# htg930_clock_probe.bit. Short commands must still be written as 10 hex
# digits; the archived helper used an 8-digit format for these commands.

set engine_vio {}
foreach v [get_hw_vios -quiet] {
    if {[llength [get_hw_probes -quiet i2c_command -of_objects $v]] == 1} {
        lappend engine_vio $v
    }
}
if {[llength $engine_vio] != 1} {
    error "Expected exactly one hardware I2C VIO"
}
set engine_out [get_hw_probes i2c_command -of_objects $engine_vio]
set engine_in [get_hw_probes i2c_status -of_objects $engine_vio]
set_property OUTPUT_VALUE_RADIX HEX $engine_out
set_property INPUT_VALUE_RADIX HEX $engine_in

# Normalize Vivado's initial short hexadecimal value to the 40-bit VIO width
# without committing a new value to the FPGA.
scan [get_property OUTPUT_VALUE $engine_out] %x initial_output
set_property OUTPUT_VALUE [format %010x $initial_output] $engine_out

proc i2c_status_read {} {
    global engine_vio engine_in
    refresh_hw_vio $engine_vio
    scan [get_property INPUT_VALUE $engine_in] %x status
    return $status
}

proc i2c_command_run {mask address {register -1} {page 0}} {
    global engine_out engine_vio
    if {$mask < 0 || $mask > 255 || $address < 8 || $address > 119 ||
        $register < -1 || $register > 255 || $page < 0 || $page > 31} {
        error "Invalid I2C command arguments"
    }
    set before [i2c_status_read]
    if {$before & 1} {error "I2C engine is busy"}
    scan [get_property OUTPUT_VALUE $engine_out] %x old
    set cmd [expr {(($old ^ 0x80000000) & 0x80000000) |
        ($mask << 16) | ($address << 8)}]
    if {$register >= 0} {
        if {$address != 0x77} {
            error "Paged reads in this helper are for the Si5341 at 0x77"
        }
        set cmd [expr {$cmd | 0x41000000 | ($page << 25) | $register}]
    }
    set_property OUTPUT_VALUE [format %010x $cmd] $engine_out
    commit_hw_vio $engine_vio
    set deadline [expr {[clock milliseconds] + 3000}]
    while {[clock milliseconds] < $deadline} {
        set status [i2c_status_read]
        if {(($status >> 16) & 65535) != (($before >> 16) & 65535) &&
            ($status & 2)} {
            set error_code [expr {($status >> 4) & 15}]
            puts [format "I2C 0x%02X: success=%d error=%d data=0x%02X" \
                $address [expr {($status >> 2) & 1}] $error_code \
                [expr {($status >> 8) & 255}]]
            return $status
        }
        after 10
    }
    error "I2C completion timed out; inspect the bus and status"
}

proc si5341_read {mask register_address} {
    if {$register_address < 0 || $register_address > 0x1FFF} {
        error "Si5341 register address out of range"
    }
    return [i2c_command_run $mask 0x77 \
        [expr {$register_address & 255}] [expr {$register_address >> 8}]]
}
