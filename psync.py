#!/usr/bin/python2

import collections
import subprocess
import threading
import optparse
import inspect
import hashlib
import os.path
import time
import sys
import os
import re

# Custom imports
sys.dont_write_bytecode = True
from libs import utils
from libs import config

# Globally writable objects
# Deque, dictionary and the likes
actions = collections.deque()   # Actions - source,method,itemtype,files,dstfile
locks = {'global':threading.Lock()} # Locks
dirs = {'L': {}, 'R': {}}           # Touched directories
pendings = {'L': {}, 'R': {}}       # L,R

# Current state
state = {
    'current_merges': 0,
}

schedules = {
    'fullsync': {'hours': config.fullsync}
}

# Heartbeats
heartbeats = {
    'L': {'last': time.time(), 'truelast': time.time(), 'ready': False,
          'timeout': config.timeout, 'itimeout': config.itimeout,
          'maxtimeout': config.maxtimeout},
    'R': {'last': time.time(), 'truelast': time.time(), 'ready': False,
          'timeout': config.timeout, 'itimeout': config.itimeout,
          'maxtimeout': config.maxtimeout},
    'reader': {'last': time.time(), 'timeout': config.timeout},
    'dequeue': {'last': time.time(), 'timeout': config.timeout},
    'execute': {'default': {'last': time.time(), 'timeout': config.etimeout}},
    # execute timeout MUST be LOWER than dequeue timeout
}

# Wrapper functions
def log(severity, source, message, raw=0, eventid=None):
    caller = inspect.stack()[1][3]
    thread = threading.current_thread()
    utils.log(severity, source, message, options.debug, caller, thread, raw,
              eventid)


def execute(cmd, source, stdin, warn=True,
            timeout=heartbeats['execute']['default']['timeout'], eventid=None):
    return utils.execute(cmd, source, stdin, warn=warn, timeout=timeout,
                         heartbeats=heartbeats, dryrun=options.dryrun,
                         debug=options.debug, eventid=eventid)

# Private functions
def parse_options():
    parser = optparse.OptionParser()
    parser.add_option("-d", "--debug", dest="debug", type="int",
                      help="Enable debugger", action="store",
                      default=config.debug)
    parser.add_option("-r", "--remote-host", dest="dsthost",
                      help="Remote host", action="store", default=None)
    parser.add_option("-t", "--tempfiles", dest="tempfiles",
                      help="Tempfile list (regex)", action="store",
                      default=config.tempfiles)
    parser.add_option("-e", "--excludes", dest="excludes", action="store",
                      help="Excluded files (regex)", default=config.excludes)
    parser.add_option("--rsync-excludes", dest="rsync_excludes",
                      help="Rsync exclusion list", action="append",
                      default=config.rsync_excludes)
    parser.add_option("-x", "--extra", dest="rsync_extra",
                      help="Extra rsync options", action="append",
                      default=config.rsync_extra)
    parser.add_option("-b", "--banned", dest="banned",
                      help="Exit immediately if BANNED program is running",
                      action="store", default=config.banned)
    parser.add_option("-T", "--translate", dest="translate",
                      help="Translate/replace path element", action="store",
                      default=config.translate)
    parser.add_option("-n", "--dry-run", dest="dryrun",
                      help="Simulate sync and log, but do nothing",
                      action="store_true", default=config.dryrun)
    parser.add_option("-s", "--sync-only", dest="synconly",
                      help="First sync only, then exit", action="store_true",
                      default=config.first_sync_only)
    parser.add_option("-k", "--skip-initial-sync", dest="skipsync",
                      help="Skip initial sync", action="store_true",
                      default=config.skip_initial_sync)
    parser.add_option("-f", "--force", dest="force", action="count",
                      help="Force delete/move commands",
                      default=config.force)
    parser.add_option("--srcroot", dest="srcroot", action="store",
                      default=None)
    parser.add_option("--dstroot", dest="dstroot", action="store",
                      default=None)
    (options, args) = parser.parse_args()
    # Let rsync be more verbose based of debug level
    if options.debug:
        options.rsync_extra.append("-v")
    if options.debug > 1:
        options.rsync_extra.append("--stats")
    # If dryrun, increase debug level
    if options.dryrun:
        options.debug = 2
        options.rsync_extra.append("-n")
    # Normalize directories
    options.srcroot = utils.normalize_dir(args[0])
    options.dstroot = utils.normalize_dir(args[1])
    # Define left and right private .psync dirs
    options.lpsyncdir = utils.normalize_dir(options.srcroot + config.psyncdir)
    options.rpsyncdir = utils.normalize_dir(options.dstroot + config.psyncdir)
    return (options, args)


