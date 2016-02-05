#!/usr/bin/python2 -u

import subprocess
import optparse
import sys

# Custom imports
sys.dont_write_bytecode = True
from libs import utils
from libs import config

# Defines
FAKESUM = "00000000000000000000000000000000"
CSUMLEN = len(FAKESUM)
FLAGLEN = 12

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
    parser.add_option("-c", "--checksum", dest="checksum",
                      help="Compute checksum for changed files",
                      action="store_true", default=False)
    parser.add_option("-k", "--fake-checksum", dest="fakechecksum",
                      help="Do not really compute checksum",
                      action="store_true", default=False)
    parser.add_option("-n", "--newer", dest="newer",
                      help="Consider only files changed since N minutes",
                      action="store", default=None)
    parser.add_option("-m", "--modified_only", dest="modified_only",
                      help="Consider only modified files, ignoring new files",
                      action="store_true", default=False)
    parser.add_option("--srcroot", dest="srcroot", action="store",
                      default=None)
    parser.add_option("--dstroot", dest="dstroot", action="store",
                      default=None)
    (options, args) = parser.parse_args()
    # Fake checksum implies checksum
    if options.fakechecksum:
        options.checksum = True
    # Checksum or modified_only automatically disables lite check
    if options.checksum or options.modified_only:
        options.lite = False
    # srcroot and dstroot
    options.srcroot = utils.normalize_dir(args[0])
    options.dstroot = utils.normalize_dir(args[1])
    return (options, args)

def execute(cmd, stdin=None):
    # Execute
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    (output, error) = process.communicate(stdin)
    # Output reporting
    if options.debug:
        print cmd
        if output:
            print output
    # Ignore specific rsync errors
    if process.returncode in utils.RSYNC_SUCCESS:
        process.returncode = 0
    # Error reporting
    if process.returncode:
        print "ERROR executing command "+str(cmd)
        if error:
            sys.stderr.write(error)
    return (process, output, error)

def checksum(source, basedir, changed):
    # Set initial values
    clist = {}
    changedfiles = "\n".join(set(changed))
    # Command selection
    if source == "L":
        cmd = ["xargs", "-d", "\n", config.csumbin, "-b", basedir]
    else:
        cmd = (["ssh"] + config.ssh_options +
               [options.dsthost, "xargs", "-d", "'\n'", config.csumbin,
                "-b", basedir])
    # Append other options
    if options.newer:
        cmd.append("-n")
        cmd.append(options.newer)
    if options.fakechecksum:
        cmd.append("-k")
    # Execute
    (process, output, error) = execute(cmd, changedfiles)
    if process.returncode or len(output) <= 0:
        return (process.returncode, clist)
    # Parse output
    for line in output.split("\n"):
        if len(line):
            csum = line[:CSUMLEN]
            name = line[CSUMLEN+1:]
            clist[name] = csum
    # Return
    return (process.returncode, clist)

def check(src, dst):
    # Set initial values
    alert = False
    count = 0
    if options.checksum:
        changed = []
    else:
        changed = ""
    # Check via rsync
    excludelist = utils.gen_exclude(options.rsync_excludes)
    try:
        excludelist.remove("--exclude=*"+config.safesuffix)
    except:
        pass
    rsync_args = ["-anui"]
    # Set filesize limit
    # For lite or modified_only checks, use the default from config.py
    # For full check or when using cheksum, increse size limit
    if options.checksum:
        rsync_args.append("--max-size=1024G")
    elif options.modified_only:
        pass
    elif options.lite:
        pass
    else:
        rsync_args.append("--max-size=1024G")
    # Construct command and execute
    cmd = (["rsync"] + options.extra + rsync_args + ["-n"] +
           excludelist + [src, dst])
    (process, output, error) = execute(cmd)
    if process.returncode:
        return (process.returncode, count, changed, alert)
    # Count changed files
    for line in output.split("\n"):
        # If empty, ignore
        if len(line) <= 0:
            continue
        # If not transfered, ignore
        if line[0] != "<" and line[0] != ">":
            continue
        # If checksum or modified_only, ignore new files
        if options.checksum and line[3] == "+":
            continue
        # Modified_only checks focus on existing files with different size
        elif options.modified_only and line[3] != "s":
            continue
        # Lite checks ignore existing files with same size
        elif options.lite and line[3] != "s" and line[3] != "+":
            continue
        # Alerts
        # For modified_only checks, raise an alert if size
        # of an existing file changed. Otherwise, continue
        if options.modified_only and line[3] == "s":
            alert = True
        # For full checks, raise an alert if size OR time
        # of an existing file changed. Otherwise, continue
        elif not options.lite and (line[3] == "s" or line[4] == "t"):
            alert = True
        # If we arrived here, the line is interesting.
        # Count changed lines
        count = count+1
        if options.checksum:
            changed.append(line[FLAGLEN:])
        else:
            changed = utils.concat(changed, line)
    # Return
    return (process.returncode, count, changed, alert)

def showrdiff(src, dst, changed):
    if len(changed):
        print "\nDifferences found while checking FROM "+src+" TO "+dst
        print changed.rstrip("\n")

def showcdiff(llist, rlist):
    # Initial values
    changed = ""
    alert = False
    for entry in llist:
        lsum = llist[entry]
        rsum = rlist[entry]
        # If sum is equal, continue
        if lsum == rsum:
            continue
        # If sum is zero, continue
        if lsum == FAKESUM or rsum == FAKESUM:
            continue
        # If sums differ
        changed = utils.concat(changed, entry)
        alert = True
    # If found, print the differing files
    if len(changed):
        print "\nDifferences found"
        print changed.rstrip("\n")
    return (alert, alert)


# Initial values and options parsing
error = 0
(options, args) = parse_options()
# Find changed files with rsync
(lcheck, lcount, lchanged, lalert) = check(options.srcroot,
                                           options.dsthost+":"+options.dstroot)
(rcheck, rcount, rchanged, ralert) = check(options.dsthost+":"+options.dstroot,
                                           options.srcroot)
# If rsync died with an error, quit
if lcheck or rcheck:
    error = 1
    quit(error)

# If checksum is needed, calculate it. Otherwise, print rsync output
if options.checksum:
    bchanged = lchanged + rchanged
    (lchecksum, llist) = checksum("L", options.srcroot, bchanged)
    (rchecksum, rlist) = checksum("R", options.dstroot, bchanged)
    if lchecksum or rchecksum:
        error = 1
    else:
        (lalert, ralert) = showcdiff(llist, rlist)
else:
    showrdiff(options.srcroot, options.dsthost+":"+options.dstroot, lchanged)
    showrdiff(options.dsthost+":"+options.dstroot, options.srcroot, rchanged)
# If checksum died with an error, quit
if error:
    quit(error)

# Error reporting
# 0: no differences at all
# 1: process error
# 2: alert
# 3: notice
if options.checksum:
    if lalert or ralert:
        error = 2
    else:
        error = 0
else:
    if lalert or ralert:
        error = 2
    elif (lcount+rcount) >= config.alert_threshold:
        error = 2
    elif (lcount+rcount) > 0:
        error = 3
    else:
        error = 0

# Lite checks have relaxed error codes
# 1 (process error) become 0
# 3 (notice) become 0
if options.lite:
    if error == 1:
        error = 0
    elif error == 3:
        error = 0

# Exit with error code
quit(error)
