#!/usr/bin/python2

import collections
import subprocess
import threading
import optparse
import inspect
import hashlib
import time
import math
import sys
import os
import re

# Custom imports
sys.dont_write_bytecode = True
from libs import utils
from libs import config

# Dequeues
raw_queue = collections.deque() #raw events
actions = collections.deque() #method,itemtype,dir,file,dstfile

def parse_options():
    parser = optparse.OptionParser()
    parser.add_option("-d", "--debug", dest="debug", type="int",
                      help="Enable debugger", action="store",
                      default=config.debug)
    parser.add_option("-t", "--tempfiles", dest="tempfiles", action="store",
                      help="Tempfile list (regex)", default=config.tempfiles)
    parser.add_option("-e", "--excludes", dest="excludes", action="store",
                      help="Excluded files (regex)", default=config.excludes)
    parser.add_option("-k", "--kill", dest="kill", action="store_true",
                      help="Kill other inotify processes", default=False)
    parser.add_option("-i", "--interval", dest="interval", action="store",
                      type="int",
                      help="Interval between event collection/notification",
                      default=config.event_interval)
    parser.add_option("-T", "--translate", dest="translate",
                      help="Translate/replace path element", action="store",
                      default=config.translate)
    parser.add_option("--srcroot", dest="srcroot",
                      action="store", default=None)
    (options, args) = parser.parse_args()
    # Define base dirs
    options.srcroot = utils.normalize_dir(options.srcroot)
    options.psyncdir = utils.normalize_dir(options.srcroot+config.psyncdir)
    return (options, args)

def log(severity, message):
    caller = inspect.stack()[1][3]
    thread = threading.current_thread()
    utils.log(severity, "U", message, options.debug, caller, thread)

def delay_action(action):
    actions.appendleft(action)
    sleeptime = time.time() - action['timestamp']
    time.sleep(options.interval - sleeptime)

def rsync_file_exists(action):
    # Is the to-be-synched file a valid one?
    try:
        stat = os.stat(action['file'])
        return stat
    except:
        log(utils.DEBUG2,
            "LV1 event: skipping stale RSYNC event " +
            "for file: "+action['file'])
        return None

def rsync_early_checks(action):
    if action['method'] != "RSYNC":
        return True
    # File exists?
    stat = rsync_file_exists(action)
    if not stat:
        return False
    # Current timestamp
    now = time.time()
    # Was the file really modified?
    if now - stat.st_mtime > config.delay:
        # The file is "old". Using relaxed ctime check due to
        # Explorer delaying CLOSE_WRITE during copies
        if now - stat.st_ctime > config.delay:
            log(utils.DEBUG2,
                "LV1 event: skipping non-modifying RSYNC event (type 01) " +
                "for file: "+action['file'])
            return False
    else:
        # The file is very new. Using strict ctime check to avoid
        # backfire and unwanted rsync events
        if now - stat.st_ctime > options.interval:
            log(utils.DEBUG2,
                "LV1 event: skipping non-modifying RSYNC event (type 02) " +
                "for file: "+action['file'])
            return False
    # Suppress backfire from Explorer
    (st_mtime_f, st_mtime_i) = math.modf(stat.st_mtime)
    # If mtime has no fractional part and
    # atime is newer than ctime and mtime is recent, this can be
    # an Explorer-backfired RSYNC event. Skip it
    if (not st_mtime_f and stat.st_atime+1 > stat.st_ctime and
            now - stat.st_mtime+1 < config.delay):
        log(utils.DEBUG2,
            "LV1 event: skipping Explorer-backfired RSYNC event (type 03) " +
            "for file: "+action['file'])
        return False
    # If all is ok, return True
    return True

def rsync_late_checks(action):
    if action['method'] != "RSYNC":
        return True
    # File exists?
    stat = rsync_file_exists(action)
    if not stat:
        return False
    # Current timestamp
    now = time.time()
    # Is the file currently being written?
    if time.time() - stat.st_ctime <= min(1, options.interval):
        log(utils.INFO,
            "LV1 event: delaying currently changing file " +
            action['file'])
        return False
    # If all is ok, return True
    return True

