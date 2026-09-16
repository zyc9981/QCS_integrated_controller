import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import serial
from serial.tools import list_ports


DEFAULT_PORT = "COM8"
DEFAULT_BAUD = 9600
DEFAULT_TERMINATOR = "CR"


TERMINATORS = {
    "CR": b"\r",
    "LF": b"\n",
    "CRLF": b"\r\n",
}


def printable_bytes(data):
    return "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in data)


def hex_bytes(data):
    return data.hex(" ").upper() if data else "<none>"


class PritelFA:
    def __init__(self):
        self.ser = None

    @property
    def is_open(self):
        return self.ser is not None and self.ser.is_open

    def open(self, port, baudrate=DEFAULT_BAUD):
        self.close()
        self.ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.2,
            write_timeout=1.0,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.ser = None

    def send_command(self, command, terminator, read_seconds=1.0):
        if not self.is_open:
            raise RuntimeError("Serial port is not open.")

        payload = command.encode("ascii") + terminator
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        self.ser.write(payload)
        self.ser.flush()

        return payload, self._read_for(read_seconds)

    def _read_for(self, duration_s, quiet_s=0.12):
        deadline = time.monotonic() + duration_s
        quiet_deadline = None
        chunks = []

        while time.monotonic() < deadline:
            waiting = self.ser.in_waiting
            if waiting:
                chunks.append(self.ser.read(waiting))
                quiet_deadline = time.monotonic() + quiet_s
            elif quiet_deadline and time.monotonic() >= quiet_deadline:
                break
            else:
                time.sleep(0.02)

        return b"".join(chunks)


class PritelControlApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PriTel EDFA RS-232 Control")
        self.geometry("850x620")
        self.minsize(760, 540)

        self.device = PritelFA()
        self.worker_queue = queue.Queue()

        self.port_var = tk.StringVar(value=DEFAULT_PORT)
        self.baud_var = tk.IntVar(value=DEFAULT_BAUD)
        self.terminator_var = tk.StringVar(value=DEFAULT_TERMINATOR)
        self.read_seconds_var = tk.DoubleVar(value=1.0)
        self.current_var = tk.StringVar(value="000")
        self.status_var = tk.StringVar(value="Disconnected")
        self.auto_exit_var = tk.BooleanVar(value=False)

        self._build_ui()
        self._refresh_ports()
        self._poll_worker_queue()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        connection = ttk.LabelFrame(self, text="Connection")
        connection.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        connection.columnconfigure(1, weight=1)

        ttk.Label(connection, text="Port").grid(row=0, column=0, padx=8, pady=8, sticky="w")
        self.port_combo = ttk.Combobox(connection, textvariable=self.port_var, width=18)
        self.port_combo.grid(row=0, column=1, padx=8, pady=8, sticky="ew")

        ttk.Button(connection, text="Refresh", command=self._refresh_ports).grid(row=0, column=2, padx=4, pady=8)
        ttk.Button(connection, text="Connect", command=self._connect).grid(row=0, column=3, padx=4, pady=8)
        ttk.Button(connection, text="Disconnect", command=self._disconnect).grid(row=0, column=4, padx=4, pady=8)

        ttk.Label(connection, text="Baud").grid(row=1, column=0, padx=8, pady=8, sticky="w")
        ttk.Entry(connection, textvariable=self.baud_var, width=10).grid(row=1, column=1, padx=8, pady=8, sticky="w")

        ttk.Label(connection, text="Terminator").grid(row=1, column=2, padx=8, pady=8, sticky="e")
        ttk.Combobox(
            connection,
            textvariable=self.terminator_var,
            values=list(TERMINATORS),
            width=8,
            state="readonly",
        ).grid(row=1, column=3, padx=4, pady=8, sticky="w")

        ttk.Label(connection, text="Read seconds").grid(row=1, column=4, padx=8, pady=8, sticky="e")
        ttk.Entry(connection, textvariable=self.read_seconds_var, width=8).grid(row=1, column=5, padx=8, pady=8)

        ttk.Label(connection, textvariable=self.status_var).grid(
            row=2, column=0, columnspan=6, padx=8, pady=(0, 8), sticky="w"
        )

        controls = ttk.LabelFrame(self, text="PriTel FA Commands")
        controls.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        for col in range(5):
            controls.columnconfigure(col, weight=1)

        ttk.Button(controls, text="READY?", command=lambda: self._send("READY?")).grid(
            row=0, column=0, padx=8, pady=8, sticky="ew"
        )
        ttk.Button(controls, text="FA CONTROL?", command=lambda: self._send("FA CONTROL?")).grid(
            row=0, column=1, padx=8, pady=8, sticky="ew"
        )
        ttk.Button(controls, text="FA PUMP?", command=lambda: self._send("FA PUMP?")).grid(
            row=0, column=2, padx=8, pady=8, sticky="ew"
        )
        ttk.Button(controls, text="FA CURRENT?", command=lambda: self._send("FA CURRENT?")).grid(
            row=0, column=3, padx=8, pady=8, sticky="ew"
        )
        ttk.Button(controls, text="FA EXIT", command=lambda: self._send("FA EXIT")).grid(
            row=0, column=4, padx=8, pady=8, sticky="ew"
        )

        ttk.Button(controls, text="FA ON", command=lambda: self._confirm_and_send("FA ON")).grid(
            row=1, column=0, padx=8, pady=8, sticky="ew"
        )
        ttk.Button(controls, text="FA OFF", command=lambda: self._send("FA OFF")).grid(
            row=1, column=1, padx=8, pady=8, sticky="ew"
        )

        ttk.Label(controls, text="Pump current mA").grid(row=1, column=2, padx=8, pady=8, sticky="e")
        ttk.Entry(controls, textvariable=self.current_var, width=8).grid(row=1, column=3, padx=8, pady=8, sticky="w")
        ttk.Button(controls, text="FA SET nnn", command=self._set_current).grid(
            row=1, column=4, padx=8, pady=8, sticky="ew"
        )

        custom = ttk.LabelFrame(self, text="Custom ASCII Command")
        custom.grid(row=2, column=0, sticky="ew", padx=12, pady=6)
        custom.columnconfigure(0, weight=1)
        self.custom_entry = ttk.Entry(custom)
        self.custom_entry.grid(row=0, column=0, padx=8, pady=8, sticky="ew")
        self.custom_entry.bind("<Return>", lambda _event: self._send_custom())
        ttk.Button(custom, text="Send", command=self._send_custom).grid(row=0, column=1, padx=8, pady=8)
        ttk.Checkbutton(custom, text="Send FA EXIT on close", variable=self.auto_exit_var).grid(
            row=0, column=2, padx=8, pady=8
        )

        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.grid(row=3, column=0, sticky="nsew", padx=12, pady=(6, 12))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log = scrolledtext.ScrolledText(log_frame, wrap="word", height=16)
        self.log.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    def _refresh_ports(self):
        ports = list(list_ports.comports())
        values = [port.device for port in ports]
        self.port_combo["values"] = values
        if DEFAULT_PORT in values:
            self.port_var.set(DEFAULT_PORT)
        elif values and not self.port_var.get():
            self.port_var.set(values[0])
        self._append_log("Available ports: " + (", ".join(values) if values else "none"))

    def _connect(self):
        try:
            self.device.open(self.port_var.get(), self.baud_var.get())
        except Exception as exc:
            messagebox.showerror("Connection Error", str(exc))
            self.status_var.set("Disconnected")
            return

        self.status_var.set(f"Connected to {self.port_var.get()} at {self.baud_var.get()} baud")
        self._append_log(self.status_var.get())

    def _disconnect(self):
        self.device.close()
        self.status_var.set("Disconnected")
        self._append_log("Disconnected")

    def _terminator(self):
        return TERMINATORS[self.terminator_var.get()]

    def _read_seconds(self):
        return max(0.1, float(self.read_seconds_var.get()))

    def _send_custom(self):
        command = self.custom_entry.get().strip()
        if command:
            self._send(command)

    def _confirm_and_send(self, command):
        if messagebox.askyesno("Confirm Command", f"Send {command}?"):
            self._send(command)

    def _set_current(self):
        value = self.current_var.get().strip()
        if not value.isdigit():
            messagebox.showerror("Invalid Current", "Pump current must be digits only.")
            return
        if len(value) > 3:
            messagebox.showerror("Invalid Current", "Pump current must be 0 to 999 mA.")
            return
        command = f"FA SET {int(value):03d}"
        self.current_var.set(command[-3:])
        self._send(command)

    def _send(self, command):
        if not self.device.is_open:
            messagebox.showwarning("Not Connected", "Open the serial port first.")
            return

        self._append_log(f">>> {command!r} + {self.terminator_var.get()}")
        thread = threading.Thread(target=self._send_worker, args=(command,), daemon=True)
        thread.start()

    def _send_worker(self, command):
        try:
            tx, rx = self.device.send_command(command, self._terminator(), self._read_seconds())
            self.worker_queue.put(("response", command, tx, rx))
        except Exception as exc:
            self.worker_queue.put(("error", str(exc)))

    def _poll_worker_queue(self):
        while True:
            try:
                item = self.worker_queue.get_nowait()
            except queue.Empty:
                break

            if item[0] == "response":
                _kind, command, tx, rx = item
                self._append_log(f"TX hex: {hex_bytes(tx)}")
                self._append_log(f"RX hex: {hex_bytes(rx)}")
                self._append_log(f"RX raw: {rx!r}")
                if rx:
                    self._append_log(f"RX text: {printable_bytes(rx)}")
                elif command == "READY?":
                    self._append_log('No response. Expected text includes "PriTel FA READY" when remote control is active.')
            elif item[0] == "error":
                self._append_log(f"ERROR: {item[1]}")
                messagebox.showerror("Serial Error", item[1])

        self.after(100, self._poll_worker_queue)

    def _append_log(self, text):
        timestamp = time.strftime("%H:%M:%S")
        self.log.insert("end", f"[{timestamp}] {text}\n")
        self.log.see("end")

    def _on_close(self):
        if self.device.is_open and self.auto_exit_var.get():
            try:
                self.device.send_command("FA EXIT", self._terminator(), self._read_seconds())
            except Exception:
                pass
        self.device.close()
        self.destroy()


if __name__ == "__main__":
    app = PritelControlApp()
    app.mainloop()
