"""Browse and plot saved Scan_WL CSV files without connecting to any hardware.

Run this file, then click Browse CSV. Expected columns are wavelength_nm,
followed by one or more PD columns (for example PD1, PD2).
"""

import csv
import math
from pathlib import Path
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


def load_scan_csv(filename):
    """Return wavelengths and PD series in their original file order."""
    with open(filename, newline="", encoding="utf-8-sig") as stream:
        reader = csv.reader(stream)
        header = [name.strip() for name in next(reader, [])]
        if (
            len(header) < 2
            or header[0] != "wavelength_nm"
            or any(re.fullmatch(r"PD\d+", name) is None for name in header[1:])
            or len(set(header)) != len(header)
        ):
            raise ValueError(
                "Expected wavelength_nm followed by unique PD columns "
                "(for example: wavelength_nm,PD1,PD2)."
            )

        wavelengths = []
        series = {name: [] for name in header[1:]}
        for row in reader:
            if not row or all(not value.strip() for value in row):
                continue
            if len(row) != len(header):
                raise ValueError(
                    f"Line {reader.line_num}: expected {len(header)} columns, "
                    f"found {len(row)}."
                )
            try:
                values = [float(value) for value in row]
            except ValueError as exc:
                raise ValueError(
                    f"Line {reader.line_num}: every value must be numeric."
                ) from exc
            if not all(math.isfinite(value) for value in values):
                raise ValueError(f"Line {reader.line_num}: values must be finite.")
            wavelengths.append(values[0])
            for name, value in zip(series, values[1:]):
                series[name].append(value)

    if not wavelengths:
        raise ValueError("The CSV contains no scan data.")
    return wavelengths, series


def plot_scan(wavelengths, series):
    """Match ring_calibration_helper._plot_wavelength_scan_results."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    for name, values in series.items():
        ax.plot(wavelengths, values, marker="o", label=name)
    ax.set_xlabel("Wavelength (nm)")
    ax.set_ylabel("Detector value (arb. units)")
    ax.set_title("Wavelength scan")
    ax.grid(True)
    ax.legend()
    fig.tight_layout()
    # The browser's Tk event loop keeps this separate plot window responsive.
    plt.show(block=False)
    return fig


def main():
    import matplotlib

    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt

    root = tk.Tk()
    root.title("Scan_WL_Plot")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Open a saved Scan_WL CSV to plot all recorded PDs.").pack(
        anchor="w", pady=(0, 12)
    )
    status = tk.StringVar(value="No file selected.")
    initial_dir = Path(__file__).resolve().parent / "automatic_calib_logs"
    if not initial_dir.is_dir():
        initial_dir = Path(__file__).resolve().parent

    def browse():
        nonlocal initial_dir
        filename = filedialog.askopenfilename(
            parent=root,
            title="Open Scan_WL CSV",
            initialdir=str(initial_dir),
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not filename:
            return
        try:
            wavelengths, series = load_scan_csv(filename)
        except (OSError, UnicodeError, ValueError, csv.Error) as exc:
            messagebox.showerror("Cannot open scan", str(exc), parent=root)
            return
        initial_dir = Path(filename).parent
        plot_scan(wavelengths, series)
        status.set(f"{Path(filename).name}\n{len(wavelengths)} points; {', '.join(series)}")

    ttk.Button(frame, text="Browse CSV...", command=browse).pack(anchor="w")
    ttk.Label(frame, textvariable=status, wraplength=500).pack(anchor="w", pady=(12, 0))

    def close():
        plt.close("all")
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()


if __name__ == "__main__":
    main()