def check_delete(filelist, source):
    filelist = utils.deconcat(filelist)
    if source == "L":
        root = options.dstroot
    else:
        root = options.srcroot
    protected = ""
    todelete = ""
    for filename in filelist:
        # Be extra careful on what we delete
        if len(filename) <= len(root):
            protected = utils.concat(protected, filename)
        else:
            todelete = utils.concat(todelete, filename)
    return (protected, todelete)


def dequeue():
    while True:
        beat("dequeue")
        try:
            action = actions.popleft()
        except:
            time.sleep(1)
            continue
        # Print queue length
        log(utils.DEBUG1, "B", "Actions queue length: "+
            str(len(actions)+1), eventid=action['eventid'])
        # Refresh pendings
        log(utils.DEBUG1, action['source'],
            "Dequeue, using method " + action['method'],
            eventid=action['eventid'])
        log(utils.DEBUG3, action['source'], "LV2 action: " + str(action),
            eventid=action['eventid'])
        if are_ready():
            # Select appropriate command
            if action['method'] == "RSYNC":
                rsync(action, acl=True)
            if action['method'] == "DELETE":
                delete(action)
            if action['method'] == "MOVE":
                move(action)
        else:
            for filename in utils.deconcat(action['filelist']):
                log(utils.ERROR, action['source'],
                    "Not connected, removing from queue event " +
                    action['method'] + config.separator + filename,
                    eventid=action['eventid'])


def get_mirror(source):
    if source == "L":
        mirror = "R"
    else:
        mirror = "L"
    return mirror


def check_pendings(source, filename, method, eventid=None):
    log(utils.DEBUG1, source, "Active pendings check", eventid=eventid)
    mirror = get_mirror(source)
    if source == "L":
        offset = len(options.srcroot)
    else:
        offset = len(options.dstroot)
    # Generate entry
    relname = filename[offset:]
    entry = method + config.separator + relname
    log(utils.DEBUG2, source, "Requesting: " + entry, eventid=eventid)
    # Check if a valid pending entry exists
    found = False
    now = time.time()
    for pending in pendings[mirror].keys():
        # If found...
        if pending == entry:
            # ...and if valid, ignore event
            if now-pendings[mirror][entry] <= config.pending_lifetime:
                found = True
                log(utils.DEBUG1, source,
                    "File found. Backfired inotify event " + entry,
                    eventid=eventid)
                if method == "MOVE":
                    log(utils.DEBUG2, source, "Removing: " + entry,
                        eventid=eventid)
                    pendings[mirror].pop(entry, None)
            else:
                # ... and if not valid, remove it from pending list
                log(utils.DEBUG2, source,
                    "Stale entry. Pretend nothing matched for " + entry,
                    eventid=eventid)
                pendings[mirror].pop(entry, None)
        else:
            # Clear old entries
            if now-pendings[mirror][pending] >= config.pending_lifetime:
                log(utils.DEBUG2, source, "Clearing stale entry " + pending)
                pendings[mirror].pop(pending, None)
    # Return True if found
    # Return False and insert it into pending list if not found
    if found:
        return True
    else:
        log(utils.DEBUG2, source, "Inserting: " + entry, eventid=eventid)
        pendings[source][entry] = time.time()
        return False

def delete(action):
    log(utils.DEBUG1, action['source'], "DELETE action",
        eventid=action['eventid'])
    # Command selection
    if action['source'] == "L":
        cmd = (["ssh"] + config.ssh_options +
               [options.dsthost, "xargs", "-d", "'\n'",
                config.helperbin, "-a", "DELETE"])
    else:
        cmd = ["xargs", "-d", "\n", config.helperbin, "-a", "DELETE"]
    # Forced?
    for i in range(options.force):
        cmd.append("-f")
    # Check if we can delete the required files
    (protected, todelete) = check_delete(action['filelist'], action['source'])
    # Calculate and append checksum
    tohash = utils.concat("DELETE", todelete)
    checksum = hashlib.md5(tohash).hexdigest()
    cmd = cmd + ["-c", checksum]
    # Execute and report
    if todelete:
        log(utils.DEBUG2, action['source'], "Preparing to delete: \n" +
            todelete, eventid=action['eventid'])
        execute(cmd, action['source'], todelete, eventid=action['eventid'])
    if protected:
        log(utils.INFO, action['source'], "Refusing to delete: \n" + protected,
            eventid=action['eventid'])
        action['method'] = "RSYNC"
        action['filelist'] = protected
        rsync(action)


