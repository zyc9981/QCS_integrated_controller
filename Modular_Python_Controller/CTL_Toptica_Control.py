"""Small DLC pro control window for Linux.

Focus a setpoint and press Up or Down to send each change immediately.
"""

import argparse
from decimal import Decimal, InvalidOperation
import tkinter as tk
from tkinter import ttk

DEFAULT_HOST = "192.168.1.200"

# Power uses the DLC pro power-stabilization setpoint. Its unit and available
# range depend on the laser's configuration, so the GUI does not assume either.
CONTROLS = (
    ("wavelength", "Wavelength", "nm", "0.001", "laser1:ctl:wavelength-set", "set_wavelength_nm"),
    ("piezo", "Piezo voltage", "V", "0.01", "laser1:dl:pc:voltage-set", "set_piezo_V"),
    ("power", "Power setpoint", "device units", "0.1", "laser1:power-stabilization:setpoint", "set_power"),
)


class CTLTopticaControl(tk.Tk):
    def __init__(self, host: str):
        super().__init__()
        self.title("TOPTICA DLC pro control")
        self.resizable(False, False)
        self.laser = None
        self.fields = {}

        frame = ttk.Frame(self, padding=16)
        frame.grid(sticky="nsew")

        ttk.Label(frame, text="DLC pro address").grid(row=0, column=0, sticky="w")
        self.host_var = tk.StringVar(value=host)
        ttk.Entry(frame, textvariable=self.host_var, width=23).grid(row=0, column=1, columnspan=2, sticky="ew", padx=(8, 8))
        ttk.Button(frame, text="Connect / refresh", command=self.connect).grid(row=0, column=3, columnspan=2, sticky="ew")

        ttk.Label(frame, text="Setpoint").grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(14, 0))
        ttk.Label(frame, text="Step").grid(row=1, column=2, sticky="w", padx=(8, 0), pady=(14, 0))

        for row, (key, label, unit, default_step, parameter, setter) in enumerate(CONTROLS, start=2):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=5)
            value_var = tk.StringVar()
            step_var = tk.StringVar(value=default_step)
            entry = ttk.Entry(frame, textvariable=value_var, width=16, state="disabled")
            entry.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=5)
            entry.bind("<Up>", lambda event, name=key: self._arrow(event, name, 1))
            entry.bind("<Down>", lambda event, name=key: self._arrow(event, name, -1))
            entry.bind("<Return>", lambda event, name=key: self._enter(event, name))
            ttk.Entry(frame, textvariable=step_var, width=9).grid(row=row, column=2, sticky="ew", padx=(8, 0), pady=5)

            down = ttk.Button(frame, text="▼", width=3, state="disabled", command=lambda name=key: self.adjust(name, -1))
            down.grid(row=row, column=3, padx=(8, 0), pady=5)
            up = ttk.Button(frame, text="▲", width=3, state="disabled", command=lambda name=key: self.adjust(name, 1))
            up.grid(row=row, column=4, padx=(4, 0), pady=5)
            ttk.Label(frame, text=unit).grid(row=row, column=5, sticky="w", padx=(8, 0))

            self.fields[key] = {
                "label": label,
                "parameter": parameter,
                "setter": setter,
                "value": value_var,
                "step": step_var,
                "entry": entry,
                "buttons": (down, up),
            }

        ttk.Label(frame, text="Focus a setpoint and press ↑ or ↓ to send each step. Type a value and press Enter.").grid(
            row=5, column=0, columnspan=6, sticky="w", pady=(12, 0)
        )
        self.status_var = tk.StringVar(value="Connecting…")
        ttk.Label(frame, textvariable=self.status_var, wraplength=510).grid(
            row=6, column=0, columnspan=6, sticky="w", pady=(8, 0)
        )

        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(100, self.connect)

    def connect(self):
        if self.laser is not None:
            try:
                self.laser.close()
            finally:
                self.laser = None
        self._enable_controls(False)
        host = self.host_var.get().strip()
        if not host:
            self.status_var.set("Enter the DLC pro address.")
            return

        self.status_var.set(f"Connecting to {host}…")
        self.update_idletasks()
        try:
            from automated_calibration.remote_laser_control import DLCProSimple

            self.laser = DLCProSimple(host).open()
        except Exception as exc:
            self.laser = None
            self.status_var.set(f"Connection failed: {exc}")
            return

        self._enable_controls(True)
        unreadable = []
        for field in self.fields.values():
            try:
                setpoint = Decimal(str(self.laser.client.get(field["parameter"])))
                field["value"].set(format(setpoint, "f"))
            except Exception:
                field["value"].set("")
                unreadable.append(field["label"])

        if unreadable:
            self.status_var.set(
                f"Connected to {host}. Could not read: {', '.join(unreadable)}. "
                "You can type a setpoint and press Enter."
            )
        else:
            self.status_var.set(f"Connected to {host}. Setpoints loaded.")
        self.fields["wavelength"]["entry"].focus_set()

    def _enable_controls(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for field in self.fields.values():
            field["entry"].configure(state=state)
            for button in field["buttons"]:
                button.configure(state=state)

    def _arrow(self, event, key: str, direction: int):
        self.adjust(key, direction)
        return "break"

    def _enter(self, event, key: str):
        self.send_value(key)
        return "break"

    def adjust(self, key: str, direction: int):
        field = self.fields[key]
        try:
            current = Decimal(field["value"].get().strip())
            step = Decimal(field["step"].get().strip())
            if not current.is_finite() or not step.is_finite() or step <= 0:
                raise ValueError("setpoint must be finite and step must be positive")
        except (InvalidOperation, ValueError):
            self.status_var.set(f"Enter a valid {field['label'].lower()} setpoint and positive step.")
            return
        self.send_value(key, current + direction * step)

    def send_value(self, key: str, value=None):
        field = self.fields[key]
        if self.laser is None:
            self.status_var.set("Connect to the DLC pro first.")
            return
        try:
            requested = Decimal(field["value"].get().strip()) if value is None else value
            if not requested.is_finite():
                raise ValueError("setpoint must be finite")
            getattr(self.laser, field["setter"])(float(requested))
        except (InvalidOperation, ValueError) as exc:
            self.status_var.set(f"Invalid {field['label'].lower()} setpoint: {exc}")
            return
        except Exception as exc:
            self.status_var.set(f"Could not set {field['label'].lower()}: {exc}")
            return

        field["value"].set(format(requested, "f"))
        self.status_var.set(f"Sent {field['label'].lower()} setpoint: {requested}")

    def close(self):
        if self.laser is not None:
            self.laser.close()
            self.laser = None
        self.destroy()


def main():
    parser = argparse.ArgumentParser(description="Control TOPTICA DLC pro setpoints")
    parser.add_argument("--host", default=DEFAULT_HOST, help="DLC pro IP address or host name")
    args = parser.parse_args()
    CTLTopticaControl(args.host).mainloop()


if __name__ == "__main__":
    main()
