#!/usr/bin/env python3

"""Apply a mask to a four-frame .fits file."""

import argparse
import datetime
import sys
import numpy as np
from astropy.io import fits

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apply a mask to a four-frame .fits file.")
    parser.add_argument("input", help="Input four-frame .fits file")
    parser.add_argument("mask", help="Mask .fits file (2D boolean array)")
    parser.add_argument("--time-offset", type=float, default=0.0, help="Time offset to apply to the data (default: 0.0)")
    args = parser.parse_args()

    with fits.open(args.mask) as hdu:
        mask_header = hdu[0].header
        mask_data = hdu[0].data

        if mask_header["NAXIS"] != 2:
            print(f"Mask file {args.mask} is not a 2D FITS image. Exiting...")
            sys.exit()

        # Ensure the mask is a boolean array
        mask = mask_data.astype(bool)

    with fits.open(args.input, mode='update') as hdu:
        data = hdu[0].data

        # Check if the mask shape matches the data shape (excluding the first dimension)
        if data.shape[1:] != mask.shape:
            print(f"Mask shape {mask.shape} does not match data shape {data.shape[1:]}. Exiting...")
            sys.exit()
        
        # Apply the mask to the data
        data[:, ~mask] = 0

        # Apply time offset if specified
        if args.time_offset != 0.0:
            nfd = hdu[0].header["DATE-OBS"]
            # Parse the YYYY-MM-DDTHH:MM:SS.sss format and apply the time offset
            t = datetime.datetime.strptime(nfd, "%Y-%m-%dT%H:%M:%S.%f") + datetime.timedelta(seconds=args.time_offset)
            hdu[0].header["DATE-OBS"] = t.isoformat()

        hdu.flush()

    print(f"Masked four-frame .fits file saved to {args.input}")
