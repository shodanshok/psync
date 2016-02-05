#!/usr/bin/python2

import optparse
import hashlib
import time
import sys
import os

# Custom imports
sys.dont_write_bytecode = True

# Defines
FAKESUM = "00000000000000000000000000000000"
CSUMLEN = len(FAKESUM)

def parse_options():
    parser = optparse.OptionParser()
    parser.add_option("-b", "--basedir", dest="basedir",
                      help="Base directory",
                      action="store", default="/")
    parser.add_option("-c", "--chunksize", dest="chunksize",
                      help="Chunk size when reading file",
                      action="store", default=1024*1024)
    parser.add_option("-n", "--newer", dest="newer",
                      help="Only check files changed since last N minutes",
                      action="store", default=None)
    parser.add_option("-k", "--fake-checksum", dest="fakechecksum",
                      help="Do not really compute checksum",
                      action="store_true", default=False)
    (options, args) = parser.parse_args()
    # Normalize basedir
    options.basedir = options.basedir.rstrip("/")+"/"
    return (options, args)

def summarize(args):
    # Iterate between files
    for arg in args:
        # Prepend basedir
        arg = options.basedir+(arg.lstrip("/"))
        # Default values
        mtime = 0
        digest = FAKESUM
        csum = hashlib.md5()
        # Prepare reftime
        if options.newer:
            reftime = time.time() - int(options.newer)*60
        else:
            reftime = 0
        # Read file
        try:
            stat = os.stat(arg)
            mtime = stat.st_mtime
            # Compare mtime with reftime. If newer, proceed
            if mtime >= reftime:
                # If fakechecksum, cheat
                if options.fakechecksum:
                    size = stat.st_size
                    digest = str(size).zfill(32)
                else:
                # Read and compute checksum
                    with open(arg, "rb") as f:
                        while True:
                            buf = f.read(options.chunksize)
                            if len(buf):
                                csum.update(buf)
                            else:
                                break
                    digest = csum.hexdigest()
        except:
            pass
        # Print data
        print digest, arg

(options, args) = parse_options()
summarize(args)