def move(action):
    log(utils.DEBUG1, action['source'], "MOVE action",
        eventid=action['eventid'])
    # Command selection
    itemtype = action['itemtype']
    if action['source'] == "L":
        cmd = (["ssh"] + config.ssh_options +
               [options.dsthost, "xargs", "-d", "'\n'",
                config.helperbin, "-a", "MOVE"])
    else:
        cmd = ["xargs", "-d", "\n", config.helperbin, "-a", "MOVE"]
    # Forced?
    for i in range(options.force):
        cmd.append("-f")
    # Define source and target
    srcfile = action['filelist']
    dstfile = action['dstfile']
    # Calculate and append checksum
    tohash = utils.concat("MOVE", utils.concat(srcfile, dstfile))
    checksum = hashlib.md5(tohash).hexdigest()
    cmd = cmd + ["-c", checksum]
    # Execute and report
    log(utils.DEBUG2, action['source'], "Preparing to move: \n" +
        srcfile + " -> " + dstfile, eventid=action['eventid'])
    (process, output, error) = execute(cmd, action['source'],
                                       utils.concat(srcfile, dstfile),
                                       warn=False, eventid=action['eventid'])
    if process.returncode:
        log(utils.INFO, action['source'], error, eventid=action['eventid'])
        log(utils.INFO, action['source'], "MOVE failed. Retrying with RSYNC",
            eventid=action['eventid'])
    # After the move, do a recursive check with rsync
    action['method'] = "RSYNC"
    action['filelist'] = action['dstfile']
    action['recurse'] = True
    rsync(action)


def rsync(action, recurse=config.rsync_event_recurse, acl=False, warn=True):
    log(utils.DEBUG1, action['source'], "RSYNC action",
        eventid=action['eventid'])
    # Options selection
    rsync_options = []
    if action['backfired']:
        rsync_options.append("--existing")
    if recurse or action['recurse']:
        rsync_options.append("-r")
    if acl and (action['source'] == "L" or not config.acl_from_left_only):
        rsync_options.append("-AX")
    if action['flags'] == utils.FFORCE and config.maxsize:
        rsync_options.append(config.maxsize)
    # Command selection
    if action['source'] == "L":
        left = options.srcroot
        right = options.dsthost + ":" + options.dstroot
        filelist = action['filelist'].replace(left, "")
    else:
        left = options.dsthost + ":" + options.dstroot
        right = options.srcroot
        filelist = action['filelist'].replace(right, "")
    # Filelist mangling to remove duplicate
    if len(filelist) == 0:
        filelist = "/"
    else:
        fileset = set(utils.deconcat(filelist))
        filelist = "\n".join(fileset)
    # Generating exclude list
    excludelist = utils.gen_exclude(options.rsync_excludes)
    # Execute and report
    log(utils.DEBUG2, action['source'], "Preparing to sync: \n" + filelist,
        eventid=action['eventid'])
    cmd = (["rsync", "-ai"] + options.rsync_extra + rsync_options +
           ["--files-from=-"] + excludelist + [left, right])
    (process, output, error) = execute(cmd, action['source'], filelist,
                                       warn=warn, eventid=action['eventid'])
    if process.returncode == utils.RSYNC_TERMINATED:
        log(utils.INFO, action['source'], "Rescheduling files: \n" + filelist,
            eventid=action['eventid'])
        actions.append(action)


