#!/usr/bin/env python3
import argparse
import os

import matplotlib.pyplot as plt
import numpy as np
from astropy.io import fits


def latest_fits(directory):
    # scandir gets names (and types) from a single readdir without stat()ing
    # each entry, which matters a lot on network shares with many files.
    # Filenames are ISO timestamps, so lexical order is chronological.
    latest = None
    with os.scandir(directory) as it:
        for entry in it:
            name = entry.name
            if name.startswith("2") and name.endswith(".fits"):
                if latest is None or name > latest:
                    latest = name
    return latest


def read_zavg(path):
    # .section reads only the first plane from disk instead of all four
    with fits.open(path, memmap=True) as hdul:
        zavg = np.array(hdul[0].section[0], dtype="float32")
        nfd = hdul[0].header.get("DATE-OBS", os.path.basename(path))
    return zavg, nfd


def main():
    parser = argparse.ArgumentParser(
        description="Show the zavg plane of the latest FITS file in a directory "
        "and update the display as new files arrive.")
    parser.add_argument("directory", help="Observation directory to watch")
    parser.add_argument("-i", "--interval", type=float, default=2.0,
                        help="Polling interval in seconds [default: 2]")
    parser.add_argument("--cmap", default="gray_r",
                        help="Matplotlib colormap [default: gray_r]")
    args = parser.parse_args()

    fig, ax = plt.subplots(figsize=(10, 7))
    fig.canvas.manager.set_window_title(f"stvid monitor: {args.directory}")
    ax.set_axis_off()
    fig.subplots_adjust(left=0.02, right=0.98, bottom=0.02, top=0.94)
    state = {"fname": None, "im": None}

    def update():
        try:
            fname = latest_fits(args.directory)
        except OSError as e:
            ax.set_title(f"Cannot list {args.directory}: {e}", loc="left")
            fig.canvas.draw_idle()
            return
        if fname is None or fname == state["fname"]:
            if fname is None:
                ax.set_title(f"Waiting for FITS files in {args.directory}",
                             loc="left")
                fig.canvas.draw_idle()
            return

        try:
            zavg, nfd = read_zavg(os.path.join(args.directory, fname))
        except (OSError, ValueError, TypeError) as e:
            # Retry on the next tick rather than marking the file as shown
            print(f"Failed to read {fname}: {e}")
            return
        state["fname"] = fname

        vmin = np.mean(zavg) - 2.0 * np.std(zavg)
        vmax = np.mean(zavg) + 6.0 * np.std(zavg)
        if state["im"] is None or state["im"].get_array().shape != zavg.shape:
            ax.clear()
            ax.set_axis_off()
            state["im"] = ax.imshow(zavg, origin="lower", interpolation="none",
                                    vmin=vmin, vmax=vmax, cmap=args.cmap)
        else:
            state["im"].set_data(zavg)
            state["im"].set_clim(vmin, vmax)
        ax.set_title(f"{nfd}  ({fname})", loc="left")
        fig.canvas.draw_idle()

    update()
    timer = fig.canvas.new_timer(interval=int(args.interval * 1000))
    timer.add_callback(update)
    timer.start()
    plt.show()


if __name__ == "__main__":
    main()
