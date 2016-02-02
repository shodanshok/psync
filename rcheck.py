#!/usr/bin/python2 -u

import subprocess
import optparse
import sys

# Custom imports
sys.dont_write_bytecode = True
from libs import utils
from libs import config

def parse_options():
    parser = optparse.OptionParser()
    parser.add_option("-r", "--remote-host", dest="dsthost",
                      help="Remote host", action="store", default=None)
    parser.add_option("-e", "--exclude", dest="rsync_excludes",
                      help="Files to exclude", action="append",
                      default=config.rsync_excludes)
    parser.add_option("-x", "--extra", dest="extra",
                      help="Extra rsync options", action="append",
                      default=config.rsync_extra)
    parser.add_option("-d", "--debug", dest="debug", help="Debug",
                      action="store", default=config.debug)
    parser.add_option("-l", "--lite", dest="lite", help="Relaxed checks",
                      action="store_true", default=False)
    parser.add_option("-m", "--modified-only", dest="modified_only",
                      help="Check for modified files, ignoring new files",
                      action="store_true", default=False)
    parser.add_option("--srcroot", dest="srcroot", action="store",
                      default=None)
    parser.add_option("--dstroot", dest="dstroot", action="store",
                      default=None)
    (options, args) = parser.parse_args()
    # srcroot and dstroot
    options.srcroot = utils.normalize_dir(args[0])
    options.dstroot = utils.normalize_dir(args[1])
    return (options, args)

def check(src, dst):
    # Set initial values
    changed = ""
    alert = False
    count = 0
    # Check via rsync
    excludelist = utils.gen_exclude(options.rsync_excludes)
    try:
        excludelist.remove("--exclude=*"+config.safesuffix)
    except:
        pass
    rsync_args = ["-anu", "--out-format=%i %n%L %l"]
    if not (options.lite or options.modified_only):
        rsync_args.append("--max-size=1024G")
    cmd = (["rsync"] + options.extra + rsync_args + ["-n"] +
           excludelist + [src, dst])
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    (output, error) = process.communicate()
    if options.debug:
        print cmd
        print output
    if process.returncode != 0 and process.returncode != 23:
        print "ERROR while checking!"
        sys.stderr.write(error)
        return (process.returncode, count, alert)
    # Count changed files
    for line in output.split("\n"):
        # If empty, ignore
        if len(line) <= 0:
            continue
        # If not transfered, ignore
        if line[0] != "<" and line[0] != ">":
            continue
        # New or existing file?
        if line[3] == "+":
            if options.modified_only:
                continue
        else:
            # For lite checks, raise an alert if size AND time
            # of an existing file changed. Otherwise, ignore
            if options.lite:
                if line[3] == "s" and line[4] == "t":
                    alert = True
                else:
                    continue
            # For full checks, raise an alert if size OR time
            # of an existing file changed. Otherwise, continue
            else:
                if line[3] == "s" or line[4] == "t":
                    alert = True
        # If we arrived here, the line is interesting.
        # Count changed lines
        changed = changed + " " + line + "\n"
        count = count+1
    # If something changed, report it back
    if len(changed):
        print "\nDifferences found while checking FROM "+src+" TO "+dst
        print changed.rstrip("\n")
    return (0, count, alert)

# Run
(options, args) = parse_options()
(lcheck, lchanged, lalert) = check(options.srcroot,
                                   options.dsthost+":"+options.dstroot)
(rcheck, rchanged, ralert) = check(options.dsthost+":"+options.dstroot,
                                   options.srcroot)

# Error reporting is as follow (full/lite):
# a) exit 0/0: no error, no differences
# b) exit 1/0: any error
# c) exit 2/3: no error, many differences
# d) exit 3/3: no error, some differences
# e) exit 4/0: no error, very few differences
if lcheck == 0 and rcheck == 0:
    if (lchanged+rchanged) >= config.warning_threshold:
        error = 2
    elif (lchanged+rchanged) >= config.alert_threshold:
        error = 3
    elif (lchanged+rchanged) > 0:
        error = 4
    else:
        error = 0
else:
    error = 1

# If alerted and this is a full check OR
# modified_only is true, raise error level
if (lalert or ralert):
    if not options.lite or options.modified_only:
        error = min(error, 3)

# Lite checks have relaxed error codes
if options.lite:
    if error == 1:
        error = 0
    elif error == 2:
        error = 3
    elif error == 4:
        error = 0

# Exit with error code
quit(error)
