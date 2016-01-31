#!/usr/bin/python2

import os.path

# DO NOT TOUCH THESE LINES
# Sanitize config
def normalize_dir(dirname):
    return dirname.rstrip("/")+"/"
# Base dir
basedir = normalize_dir(os.path.dirname(os.path.dirname(__file__)))
# Bins
helperbin = basedir+"libs/helpers.py"
filterbin = basedir+"filter.py"
inotifybin = basedir+"cinotify/cinotify"

# START OF USER EDITABLE CONFIGURATION
# Safename suffix
safesuffix = ".psync.ignore"

# Command line defaults
debug = 0
event_interval = 5
force = 0
dryrun = False
first_sync_only = False
skip_initial_sync = True
banned = None
translate = None #translate = "____archive____/|None"
rsync_excludes = [".psync", "*.psync.ignore", "*.rsync-partial", ".*.??????",
                  "____archive____", "*.symlink", "*.tmp", "*.TMP", "*.~tmp~",
                  "Thumbs.db", "~$*"]
rsync_extra = ["-L", "--timeout=10", "--max-size=90M",
               "--partial-dir=.rsync-partial"]
inotify_extra = ["-E", "____archive____", "-q", "-s"]
tempfiles = "\.tmp$|\.~tmp~|/~\$"
excludes = (".psync.ignore|.rsync-partial|/\..*\.......$|/____archive____/" +
            "|\.symlink$|/Thumbs.db$")

# Internal configuration
psyncdir = normalize_dir(".psync")
heartfile = "heartbeat"
separator = ":"
pending_lifetime = 60
pending_events = ["RSYNC", "DELETE"]
ssh_options = ["-o", "ConnectTimeout=10", "-C"]
rsync_event_recurse = False
alert_threshold = 10
warning_threshold = 20
rsync_style = 2 # 1: continuous, 2: continuous w/o backfired, 3: batchched
acl_from_left_only = True

# Timeouts
timeout = 60                # General timeout
itimeout = timeout*5        # Initial inotify timeout
etimeout = timeout-15       # Execute timeout
maxtimeout = timeout*15     # Max connection timeout (abort)

# Schedules
fullsync = [01]