def full_syncher(oneshot=False):
    while True:
        # If oneshot, run full sync immediately
        if oneshot:
            log(utils.INFO, "B", "INITIAL SYNC\n" +
                "Please wait: this can take a long time")
        else:
            time.sleep(3600)
            log(utils.DEBUG2, "B", "TIMED FULL SYNC: Waking up")
            # Check if it's time of a scheduled fullsync
            hour = int(time.strftime("%H"))
            if hour not in schedules['fullsync']['hours']:
                log(utils.DEBUG2, "B", "TIMED FULL SYNC: not now. Sleeping...")
                continue
            log(utils.INFO, "B", "TIMED FULL SYNC: Starting")
        # Add required options
        rsync_options = ["-AX"]
        rsync_options.append("--max-size=1024G")
        # Proceed
        ldirs = "/"
        rdirs = "/"
        # First sync, from L to R
        success = True  # Be optimistic ;)
        excludelist = utils.gen_exclude(options.rsync_excludes)
        cmd = (["rsync", "-airu"] + options.rsync_extra + rsync_options +
               ["-u", "--files-from=-"] + excludelist +
               [options.srcroot, options.dsthost + ":" + options.dstroot])
        log(utils.INFO, "B",
            "Timed full sync from L to R started")
        (process, output, error) = execute(cmd, "L", ldirs, timeout=False)
        if process.returncode not in utils.RSYNC_SUCCESS:
            success = False
        # Second sync, from R to L
        if config.acl_from_left_only:
            try:
                rsync_options.remove("-AX")
            except:
                pass
        cmd = (["rsync", "-airu"] + options.rsync_extra + rsync_options +
               ["-u", "--files-from=-"] + excludelist +
               [options.dsthost + ":" + options.dstroot, options.srcroot])
        log(utils.INFO, "B",
            "Timed full sync from R to L started")
        (process, output, error) = execute(cmd, "R", rdirs, timeout=False)
        if process.returncode not in utils.RSYNC_SUCCESS:
            success = False
        log(utils.INFO, "B", "TIMED FULL SYNC: Ending")
        # If oneshot, return now
        if oneshot:
            return success


def connect_left():
    try:
        left.kill()
        log(utils.ERROR, "L", "KILLING FILTER WITH PID " + str(left.pid))
    except:
        pass
    # Kill any leftover
    cmd = ["killall", "-q", "filter.py"]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE).communicate()
    # Prepare filter command
    cmd = [config.filterbin, "--srcroot", options.srcroot,
           "-d", str(options.debug),
           "-e", options.excludes,
           "-k"]
    # Other options
    if options.tempfiles:
        cmd = cmd + ["-t", options.tempfiles]
    if options.translate:
        cmd = cmd + ["-T", options.translate]
    # Execute new filter instance
    log(utils.INFO, "L", "REGISTERING TO LOCAL  HOST")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=1)
    log(utils.DEBUG2, "L", "STARTED FILTER PID: " + str(process.pid))
    beat("L")
    heartbeats['L']['ready'] = False
    lreader = threading.Thread(name="lreader", target=reader,
                               args=(process, "L",))
    lreader.daemon = True
    lreader.start()
    return (process, lreader)


def connect_right():
    try:
        right.kill()
        log(utils.ERROR, "R", "KILLING FILTER WITH PID " + str(right.pid))
    except:
        pass
    # Kill any leftover
    cmd = (["ssh"] + config.ssh_options + [options.dsthost] +
           ["killall", "-q", "filter.py"])
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE).communicate()
    # Prepare filter command
    cmd = (["ssh"] + config.ssh_options + [options.dsthost] +
           [config.filterbin, "--srcroot", options.dstroot,
            "-d", str(options.debug),
            "-e", "'" + options.excludes + "'",
            "-k"])
    # Other options
    if options.tempfiles:
        cmd = cmd + ["-t", "'" + options.tempfiles + "'"]
    if options.translate:
        cmd = cmd + ["-T", "'" + options.translate + "'",]
    # Execute new filter instance
    log(utils.INFO, "R", "REGISTERING TO REMOTE HOST " + options.dsthost)
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=1)
    log(utils.DEBUG2, "R", "STARTED FILTER PID: " + str(process.pid))
    beat("R")
    heartbeats['R']['ready'] = False
    rreader = threading.Thread(name="rreader", target=reader,
                               args=(process, "R",))
    rreader.daemon = True
    rreader.start()
    return (process, rreader)


def is_connected(side):
    try:
        if side == "L":
            process = left
            reader = lreader
        else:
            process = right
            reader = rreader
        if not process:
            return False
        elif process.poll():
            return False
        elif not reader.is_alive():
            return False
        elif heartbeats[side]['ready'] and timedout(side):
            return False
        elif (not heartbeats[side]['ready'] and
              timedout(side, timeout_field="itimeout")):
            return False
        else:
            return True
    except:
        return False


def are_connected():
    both = is_connected("L") and is_connected("R")
    return both


def are_ready():
    connected = are_connected()
    if connected and heartbeats['L']['ready'] and heartbeats['R']['ready']:
        return True
    else:
        return False


def beat_inotify(source):
    beat(source)
    beat(source, "truelast")
    heartbeats[source]['ready'] = True


def register_dir(source, dirname):
    dirs[source][utils.normalize_dir(dirname)] = True
    log(utils.DEBUG2, source,
        "Registering directory for later check: " + dirname)


