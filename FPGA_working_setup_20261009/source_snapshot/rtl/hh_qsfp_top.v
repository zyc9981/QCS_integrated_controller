// PCIe H2C -> QSFP3 TX2 -> fiber -> QSFP4 RX2 -> PCIe C2H.
// The two FIFOs cross independent PCIe/Aurora clocks. Aurora RX has no ready
// signal, so an overflow is a data-loss condition, exposed on status LEDs.
module hh_qsfp_top (
    input  wire sys_clk_p,
    input  wire sys_clk_n,
    input  wire sys_rst_n,
    input  wire pci_exp_rxp,
    input  wire pci_exp_rxn,
    output wire pci_exp_txp,
    output wire pci_exp_txn,
    input  wire init_clk_p,
    input  wire init_clk_n,
    input  wire qsfp3_refclk_p,
    input  wire qsfp3_refclk_n,
    input  wire qsfp4_refclk_p,
    input  wire qsfp4_refclk_n,
    input  wire qsfp3_rxp,
    input  wire qsfp3_rxn,
    output wire qsfp3_txp,
    output wire qsfp3_txn,
    input  wire qsfp4_rxp,
    input  wire qsfp4_rxn,
    output wire qsfp4_txp,
    output wire qsfp4_txn,
    output wire qsfp3_reset_n,
    output wire qsfp4_reset_n,
    output wire qsfp3_lpmode,
    output wire qsfp4_lpmode,
    output wire [2:0] status_led
);
    wire sys_clk_gt, sys_clk;
    wire init_clk_unbuf, init_clk;
    IBUFDS_GTE4 pcie_clk_buf (
        .I(sys_clk_p), .IB(sys_clk_n), .CEB(1'b0),
        .O(sys_clk_gt), .ODIV2(sys_clk)
    );
    IBUFDS init_clk_ibuf (.I(init_clk_p), .IB(init_clk_n), .O(init_clk_unbuf));
    BUFG init_clk_buf (.I(init_clk_unbuf), .O(init_clk));

    // Keep the installed optical modules enabled. These pins match the
    // controls in the known-good IBERT design's FMC extension constraints.
    assign qsfp3_reset_n = 1'b1;
    assign qsfp4_reset_n = 1'b1;
    assign qsfp3_lpmode = 1'b0;
    assign qsfp4_lpmode = 1'b0;

    wire axi_clk, axi_resetn, pcie_link_up;
    wire [63:0] h2c_data, c2h_data;
    wire [7:0] h2c_keep, c2h_keep;
    wire h2c_last, h2c_valid, h2c_ready;
    wire c2h_last, c2h_valid, c2h_ready;
    pcie_dma dma (
        .sys_clk(sys_clk), .sys_clk_gt(sys_clk_gt), .sys_rst_n(sys_rst_n),
        .user_lnk_up(pcie_link_up),
        .pci_exp_rxp(pci_exp_rxp), .pci_exp_rxn(pci_exp_rxn),
        .pci_exp_txp(pci_exp_txp), .pci_exp_txn(pci_exp_txn),
        .axi_aclk(axi_clk), .axi_aresetn(axi_resetn),
        .usr_irq_req(1'b0), .usr_irq_ack(), .msi_enable(), .msi_vector_width(),
        .cfg_mgmt_addr(19'b0), .cfg_mgmt_write(1'b0),
        .cfg_mgmt_write_data(32'b0), .cfg_mgmt_byte_enable(4'b0),
        .cfg_mgmt_read(1'b0), .cfg_mgmt_read_data(),
        .cfg_mgmt_read_write_done(),
        .m_axis_h2c_tdata_0(h2c_data), .m_axis_h2c_tkeep_0(h2c_keep),
        .m_axis_h2c_tlast_0(h2c_last), .m_axis_h2c_tvalid_0(h2c_valid),
        .m_axis_h2c_tready_0(h2c_ready),
        .s_axis_c2h_tdata_0(c2h_data), .s_axis_c2h_tkeep_0(c2h_keep),
        .s_axis_c2h_tlast_0(c2h_last), .s_axis_c2h_tvalid_0(c2h_valid),
        .s_axis_c2h_tready_0(c2h_ready)
    );

    // Hold both Aurora cores in reset briefly after configuration and PCIe
    // PERST release. The init clock stays available across PCIe link resets.
    reg [15:0] startup_count = 16'b0;
    always @(posedge init_clk or negedge sys_rst_n) begin
        if (!sys_rst_n)
            startup_count <= 16'b0;
        else if (!(&startup_count))
            startup_count <= startup_count + 1'b1;
    end
    wire aurora_reset = !(&startup_count);
    wire tx_clk, rx_clk, tx_link_up, rx_link_up;
    wire tx_hard_err, tx_soft_err, rx_hard_err, rx_soft_err;
    wire [63:0] tx_data, rx_data;
    wire [7:0] tx_keep, rx_keep;
    wire tx_last, tx_valid, tx_ready;
    wire rx_last, rx_valid;

    qsfp3_link optical_tx (
        .rxp(qsfp3_rxp), .rxn(qsfp3_rxn),
        .txp(qsfp3_txp), .txn(qsfp3_txn),
        .gt_refclk1_p(qsfp3_refclk_p), .gt_refclk1_n(qsfp3_refclk_n),
        .init_clk(init_clk), .user_clk_out(tx_clk), .sync_clk_out(),
        .reset_pb(aurora_reset), .pma_init(aurora_reset),
        .power_down(1'b0), .loopback(3'b000),
        .gt_rxcdrovrden_in(1'b0),
        .s_axi_tx_tdata(tx_data), .s_axi_tx_tkeep(tx_keep),
        .s_axi_tx_tlast(tx_last), .s_axi_tx_tvalid(tx_valid),
        .s_axi_tx_tready(tx_ready),
        .m_axi_rx_tdata(), .m_axi_rx_tkeep(),
        .m_axi_rx_tlast(), .m_axi_rx_tvalid(),
        .gt0_drpaddr(10'b0), .gt0_drpdi(16'b0),
        .gt0_drpwe(1'b0), .gt0_drpen(1'b0),
        .gt0_drpdo(), .gt0_drprdy(),
        .channel_up(tx_link_up), .lane_up(), .hard_err(tx_hard_err), .soft_err(tx_soft_err),
        .tx_out_clk(), .gt_pll_lock(), .mmcm_not_locked_out(),
        .link_reset_out(), .gt_qpllclk_quad1_out(),
        .gt_qpllrefclk_quad1_out(), .gt_qpllrefclklost_quad1_out(),
        .gt_qplllock_quad1_out(), .sys_reset_out(), .gt_reset_out(),
        .gt_refclk1_out(), .gt_powergood()
    );
    qsfp4_link optical_rx (
        .rxp(qsfp4_rxp), .rxn(qsfp4_rxn),
        .txp(qsfp4_txp), .txn(qsfp4_txn),
        .gt_refclk1_p(qsfp4_refclk_p), .gt_refclk1_n(qsfp4_refclk_n),
        .init_clk(init_clk), .user_clk_out(rx_clk), .sync_clk_out(),
        .reset_pb(aurora_reset), .pma_init(aurora_reset),
        .power_down(1'b0), .loopback(3'b000),
        .gt_rxcdrovrden_in(1'b0),
        .s_axi_tx_tdata(64'b0), .s_axi_tx_tkeep(8'b0),
        .s_axi_tx_tlast(1'b0), .s_axi_tx_tvalid(1'b0),
        .s_axi_tx_tready(),
        .m_axi_rx_tdata(rx_data), .m_axi_rx_tkeep(rx_keep),
        .m_axi_rx_tlast(rx_last), .m_axi_rx_tvalid(rx_valid),
        .gt0_drpaddr(10'b0), .gt0_drpdi(16'b0),
        .gt0_drpwe(1'b0), .gt0_drpen(1'b0),
        .gt0_drpdo(), .gt0_drprdy(),
        .channel_up(rx_link_up), .lane_up(), .hard_err(rx_hard_err), .soft_err(rx_soft_err),
        .tx_out_clk(), .gt_pll_lock(), .mmcm_not_locked_out(),
        .link_reset_out(), .gt_qpllclk_quad1_out(),
        .gt_qpllrefclk_quad1_out(), .gt_qpllrefclklost_quad1_out(),
        .gt_qplllock_quad1_out(), .sys_reset_out(), .gt_reset_out(),
        .gt_refclk1_out(), .gt_powergood()
    );

    // 128 KiB in each direction; enough for one 64 KiB host block plus slack.
    // The RX FIFO cannot apply backpressure to Aurora. Software must have a
    // matching C2H read pending before it submits each H2C block.
    wire [72:0] tx_fifo_data, rx_fifo_data;
    wire tx_fifo_full, tx_fifo_empty, tx_wr_busy, tx_rd_busy;
    wire rx_fifo_full, rx_fifo_empty, rx_wr_busy, rx_rd_busy;
    wire rx_fifo_overflow;
    (* ASYNC_REG = "TRUE" *) reg [2:0] tx_link_axi_sync = 3'b0;
    (* ASYNC_REG = "TRUE" *) reg [2:0] rx_link_axi_sync = 3'b0;
    (* ASYNC_REG = "TRUE" *) reg [2:0] axi_reset_rx_sync = 3'b0;
    always @(posedge axi_clk) begin
        tx_link_axi_sync <= {tx_link_axi_sync[1:0], tx_link_up};
        rx_link_axi_sync <= {rx_link_axi_sync[1:0], rx_link_up};
    end
    always @(posedge rx_clk)
        axi_reset_rx_sync <= {axi_reset_rx_sync[1:0], axi_resetn};
    assign h2c_ready = tx_link_axi_sync[2] && rx_link_axi_sync[2]
        && !tx_fifo_full && !tx_wr_busy;
    assign {tx_last, tx_keep, tx_data} = tx_fifo_data;
    assign tx_valid = !tx_fifo_empty && !tx_rd_busy && tx_link_up;
    xpm_fifo_async #(
        .FIFO_MEMORY_TYPE("block"), .FIFO_WRITE_DEPTH(16384),
        .WRITE_DATA_WIDTH(73), .READ_DATA_WIDTH(73),
        .READ_MODE("fwft"), .FIFO_READ_LATENCY(0),
        .CDC_SYNC_STAGES(2), .DOUT_RESET_VALUE("0"),
        .ECC_MODE("no_ecc"), .FULL_RESET_VALUE(0),
        .PROG_EMPTY_THRESH(10), .PROG_FULL_THRESH(16374),
        .RD_DATA_COUNT_WIDTH(15), .WR_DATA_COUNT_WIDTH(15),
        .WAKEUP_TIME(0)
    ) h2c_fifo (
        .rst(!axi_resetn), .wr_clk(axi_clk),
        .wr_en(h2c_valid && h2c_ready),
        .din({h2c_last, h2c_keep, h2c_data}),
        .full(tx_fifo_full), .wr_rst_busy(tx_wr_busy),
        .rd_clk(tx_clk), .rd_en(tx_valid && tx_ready),
        .dout(tx_fifo_data), .empty(tx_fifo_empty),
        .rd_rst_busy(tx_rd_busy),
        .sleep(1'b0), .injectsbiterr(1'b0), .injectdbiterr(1'b0)
    );

    assign {c2h_last, c2h_keep, c2h_data} = rx_fifo_data;
    assign c2h_valid = !rx_fifo_empty && !rx_rd_busy;
    xpm_fifo_async #(
        .FIFO_MEMORY_TYPE("block"), .FIFO_WRITE_DEPTH(16384),
        .WRITE_DATA_WIDTH(73), .READ_DATA_WIDTH(73),
        .READ_MODE("fwft"), .FIFO_READ_LATENCY(0),
        .CDC_SYNC_STAGES(2), .DOUT_RESET_VALUE("0"),
        .ECC_MODE("no_ecc"), .FULL_RESET_VALUE(0),
        .PROG_EMPTY_THRESH(10), .PROG_FULL_THRESH(16374),
        .RD_DATA_COUNT_WIDTH(15), .WR_DATA_COUNT_WIDTH(15),
        .WAKEUP_TIME(0)
    ) c2h_fifo (
        .rst(!axi_reset_rx_sync[2]), .wr_clk(rx_clk),
        .wr_en(rx_valid && rx_link_up && !rx_wr_busy),
        .din({rx_last, rx_keep, rx_data}),
        .full(rx_fifo_full), .overflow(rx_fifo_overflow),
        .wr_rst_busy(rx_wr_busy),
        .rd_clk(axi_clk), .rd_en(c2h_valid && c2h_ready),
        .dout(rx_fifo_data), .empty(rx_fifo_empty),
        .rd_rst_busy(rx_rd_busy),
        .sleep(1'b0), .injectsbiterr(1'b0), .injectdbiterr(1'b0)
    );
    wire diag_clear_req;
    (* ASYNC_REG = "TRUE" *) reg [1:0] tx_diag_clear_sync = 2'b0;
    (* ASYNC_REG = "TRUE" *) reg [1:0] rx_diag_clear_sync = 2'b0;
    always @(posedge tx_clk)
        tx_diag_clear_sync <= {tx_diag_clear_sync[0], diag_clear_req};
    always @(posedge rx_clk)
        rx_diag_clear_sync <= {rx_diag_clear_sync[0], diag_clear_req};

    reg overflow_sticky = 1'b0;
    always @(posedge rx_clk) begin
        if (rx_diag_clear_sync[1])
            overflow_sticky <= 1'b0;
        else if (rx_fifo_overflow || (rx_valid && rx_fifo_full))
            overflow_sticky <= 1'b1;
    end

    // Sticky Aurora error flags survive the failing block so they can be
    // inspected later over JTAG, even when the board LEDs are not visible.
    reg tx_hard_err_sticky = 1'b0, tx_soft_err_sticky = 1'b0;
    reg rx_hard_err_sticky = 1'b0, rx_soft_err_sticky = 1'b0;
    always @(posedge tx_clk) begin
        if (tx_diag_clear_sync[1]) begin
            tx_hard_err_sticky <= 1'b0;
            tx_soft_err_sticky <= 1'b0;
        end else begin
            if (tx_hard_err) tx_hard_err_sticky <= 1'b1;
            if (tx_soft_err) tx_soft_err_sticky <= 1'b1;
        end
    end
    always @(posedge rx_clk) begin
        if (rx_diag_clear_sync[1]) begin
            rx_hard_err_sticky <= 1'b0;
            rx_soft_err_sticky <= 1'b0;
        end else begin
            if (rx_hard_err) rx_hard_err_sticky <= 1'b1;
            if (rx_soft_err) rx_soft_err_sticky <= 1'b1;
        end
    end

    // Synchronize these diagnostic bits into the always-running init clock
    // domain before the VIO samples them.
    wire [8:0] diag_async = {
        rx_soft_err_sticky,
        rx_hard_err_sticky,
        tx_soft_err_sticky,
        tx_hard_err_sticky,
        rx_wr_busy,
        rx_fifo_full,
        overflow_sticky,
        rx_link_up,
        tx_link_up
    };
    (* ASYNC_REG = "TRUE" *) reg [8:0] diag_sync1 = 9'b0;
    (* ASYNC_REG = "TRUE" *) reg [8:0] diag_sync2 = 9'b0;
    always @(posedge init_clk) begin
        diag_sync1 <= diag_async;
        diag_sync2 <= diag_sync1;
    end

    // Read status and clear sticky flags with Vivado Hardware Manager.
    diagnostic_vio diagnostic_vio_inst (
        .clk(init_clk),
        .probe_in0(diag_sync2),
        .probe_out0(diag_clear_req)
    );

    assign status_led = {overflow_sticky, rx_link_up, tx_link_up};
endmodule
