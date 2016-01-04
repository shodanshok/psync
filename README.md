# Psync
Psync is a realtime, two-way syncronization utility written in Python

## Summary
[Usage](https://github.com/shodanshok/psync#usage)  
[How it works]  
[Command line options summary]  
[Command line options explained]  
[Config file notes]  
[FAQ]

## How it works
The basic idea is that, using inotify, one should be able to synchronize in (more or less) realtime two directory subtree, being on the same server or two different ones. This idea is not a new concept after all - utilities as lsyncd already accomplished this task.

What make Psync different is that it is a *two-way* synchronization tool, so that you can create/edit/rename files and directories on *both* replica sides, with Psync keeping the two sets aligned. Moreover, being a (quasi) realtime synchronization, it avoid the unpleasant manage of the conflicting/deleted file repository/history (DSFR users anyone?)

## Usage
`psync.py -r remotehost \<srcroot\> \<dstroot\>`  
*Example:* `psync -r slave.assyoma.it /opt/fileserver /opt/fileserver`  
*Note:* psync should be installed on both sides (left and right)

## Command line options quick summary
**-h, --help** show this help message and exit  
**-r DSTHOST, --remote-host=DSTHOST** Remote host (mandatory!)  
**-d DEBUGLEVEL, --debug=DEBUGLEVEL** enable debugger (levels: 1, 2 and 3)  
**-t TEMPFILES, --tempfiles=TEMPFILES** Tempfile list (regex)  
**-e EXCLUDES, --excludes=EXCLUDES** Excluded files (regex)  
**--rsync-excludes=RSYNC_EXCLUDES** Rsync exclusion list  
**-x RSYNC_EXTRA, --extra=RSYNC_EXTRA** Extra rsync options  
**-b BANNED, --banned=BANNED** Exit immediately if BANNED program is running  
**-T TRANSLATE, --translate=TRANSLATE** Translate/replace path element  
**-n, --dry-run** Simulate sync and log, but do nothing  
**-s, --sync-only** First sync only, then exit  
**-k, --skip-initial-sync** Skip initial sync  
**-f, --force** Force delete/move commands  

## Command line options explained
**-r DSTHOST, --remote-host=DSTHOST**  
This options define the remote host to which psync should connect. You can use both an hostname and an IP address.

**-d DEBUGLEVEL, --debug=DEBUGLEVEL**
Enable various level of increasing verbosity/debug. For normal operation, you need at most level 1. For event-tracking, you need level 2. For extended (and very verbose debug), use level 3

**-t TEMPFILES, --tempfiles=TEMPFILES**
Files identified as tempfiles (ie: temporary files) are *not* synchronized. As many programs (include office suites) make extended use of temporary files each time you save/edit a file, excluding them is important both for performance and correctness (see also the "TEMPFILES vs EXCLUDES" paragraph for more information)

**-e EXCLUDES, --excludes=EXCLUDES**
Files to exclude/ignore from replication. A special "*.psync.ignore*" extension is **always** excluded, as it is used to identify non-replicating events (see also the "TEMPFILES vs EXCLUDES" paragraph for more information)

**--rsync-excludes=RSYNC_EXCLUDES**
Files to exclude/ignore from full-merge RSYNC operation (see the "HOW PSYNC WORKS" paragraph for more information)

**-x RSYNC_EXTRA, --extra=RSYNC_EXTRA**
Extra RSYNC options to pass (eg: "-L")

**-b BANNED, --banned=BANNED**
Sometime, you want the replication to exit immediately if a particular program is running. This option enable you to specify a banned program, that will leat PSYNC to exit immediately

**-T TRANSLATE, --translate=TRANSLATE**
This is a very crude prototype for path translation. Usefull only in *very* particular cases. Don't use it unless you *really* know that are you doing.

**-n, --dry-run**
This does not need any explanation, right?

**-s, --sync-only**
This option trigger an one-shot full synchronization, then exits

**-k, --skip-initial-sync**
This option skips launch-time full synchronization. Usefull when you know that your sides are already synchronized

**-f, --force**
Normally, PSYNC will refuse to delete non-empty directory, or move a directory when it's target is another non-empty directory. This option will *force* PSYNC to complete the above operation on non-empty directory. Please note that in normal usage scenario you don't need to force anything, so use this option only if you know what are you doing.