def unregister_dir(source, dirname):
    mirror = mirror = get_mirror(source)
    dirs[source].pop(utils.normalize_dir(dirname), None)
    dirs[mirror].pop(utils.normalize_dir(dirname), None)
    log(utils.DEBUG2, source,
        "Unregistering directory from later check: " + dirname)


def reader(process, source="B"):
    rogue = 0
    while True:
        # Select variables based on event source
        if source == "L":
            psyncdir = options.lpsyncdir
        else:
            psyncdir = options.rpsyncdir
        # Read line
        line = process.stdout.readline()
        line = line.strip(" \n")
        # If it is a log, print it
        match = re.match("^\[(.*?)\] \[(.*?):(.*?)\] \[(.*?)\]", line)
        if match:
            severity = match.group(3)
            line = line[len(match.group()) + 1:]
            # If it is an heartbeat-related log line, take note and continue
            if line.find(psyncdir + config.heartfile) >= 0:
                beat_inotify(source)
                log(utils.DEBUG3, source, line, 1)
            else:
                # Otherwise, simply print it
                log(severity, source, line, 1)
            continue
        # If HEART, take note and continue
        if line.find(psyncdir + config.heartfile) >= 0:
            beat_inotify(source)
            log(utils.DEBUG2, source, "heartbeat")
            continue
        # Check if connected
        if not are_ready():
            if len(line) > 0:
                log(utils.ERROR, source,
                    "Not connected, ignoring event: " + line)
            continue
        # Be sure to process a good formed line
        nfields = 6
        match = re.match("^(RSYNC|MOVE|DELETE|NONE)", line, flags=re.I)
        if not match or line.count(config.separator) != nfields:
            log(utils.WARNING, source,
                "Rogue line (n." + str(rogue) + "): " + line)
            rogue = rogue + 1
            if rogue >= 5:
                return
            else:
                continue
        else:
            rogue = 0
        entry = utils.deconcat(line, config.separator)
        method = entry[0]
        itemtype = entry[1]
        parent = utils.normalize_dir(entry[2])
        srcfile = entry[3]
        dstfile = entry[4]
        flags = entry[5]
        checksum = entry[6]
        # Validate checksum
        computed = line[:-len(config.separator + checksum)]
        computed = hashlib.md5(computed).hexdigest()
        if checksum != computed:
            log(utils.ERROR, source,
                "Ignoring event due to invalid checksum for line: " + line)
            log(utils.ERROR, source,
                "Received: " + checksum + " - Computed: " + computed)
            continue
        else:
            log(utils.DEBUG2, source, "Checksum ok. Received: " +
                checksum + " - Computed: " + computed)
        # Beat the heart
        beat_inotify(source)
        # If method is NONE, continue reading
        if method == "NONE":
            log(utils.INFO, source, "Ignoring event NONE for file: " + srcfile)
            continue
        # Parse event
        log(utils.DEBUG1, source, "Read event: " + line)
        # Pending checks
        if method in config.pending_events:
            backfired = check_pendings(source, srcfile, method)
        else:
            backfired = False
        if backfired:
            if method == "RSYNC" and config.rsync_style > 1:
                log(utils.DEBUG1, source, "Ignoring backfired event "+method+
                    config.separator + srcfile)
            continue
        # If batched rsync is true, continue to the next event
        if config.rsync_style == 3:
            continue
        # Normalize dir
        if itemtype == "DIR":
            srcfile = utils.normalize_dir(srcfile)
            if method == "MOVE":
                dstfile = utils.normalize_dir(dstfile)
        # Build filelist
        try:
            prev = actions.pop()
            # Is mergeable?
            if (
                    # source and method are same than previous
                    source == prev['source'] and method == prev['method'] and (
                        (
                            # method is rsync and other options are the same
                            prev['method'] == "RSYNC" and
                            prev['backfired'] == backfired and
                            prev['flags'] == flags
                        ) or (
                            # method is delete
                            prev['method'] == "DELETE"
                        )
                    )
                ):
                filelist = utils.concat(prev['filelist'], srcfile)
                state['current_merges'] = state['current_merges'] + 1
            else:
                state['current_merges'] = 0
                filelist = srcfile
                actions.append(prev)
        except:
            state['current_merges'] = 0
            filelist = srcfile
        log(utils.DEBUG1, source,
            "Current merges: " + str(state['current_merges']))
        entry = {'source': source, 'method': method, 'itemtype': itemtype,
                 'filelist': filelist, 'dstfile': dstfile,
                 'eventid': checksum[-5:], 'backfired': backfired,
                 'flags': flags, 'recurse': False}
        actions.append(entry)


