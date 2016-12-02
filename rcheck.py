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
    parser.add_option("-m", "--modified_only", dest="modified_only",
                      help="Consider only modified files, ignoring new files",
                      action="store_true", default=False)
    parser.add_option("-X", "--nolinks", dest="nolinks",
                      help="Exclude links from comparison",
                      action="store_true", default=False)
    parser.add_option("-b", "--backup", dest="backup", help="Do backups",
                      action="store_true", default=False)
    parser.add_option("--srcroot", dest="srcroot", action="store",
                      default=None)
    parser.add_option("--dstroot", dest="dstroot", action="store",
                      default=None)
    (options, args) = parser.parse_args()
    # Checksum or modified_only automatically disables lite check
    if options.checksum or options.modified_only:
        options.lite = False
    # srcroot and dstroot
    options.srcroot = utils.normalize_dir(args[0])
    options.dstroot = utils.normalize_dir(args[1])
    return (options, args)

def execute(cmd, stdin=None):
    # Execute
    if options.debug:
        print "cmd: "+str(cmd)
        print "stdin: "+stdin
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    (output, error) = process.communicate(stdin)
    # Output reporting
    if options.debug and output:
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

def check(src, dst, filelist="", checksum=False):
    # If checksum is enabled, continue only with a filelist
    if not filelist and checksum:
        return 0, ""
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
    if options.modified_only or options.lite:
        pass
    else:
        rsync_args.append("--max-size=1024G")
    # Enable checksum
    if checksum:
        rsync_args.append("--checksum")
    # Link disabling
    if options.nolinks:
        try:
            options.extra.remove("-L")
        except:
            pass
        rsync_args.append("--no-l")
    # Pass filelist
    if filelist:
        rsync_args.append("--files-from=-")
    # Construct command and execute
    cmd = (["rsync"] + options.extra + rsync_args + ["-n"] +
           excludelist + [src, dst])
    (process, output, error) = execute(cmd, filelist)
    # Return
    return process.returncode, output

def parse_output(output, strip=False, checksum=False):
    # Initial values
    count = 0
    changed = ""
    alert = False
    # Count changed files
    for line in output.split("\n"):
        # If empty, ignore
        if len(line) <= 0:
            continue
        # If not transfered, ignore
        if line[0] != "<" and line[0] != ">":
            continue
        # If local checksum, ignore any matching files:
        if checksum and line[2] != "c":
            continue
        # If checksum or modified_only, ignore new files
        elif (options.checksum or options.modified_only) and line[3] == "+":
            continue
        # Lite checks ignore existing files with same size
        elif options.lite and line[3] != "s" and line[3] != "+":
            continue
        # If we arrived here, the line is interesting.
        # Count changed lines
        count = count+1
        # If strip, grep the filename only
        if strip:
            line = line[FLAGLEN:]
        # Append the changed line
        changed = utils.concat(changed, line)
        # Alerts
        # For checksum, raise an alert for a non-matching file
        if checksum and line[2] == "c":
            alert = True
        # For full checks, raise an alert if size OR time
        # of an existing file changed. Otherwise, continue
        elif not options.lite and (line[3] == "s" or line[4] == "t"):
            alert = True
    # Return
    return (count, changed, alert)

def showrdiff(src, dst, changed):
    if len(changed):
        print "\nDifferences found while checking FROM "+src+" TO "+dst
        print changed.rstrip("\n")

def dosidebackup(changed, side):
    if not changed:
        return (None, None, None)
    rsync_args = ["-avAX"]
    filelist = ""
    for line in utils.deconcat(changed):
        if line[2] == "+":
            continue
        line = line[FLAGLEN:]
        filelist = utils.concat(filelist, line)
    if not filelist:
        return (None, None, None)
    cmd = (["rsync"] + options.extra + rsync_args +
           ["--files-from=-", side, backupdir])
    (process, output, error) = execute(cmd, filelist)
    return (process, output, error)

def dobackup(lchanged, rchanged):
    (lprocess, loutput, lerror) = dosidebackup(lchanged, dst)
    (rprocess, routput, rerror) = dosidebackup(rchanged, src)
    if not lprocess and not rprocess:
        return
    print
    print "Doing backups..."
    print loutput
    print
    print routput
    print "...done"

# Initial values and options parsing
error = 0
(options, args) = parse_options()
(src, dst) = (options.srcroot, options.dsthost+":"+options.dstroot)
backupdir = utils.normalize_dir(src+config.backupdir)
# Find changed files with rsync
(lcheck, loutput) = check(src, dst)
(rcheck, routput) = check(dst, src)
if lcheck or rcheck:
    error = 1
    quit(error)
# Parse rsync output
(lcount, lchanged, lalert) = parse_output(loutput, strip=options.checksum)
(rcount, rchanged, ralert) = parse_output(routput, strip=options.checksum)
# If checksum, do the second pass
if options.checksum:
    # Only check the specified files
    (lcheck, loutput) = check(src, dst, filelist=lchanged, checksum=True)
    (rcheck, routput) = check(dst, src, filelist=rchanged, checksum=True)
    if lcheck or rcheck:
        error = 1
        quit(error)
    # Parse rsync output
    (lcount, lchanged, lalert) = parse_output(loutput, checksum=True)
    (rcount, rchanged, ralert) = parse_output(routput, checksum=True)
# Print the differences
showrdiff(src, dst, lchanged)
showrdiff(dst, src, rchanged)

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

# If needed, do backups
if options.backup:
    dobackup(lchanged, rchanged)

# Exit with error code
quit(error)
