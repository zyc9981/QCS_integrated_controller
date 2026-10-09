// Diagnostic: XDMA H2C -> async FIFO -> async FIFO -> XDMA C2H.
// Cross through the board's 200 MHz init clock. No Aurora or optical payload.
module pcie_fifo_loopback_top (
    input wire sys_clk_p, sys_clk_n, sys_rst_n,
    input wire pci_exp_rxp, pci_exp_rxn,
    output wire pci_exp_txp, pci_exp_txn,
    input wire init_clk_p, init_clk_n,
    output wire qsfp3_reset_n, qsfp4_reset_n,
    output wire qsfp3_lpmode, qsfp4_lpmode,
    output wire [2:0] status_led
);
    wire sys_clk_gt, sys_clk, init_clk_unbuf, init_clk;
    IBUFDS_GTE4 pcie_clk_buf (
        .I(sys_clk_p), .IB(sys_clk_n), .CEB(1'b0),
        .O(sys_clk_gt), .ODIV2(sys_clk)
    );
    IBUFDS init_clk_ibuf (.I(init_clk_p), .IB(init_clk_n), .O(init_clk_unbuf));
    BUFG init_clk_buf (.I(init_clk_unbuf), .O(init_clk));
    assign qsfp3_reset_n = 1'b0;
    assign qsfp4_reset_n = 1'b0;
    assign qsfp3_lpmode = 1'b1;
    assign qsfp4_lpmode = 1'b1;
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


    (* ASYNC_REG = "TRUE" *) reg [2:0] init_reset_sync = 3'b0;
    always @(posedge init_clk) init_reset_sync <= {init_reset_sync[1:0], axi_resetn};
    wire [72:0] tx_word, rx_word;
    wire tx_full, tx_empty, tx_wr_busy, tx_rd_busy;
    wire rx_full, rx_empty, rx_wr_busy, rx_rd_busy;
    wire bridge_transfer = !tx_empty && !tx_rd_busy && !rx_full && !rx_wr_busy;
    assign h2c_ready = !tx_full && !tx_wr_busy;
    assign {c2h_last, c2h_keep, c2h_data} = rx_word;
    assign c2h_valid = !rx_empty && !rx_rd_busy;
    xpm_fifo_async #(
        .FIFO_MEMORY_TYPE("block"), .FIFO_WRITE_DEPTH(16384),
        .WRITE_DATA_WIDTH(73), .READ_DATA_WIDTH(73),
        .READ_MODE("fwft"), .FIFO_READ_LATENCY(0),
        .CDC_SYNC_STAGES(2), .DOUT_RESET_VALUE("0"),
        .ECC_MODE("no_ecc"), .FULL_RESET_VALUE(0),
        .PROG_EMPTY_THRESH(10), .PROG_FULL_THRESH(16374),
        .RD_DATA_COUNT_WIDTH(15), .WR_DATA_COUNT_WIDTH(15), .WAKEUP_TIME(0)
    ) h2c_fifo (
        .rst(!axi_resetn), .wr_clk(axi_clk),
        .wr_en(h2c_valid && h2c_ready), .din({h2c_last, h2c_keep, h2c_data}),
        .full(tx_full), .wr_rst_busy(tx_wr_busy),
        .rd_clk(init_clk), .rd_en(bridge_transfer), .dout(tx_word),
        .empty(tx_empty), .rd_rst_busy(tx_rd_busy),
        .sleep(1'b0), .injectsbiterr(1'b0), .injectdbiterr(1'b0)
    );
    xpm_fifo_async #(
        .FIFO_MEMORY_TYPE("block"), .FIFO_WRITE_DEPTH(16384),
        .WRITE_DATA_WIDTH(73), .READ_DATA_WIDTH(73),
        .READ_MODE("fwft"), .FIFO_READ_LATENCY(0),
        .CDC_SYNC_STAGES(2), .DOUT_RESET_VALUE("0"),
        .ECC_MODE("no_ecc"), .FULL_RESET_VALUE(0),
        .PROG_EMPTY_THRESH(10), .PROG_FULL_THRESH(16374),
        .RD_DATA_COUNT_WIDTH(15), .WR_DATA_COUNT_WIDTH(15), .WAKEUP_TIME(0)
    ) c2h_fifo (
        .rst(!init_reset_sync[2]), .wr_clk(init_clk),
        .wr_en(bridge_transfer), .din(tx_word),
        .full(rx_full), .wr_rst_busy(rx_wr_busy),
        .rd_clk(axi_clk), .rd_en(c2h_valid && c2h_ready), .dout(rx_word),
        .empty(rx_empty), .rd_rst_busy(rx_rd_busy),
        .sleep(1'b0), .injectsbiterr(1'b0), .injectdbiterr(1'b0)
    );
    assign status_led = {1'b0, axi_resetn, pcie_link_up};
endmodule