def search_banned():
    if not options.banned:
        return
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            filedesc = open('/proc/' + pid + "/comm", 'r')
            comm = filedesc.readline().rstrip("\n")
            filedesc.close()
        except:
            continue
        if comm.find(options.banned) >= 0:
            log(utils.FATAL, "L",
                "FATAL: found banned program " + comm.rstrip("\n"))
            quit(1)


def timedout(names, attempts=1, heart_field="last", timeout_field="timeout",
             grace=0):
    # This is ugly, but it simplify the following rows
    heartbeat = heartbeats
    # Select correct heartbeat
    if type(names) is not list:
        names = [names]
    for name in names:
        try:
            heartbeat = heartbeat[name]
        except:
            return False
    # Load timeout
    timeout = heartbeat[timeout_field]
    if not timeout:
        return False
    # Check if timedout
    if time.time() - heartbeat[heart_field] >= (timeout * attempts) + grace:
        return True
    else:
        return False


def beat(name, heart_field="last"):
    heartbeats[name][heart_field] = time.time()


def runtime(name):
    return time.time() - state[name + "_time"]

# Parse options
(options, args) = parse_options()
# Synchronize peers
search_banned()
if options.skipsync:
    pass
else:
    if not full_syncher(True):
        log(utils.FATAL, "B",
            "FATAL: initial sync failed. Can not proceed furter. Sorry...")
        quit(2)
if options.synconly:
    if not full_syncher(True):
        log(utils.FATAL, "B",
            "FATAL: initial sync failed. Can not proceed furter. Sorry...")
        quit(2)
    else:
        log(utils.INFO, "B", "Initial sync completed. Exit now.")
        quit(0)
# Establish connections and start reading
(left, lreader) = connect_left()
(right, rreader) = connect_right()
# Propagate changes
replicator = threading.Thread(name="replicator", target=dequeue)
replicator.daemon = True
replicator.start()
# Timed FULL checker/synchronization
full_syncher = threading.Thread(name="syncher", target=full_syncher)
full_syncher.daemon = True
full_syncher.start()

while True:
    # Verify that no harmful process are running
    search_banned()
    # Check for (and kill) slow processes
    for pid in heartbeats['execute'].keys():
        # If pid is not numeric, something is wrong. Continue with next process
        if type(pid) is not int:
            continue
        # If process does not exists anymore in the list, continue
        try:
            process = heartbeats['execute'][pid]['process']
        except:
            continue
        # If process was terminated/killed, remove it from list and continue
        if process.poll():
            heartbeats['execute'].pop(pid, None)
            continue
        # If the process does not terminate, kill it
        if timedout(['execute', pid], grace=10):
            try:
                process.kill()
            except:
                pass
            log(utils.WARNING, "B",
                "SLOW PROCESS WITH PID " + str(pid) +
                " KILLED: " + str(process))
        # Try to gracefully terminate the process
        elif timedout(['execute', pid]):
            try:
                process.terminate()
            except:
                pass
            log(utils.INFO, "B",
                "SLOW PROCESS WITH PID " + str(pid) +
                " TERMINATED: " + str(process))
    # If connections establishment is impossible, quit
    if timedout("L", heart_field='truelast', timeout_field="maxtimeout"):
        log(utils.FATAL, "L",
            "FATAL: Can not re-establish local  connection. " +
            "Exiting now. Sorry...")
        quit(3)
    if timedout("R", heart_field='truelast', timeout_field="maxtimeout"):
        log(utils.FATAL, "R",
            "FATAL: Can not re-establish remote connection. " +
            "Exiting now. Sorry...")
        quit(4)
    # Check left pipe and producer thread
    if not is_connected("L"):
        log(utils.ERROR, "L",
            "Lost connection to local  host\n" + "Reconnetting...")
        (left, lreader) = connect_left()
    # Check right pipe and producer thread
    if not is_connected("R"):
        log(utils.ERROR, "R",
            "Lost connection to remote host\n" + "Reconnecting...")
        (right, rreader) = connect_right()
    # Check consumer thread
    if timedout("dequeue"):
        log(utils.FATAL, "B", "Blocked or crashed dequeue thread. Exiting")
        quit(5)
    else:
        log(utils.DEBUG2, "B",
            "Running dequeue thread. Last seen on " +
            time.strftime("%Y-%m-%d %H:%M:%S",
                          time.localtime(heartbeats['dequeue']['last'])))
    time.sleep(5)