def dequeue():
    while True:
        try:
            action = actions.popleft()
            # Delay interval time
            if time.time() - action['timestamp'] >= options.interval:
                if action['file'] != heartfile:
                    log(utils.DEBUG3, "LV1 action: "+str(action))
                # Are we sure to delete?
                if action['method'] == "DELETE":
                    if os.path.exists(action['file']):
                        log(utils.DEBUG2,
                            "LV1 event: change from DELETE to RSYNC " +
                            "for file: " + action['file'])
                        action['method'] = "RSYNC"
                # Late rsync checks
                if action['method'] == "RSYNC":
                    if not rsync_late_checks(action):
                        continue
                # Construct and print line
                line = (action['method'] + config.separator +
                        action['itemtype'] + config.separator +
                        action['dir'] + config.separator +
                        str(action['file']) + config.separator +
                        str(action['dstfile']))
                checksum = hashlib.md5(line).hexdigest()
                print line + config.separator + checksum + "\n",
                sys.stdout.flush()
            else:
                delay_action(action)
        except:
            touch(heartfile)
            time.sleep(1)

def prepare_system():
    create_psyncdir()
    subprocess.Popen(["sysctl", "-q", "-w", "fs.inotify.max_user_watches=" +
                      str(16*1024*1024)]).communicate()
    subprocess.Popen(["sysctl", "-q", "-w", "fs.inotify.max_queued_events=" +
                      str(512*1024)]).communicate()
    if options.kill:
        tokill = os.path.basename(config.inotifybin)
        subprocess.Popen(["killall", "-q", tokill]).communicate()

def launch_inotify():
    # Force disable debug
    try:
        config.inotify_extra.remove("-d")
    except:
        pass
    # Prepare process
    process = subprocess.Popen([config.inotifybin] + config.inotify_extra +
                               [options.srcroot], stdout=subprocess.PIPE,
                               bufsize=1)
    return process

def read_inotify():
    while True:
        line = inotify.stdout.readline()
        raw_queue.append(line)

def sanitize_path(path):
    if path[:1] == config.separator[-1:] or path[-1:] == config.separator[:1]:
        return False
    else:
        return True

def safeline(line):
    # Check for bad formed line
    if line.count(config.separator) != 4:
        log(utils.WARNING, "Strange line (type S1): "+line)
        return False
    # Check for sane path/file names
    event, dirname, filename, dstfile, end = utils.deconcat(line,
                                                            config.separator,
                                                            False)
    if not sanitize_path(dirname) or not sanitize_path(filename):
        log(utils.WARNING, "Strange line (type S2): "+line)
        return False
    # If all it's ok, return success
    return True

def inotifylog(line):
    if line.startswith("error:"):
        if not line.find(config.safesuffix):
            log(utils.WARNING, line)
        return True
    if line.startswith("info:"):
        log(utils.DEBUG1, line)
        return True

def translate(line):
    original = line
    frompath, topath = utils.deconcat(options.translate, config.separator)
    if topath == "None":
        topath = ""
    if line.find(frompath) >= 0:
        translated = True
        line = line.replace(frompath, topath)
        log(utils.DEBUG2, "Translate: " + original + " -> " + line)
    else:
        translated = False
    return translated, original, line

