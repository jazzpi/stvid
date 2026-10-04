#!/usr/bin/env python3
"""Plate solve the observation closest to a given UTC time, showing solve-field output."""
import os
import sys
import glob
import shutil
import argparse
import tempfile
import subprocess
import configparser
from datetime import datetime

import warnings
import astropy.units as u
from astropy.io import fits
from astropy.time import Time
from astropy.coordinates import SkyCoord, AltAz, EarthLocation
from astropy.wcs.utils import proj_plane_pixel_scales
from astropy.utils.exceptions import AstropyWarning

from stvid import calibration
from stvid.fourframe import AstrometricCatalog


def file_time(fname):
    return datetime.strptime(os.path.basename(fname), "%Y-%m-%dT%H-%M-%S.%f.fits")


def parse_time(s):
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        name = os.path.basename(s)
        return file_time(name if name.endswith(".fits") else f"{name}.fits")


def find_closest(directory, t):
    # Observations live in <obs>/<date>_<device>/<HHMMSS>/, but also accept a run directory
    fnames = glob.glob(os.path.join(directory, "**", "2*.fits"), recursive=True)
    fnames = [f for f in fnames if not f.endswith("test.fits")]
    if not fnames:
        return None
    return min(fnames, key=lambda f: abs((file_time(f) - t).total_seconds()))


def print_pointing(fname, cfg, w):
    header = fits.getheader(fname)
    t = Time(header["MJD-OBS"], format="mjd", scale="utc")
    nx, ny = header["NAXIS1"], header["NAXIS2"]

    if all(key in header for key in ["SITELONG", "SITELAT", "ELEVATIO"]):
        lon, lat, height = header["SITELONG"], header["SITELAT"], header["ELEVATIO"]
    else:
        lon = cfg.getfloat("Observer", "longitude")
        lat = cfg.getfloat("Observer", "latitude")
        height = cfg.getfloat("Observer", "height")
    location = EarthLocation(lon=lon * u.deg, lat=lat * u.deg, height=height * u.m)

    # RA/Dec drifts with time for a fixed camera; Alt/Az and rotation are what stay put
    center = SkyCoord.from_pixel(nx / 2, ny / 2, w, 0)
    up = SkyCoord.from_pixel(nx / 2, ny / 2 + 100, w, 0)
    altaz = center.transform_to(AltAz(obstime=t, location=location))
    rotation = center.position_angle(up).wrap_at(180 * u.deg).degree
    scales = proj_plane_pixel_scales(w) * 3600

    print(f"\nPointing at {t.isot} UTC:")
    print(f"  RA/Dec:    {center.ra.degree:9.4f} {center.dec.degree:+9.4f} deg")
    print(f"  Az/Alt:    {altaz.az.degree:9.4f} {altaz.alt.degree:+9.4f} deg")
    print(f"  Rotation:  {rotation:+9.3f} deg (+y axis, E of N)")
    print(f"  Scale:     {scales[0]:.2f} x {scales[1]:.2f} arcsec/pix")
    print(f"  Field:     {nx * scales[0] / 3600:.2f} x {ny * scales[1] / 3600:.2f} deg")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plate solve the frame closest to a UTC time.")
    parser.add_argument("time", metavar="FILE_OR_TIME", help="Path to a FITS file, or a UTC time / FITS filename to search for (e.g. '2026-06-23 23:38:30')")
    parser.add_argument("-c", "--conf_file", default="configuration.ini",
                        help="Configuration file (default: configuration.ini)")
    parser.add_argument("-d", "--directory",
                        help="Directory to search (default: observations_path from config)")
    parser.add_argument("-k", "--keep", action="store_true",
                        help="Keep the working directory with solve-field outputs")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show star count and solve-field output")
    args = parser.parse_args()

    cfg = configparser.ConfigParser(inline_comment_prefixes=("#", ":"))
    if not cfg.read(args.conf_file):
        sys.exit(f"Could not read config file: {args.conf_file}")

    warnings.filterwarnings("ignore", category=UserWarning, append=True)
    warnings.simplefilter("ignore", AstropyWarning)

    if os.path.isfile(args.time):
        src = args.time
    else:
        t = parse_time(args.time)
        directory = args.directory or cfg.get("Setup", "observations_path")
        src = find_closest(directory, t)
        if src is None:
            sys.exit(f"No FITS files found under {directory}")
        print(f"Closest frame: {src} ({(file_time(src) - t).total_seconds():+.1f} s)")

    # Work on a copy so solve-field/calibrate outputs don't land in the observation directory
    workdir = tempfile.mkdtemp(prefix="plate_solve_")
    fname = os.path.join(workdir, os.path.basename(src))
    shutil.copy(src, fname)
    froot = os.path.splitext(fname)[0]

    try:
        scat = calibration.generate_star_catalog(fname)
        nstarsmin = cfg.getint("Astrometry", "min_stars")
        if args.verbose:
            print(f"Source extractor found {scat.nstars} stars (min_stars = {nstarsmin})")
        if scat.nstars <= nstarsmin:
            print(f"Only {scat.nstars} stars found (min_stars = {nstarsmin}): "
                  "process.py would not attempt a plate solve on this frame; trying anyway.")

        cmd_args = cfg.get("Astrometry", "solve-field_args", fallback="")
        command = f"solve-field {cmd_args} {fname}"
        if args.verbose:
            print(f"\nRunning: {command}\n")
            subprocess.run(command, shell=True, cwd=workdir)
            print()
        else:
            subprocess.run(command, shell=True, cwd=workdir,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if not os.path.exists(f"{froot}.new"):
            hint = "" if args.verbose else " (rerun with -v for solve-field output)"
            sys.exit(f"Plate solve FAILED{hint}")

        wref, tref = calibration.read_calibration(f"{froot}.new")
        print(f"Plate solve succeeded: RA {wref.wcs.crval[0]:.4f}, Dec {wref.wcs.crval[1]:.4f}")

        # Same per-frame refinement process.py does after obtaining a reference solve
        acat = AstrometricCatalog(cfg.getfloat("Astrometry", "max_magnitude"))
        w, rmsx, rmsy, nused, is_calibrated = calibration.calibrate(fname, cfg, acat, scat, wref, tref)
        status = "calibrated" if is_calibrated else "NOT calibrated"
        print(f"Calibration: {status}, rms {rmsx:.2f}\" x {rmsy:.2f}\", {nused}/{scat.nstars} stars matched")

        print_pointing(fname, cfg, w if is_calibrated else wref)
    finally:
        if args.keep:
            print(f"\nOutputs kept in {workdir}")
        else:
            shutil.rmtree(workdir)
