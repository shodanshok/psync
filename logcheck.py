#!/usr/bin/python2
import optparse
import time
import re

L = {}
R = {}

def parse_options():
    parser = optparse.OptionParser()
    parser.add_option("-l", "--logfile", dest="logfile", action="store",
                      help="Logfile", default="/var/log/psync/psync.log")
    return parser.parse_args()

def scanlines():
    with open(options.logfile) as log:
        for line in log:
            match = re.search('\[(.*)\] \[.*\] \[.*\] \[.*\] \[.*\] ' +
                              '<f.[s+]....... (.*)', line)
            if match:
                timestamp = time.mktime(time.strptime(match.group(1),
                                   "%Y-%m-%d %H:%M:%S"))
                L[match.group(2)] = timestamp
                continue
            match = re.search('\[(.*)\] \[.*\] \[.*\] \[.*\] \[.*\] >f.[s+]....... (.*)', line)
            if match:
                timestamp = time.mktime(time.strptime(match.group(1),
                                        "%Y-%m-%d %H:%M:%S"))
                R[match.group(2)] = timestamp
                continue

def compare():
    found = False
    for left_entry in L:
        if left_entry in R:
            ltime = L[left_entry]
            rtime = R[left_entry]
            if abs(ltime-rtime) < 900:
                print "Double-edited entry: "+left_entry
            found = True
    return found

(options, args) = parse_options()
scanlines()
found = compare()
if found:
    quit(1)
else:
    quit(0)