def parse_line(line):
    line = line.rstrip("\n")
    # Check if it's an inotify logline
    if inotifylog(line):
        return
    # Check for safety
    if not safeline(line):
        return
    log(utils.DEBUG2, "Raw EVENT: "+line)
    # Translate and re-check for safety
    if options.translate:
        translated, original, line = translate(line)
        if not safeline(line):
            return
    else:
        translated = False
    # If safe, go ahead
    event, dirname, filename, dstfile, end = utils.deconcat(line,
                                                            config.separator,
                                                            False)
    # Item identification
    dirname = utils.normalize_dir(dirname)
    if event.find(",ISDIR") >= 0:
        itemtype = "DIR"
        filename = utils.normalize_dir(filename)
        dstfile = utils.normalize_dir(dstfile)
    else:
        itemtype = "FILE"
    event = utils.deconcat(event, ",")[0]
    # Select sync method and skip unwanted events
    # On directories, CREATE is skipped to avoid backfire from rsync
    # On files, CREATE is skipped because we want to sync only
    # closed/CLOSE_WRITE (ie: complete) files.
    # To expand: when files are CREATED but not CLOSED, the mtime
    # attribute can be 'wrong' (ie: newer) then what it should be
    # Example: a file which need 60 seconds to be uploaded, will have
    # a constantly-changing mtime until the upload complete, when the mtime
    # will be rolled back to the original value.
    # This behavior is application dependent, but we can't risk: a wrong
    # mtime can led to wrong replication direction and truncated file.
    if event == "CREATE":
        log(utils.DEBUG2, "Skipping uninteresting event for "+filename)
        return
    if event.find("SELF") >= 0:
        log(utils.DEBUG2, "Skipping uninteresting event for "+filename)
        return
    # Method selection
    if event == "ATTRIB" or event == "CLOSE_WRITE" or event == "MODIFY":
        method = "RSYNC"
    # MOVE handling
    elif event == "MOVED_FROM" or event == "MOVED_TO":
        return
    elif event == "MOVE":
        method = "MOVE"
    # DELETE and undefined method
    elif event == "DELETE":
        method = "DELETE"
    else:
        log(utils.DEBUG2, "Skipping uninteresting event for "+filename)
        return
    # If event if for tempfile, ignore it
    if re.search(options.tempfiles, dstfile, re.I):
        log(utils.DEBUG2, "Skipping event for tempfile "+dstfile)
        return
    else:
        # If source was a tempfile but destination is a normal file, use RSYNC
        if re.search(options.tempfiles, filename, re.I):
            method = "RSYNC"
            filename = dstfile
            log(utils.DEBUG2, "Changing method from MOVE to RSYNC " +
                "for tempfile " + filename)
    # If event is from/to excluded files, ignore it
    if (re.search(options.excludes, filename.rstrip("/"), re.I) or
            re.search(options.excludes, dstfile.rstrip("/"), re.I)):
        log(utils.DEBUG2, "Skipping event for excluded path "+filename)
        return
    # Be EXTRA CAREFUL to skip the safesuffix
    if (re.search(config.safesuffix, filename.rstrip("/"), re.I) or
            re.search(config.safesuffix, dstfile.rstrip("/"), re.I)):
        log(utils.DEBUG2, "Skipping event for excluded path "+filename)
        return
    # If it was a translated line, only allow RSYNC method
    if translated and not method == "RSYNC":
        log(utils.DEBUG2, "Skipping non-rsync method for translated line")
        return
    # Construct action
    entry = {'method':method, 'itemtype':itemtype, 'dir':dirname,
             'file':filename, 'dstfile':dstfile, 'timestamp':time.time()}
    # Rsync checks
    if method == "RSYNC":
        if not rsync_early_checks(entry):
            return
    # Coalesce and append actions
    try:
        prev = actions.pop()
    except:
        prev = False
    if prev:
        if (method == "RSYNC" and prev['method'] == "DELETE" and
                filename == prev['file']):
            pass
        else:
            actions.append(prev)
    actions.append(entry)

def touch(filename):
    fd = open(filename, "w")
    fd.close()

def create_psyncdir():
    if not os.path.exists(options.psyncdir):
        os.makedirs(options.psyncdir)
        time.sleep(1)

# Parse options
(options, args) = parse_options()
heartfile = options.psyncdir+config.heartfile
# Prepare system
prepare_system()
# Launch pipe to inotify
inotify = launch_inotify()
# Read events as fast as possible
producer = threading.Thread(name="producer", target=read_inotify)
producer.daemon = True
producer.start()
# Analyze and coalesce changes
consumer = threading.Thread(name="consumer", target=dequeue)
consumer.daemon = True
consumer.start()

# Main thread
while True:
    parse = False
    # Check if inotify is terminated
    if inotify.poll():
        quit(1)
    # Check if psyncdir must be created
    create_psyncdir()
    # Try reading
    try:
        line = raw_queue.popleft()
        parse = True
    # If not ready, wait one second
    except:
        time.sleep(1)
    # If I have a line, parse it
    if parse:
        parse_line(line)
