#!/usr/bin/python2

import subprocess
import threading
import inspect
import time
import sys

# Custom imports
sys.dont_write_bytecode = True
import config

#### SEVERITY DEFINES #####
FATAL = 4
CRITICAL = 3
ERROR = 2
WARNING = 1
INFO = 0
DEBUG1 = -1
DEBUG2 = -2
DEBUG3 = -3
##################

### EXIT CODES ###
PSUCCESS = 0
PERROR = 1
PSOFTERROR = 100
RSYNC_SUCCESS = [0, 23, 24]
##################

def inv(number):
    return number*-1

def log(severity, source, message, debug=config.debug,
        caller=False, thread=False, raw=0, eventid=None):
    debug = inv(debug)
    if severity < debug:
        return
    if len(message) == 0:
        return
    # If string, convert to int
    if type(severity) is str:
        try:
            severity = int(severity)
        except:
            severity = WARNING
    # Severity names
    if severity < INFO:
        sevname = "DEB"
    elif severity == INFO:
        sevname = "INF"
    elif severity == WARNING:
        sevname = "WAR"
    elif severity == ERROR:
        sevname = "ERR"
    elif severity == CRITICAL:
        sevname = "CRI"
    elif severity == FATAL:
        sevname = "FAT"
    else:
        sevname = "UND"
    # Get caller, thread and eventid
    if not caller:
        caller = inspect.stack()[1][3]
    if not thread:
        thread = threading.current_thread()
    if not eventid:
        eventid = "undef"
    # Print
    message = deconcat(message)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    eventid = eventid+"      "
    eventid = eventid[:5]
    caller = caller+"        "
    caller = caller[:9]
    ident = str(thread.ident)
    ident = ident+"                "
    ident = ident[:16]
    thread = thread.name
    thread = thread+"        "
    thread = thread[:9]
    for line in message:
        # Generate log line
        if raw > 0:
            logline = ("["+timestamp+"] ["+sevname+":"+
                       "{0:+d}".format(severity)+"] ["+source+"] "+ line)
        elif debug > DEBUG3:
            logline = ("["+timestamp+"] ["+sevname+":"+
                       "{0:+d}".format(severity)+"] ["+source+"] ["+
                       eventid+"] ["+caller+"] " + line)
        else:
            logline = ("["+timestamp+"] ["+sevname+":"+
                       "{0:+d}".format(severity)+"] ["+source+"] ["+
                       eventid+"] ["+caller+"] ["+thread+"] ["+ident+"] " +
                       line)
        # Select stdout or stderr
        if severity > INFO:
            sys.stderr.write(logline+"\n")
        else:
            print logline
            sys.stdout.flush()

def execute(cmd, source, stdin, warn=True, timeout=False, heartbeats=False,
            dryrun=False, debug=config.debug, eventid=None):
    # It is rsync?
    if cmd[0].find("rsync") >= 0:
        commandtype = "rsync"
    else:
        commandtype = "other"
    # Dry run?
    if dryrun:
        prefix = "*** DRY RUN ***"
        if commandtype != "rsync":
            cmd = "true"
    else:
        prefix = ""
    # Executing
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, stdin=subprocess.PIPE)
    # Log and register process
    log(DEBUG1,
        source, prefix+"COMMAND LINE for PID "+str(process.pid)+": "+str(cmd),
        debug=debug, eventid=eventid)
    entry = {'last':time.time(), 'timeout':timeout, 'process':process,
             'pid':process.pid}
    if heartbeats:
        heartbeats['execute'][process.pid] = entry
    (output, error) = process.communicate(stdin)
    # Unregister process
    if heartbeats:
        heartbeats['execute'].pop(process.pid, None)
    # Log and return
    if output:
        if debug:
            output = (prefix +
                      "COMMAND OUTPUT for PID "+str(process.pid)+": \n"+
                      output)
        log(INFO, source, output, debug=debug, eventid=eventid)
    log(DEBUG1, source,
        prefix+"FINISHED COMMAND with PID "+str(process.pid)+", EXIT CODE "+
        str(process.returncode), debug=debug, eventid=eventid)
    # Decide if we must print warnings
    if warn and error:
        if process.returncode:
            if (
                    commandtype == "rsync" and
                    process.returncode not in RSYNC_SUCCESS or
                    commandtype == "other" or inv(debug) <= DEBUG3
                ):
                log(WARNING, source, error, debug=debug, eventid=eventid)
        else:
            if commandtype == "other":
                log(INFO, source, error, debug=debug, eventid=eventid)
    return (process, output, error)

def gen_exclude(excludes):
    excludelist = []
    if type(excludes) is list:
        for exclude in excludes:
            excludelist.append("--exclude="+exclude)
    return excludelist

def normalize_dir(dirname):
    return dirname.rstrip("/")+"/"

def concat(original, addition, separator='\n'):
    newstring = original.rstrip(separator)
    if len(newstring) > 0:
        newstring = newstring + separator + addition
    else:
        newstring = addition
    return newstring.rstrip(separator)

def deconcat(original, separator='\n', strip=True):
    if strip:
        newstring = original.rstrip(separator)
    else:
        newstring = original
    return newstring.split(separator)

def is_parent_of(parent, child):
    return child.startswith(normalize_dir(parent))
