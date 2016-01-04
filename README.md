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
The basic idea is that, using inotify, one should be able to synchronize in (more or less) realtime two directory subtree (called *left* and *right* in this document), being on the same server or two different ones. This idea is not a new concept after all - utilities as lsyncd already accomplished this task.

What make Psync different is that it is a *two-way* synchronization tool, so that you can create/edit/rename files and directories on *both* replica sides, with Psync keeping the two sets aligned. Moreover, being a (quasi) realtime synchronization, it avoid the unpleasant managing of the conflicting/deleted file repository/history (DSFR users anyone?)

A significant problem in concurrent, two-way replication is to identify which events must be propagated and which one should be discarded. Let assume a naive propagate-all-events approach: after a left-generated event is replicated on the right side, *an identical event will be immediately propagated from right to left.* The reason is quite simple: the right instance has no means to differentiate between left-induced events and locally (genuine) generated ones. Obviously, events should not be fired back to their source. This can not only results in an event loop (event is propagated left->right, then right->left, and so on) but it is a data-loss prone scenario.  

This can be fixed only with a "central brain" which coordinate events and filter them. This is one of the key reason why I had to write Psync. For more information about that topic, give a look at the FAQ entries.

**HOW EVENTS ARE COLLECTED AND PROPAGATED**  
As stated above, events are collected using [inotify](http://linux.die.net/man/7/inotify). After being collected, events are queued and issued to the replication partner. The partner apply them in a manner that avoid re-catching (and re-propagating) events back to source; this is accomplished by ad-hoc rules excluding certain "protected" filename/suffixes (eg: "psync.ignore") that Psync know to ignore, avoiding sending back the event to its source.

Sending data is accomplished via [rsync](https://rsync.samba.org/), which need to be installed on both partners. Moves and deletion are accomplished via a custom helper script. In particular, moves are executed without needing to re-transfer any data (most of the times).

Below you can find some event propagation examples. **L** and **R** means left and right, respectively.

*CREATE and CLOSE_WRITE*  
L: CREATE test.txt  
L: CLOSE_WRITE test.txt  
*... wait some seconds ...*
R: CREATE .test.txt.ABCDEF (temporary rsynch file; this event will be skipped)  
R: CLOSE_WRITE .test.txt.ABCDEF (temporary rsynch file; this event will be skipped)  
R: MOVE .test.txt.ABCDEF test.txt (as the source filename is excluded, this event will be skipped)  
*Result:* the file is pushed to the remote partner without any backired event  

*DELETE*  
L: DELETE test.txt  
*... wait some seconds ...*  
L: if file test.txt is not found (ie: it was really deleted), propagate the event  
R: MOVE test.txt test.txt.1234.psync.ignore (temporary scratch file, this event will be skipped)  
R: DELETE test.txt.1234.psync.ignore (temporary scratch file, this event will be skipped)  
*Result:* the file deleted from remote partner without any backired event  

*MOVE*  
L: MOVE test.txt new.txt  
*... wait some seconds ...*  
L: MOVE test.txt test.txt.9876.psync.ignore (temporary scratch file, this event will be skipped)  
L: MOVE test.txt.9876.psync.ignore new.txt (as the source filename is excluded, this event will be skipped)  
*Result:* the file is moved/renamed on remote partner without any backired event  


In order 

## Usage
`psync.py -r remotehost \<srcroot\> \<dstroot\>`  
*Example:* `psync -r slave.assyoma.it /opt/fileserver /opt/fileserver`  
*Note:* psync should be installed on both sides (left and right)

## Command line options quick summary
**`-h, --help`** show this help message and exit  
**`-r DSTHOST, --remote-host=DSTHOST`** Remote host (mandatory!)  
**`-d DEBUGLEVEL, --debug=DEBUGLEVEL`** enable debugger (levels: 1, 2 and 3)  
**`-t TEMPFILES, --tempfiles=TEMPFILES`** Tempfile list (regex)  
**`-e EXCLUDES, --excludes=EXCLUDES`** Excluded files (regex)  
**`--rsync-excludes=RSYNC_EXCLUDES`** Rsync exclusion list  
**`-x RSYNC_EXTRA, --extra=RSYNC_EXTRA`** Extra rsync options  
**`-b BANNED, --banned=BANNED`** Exit immediately if BANNED program is running  
**`-T TRANSLATE, --translate=TRANSLATE`** Translate/replace path element  
**`-n, --dry-run`** Simulate sync and log, but do nothing  
**`-s, --sync-only`** First sync only, then exit  
**`-k, --skip-initial-sync`** Skip initial sync  
**`-f, --force`** Force delete/move commands  

## Command line options explained
**`-r DSTHOST, --remote-host=DSTHOST`**  
This options define the remote host to which psync should connect. You can use both an hostname and an IP address.

**`-d DEBUGLEVEL, --debug=DEBUGLEVEL`**  
Enable various level of increasing verbosity/debug. For normal operation, you need at most level 1. For event-tracking, you need level 2. For extended (and very verbose debug), use level 3

**`-t TEMPFILES, --tempfiles=TEMPFILES`**  
Files identified as tempfiles (ie: temporary files) are *not* synchronized. As many programs (include office suites) make extended use of temporary files each time you save/edit a file, excluding them is important both for performance and correctness (see also the "TEMPFILES vs EXCLUDES" paragraph for more information)

**`-e EXCLUDES, --excludes=EXCLUDES`**  
Files to exclude/ignore from replication. A special "*.psync.ignore*" extension is **always** excluded, as it is used to identify non-replicating events (see also the "TEMPFILES vs EXCLUDES" paragraph for more information)

**`--rsync-excludes=RSYNC_EXCLUDES`**  
Files to exclude/ignore from full-merge RSYNC operation (see the "HOW PSYNC WORKS" paragraph for more information)

**`-x RSYNC_EXTRA, --extra=RSYNC_EXTRA`**  
Extra RSYNC options to pass (eg: "-L")

**`-b BANNED, --banned=BANNED`**  
Sometime, you want the replication to exit immediately if a particular program is running. This option enable you to specify a banned program, that will leat PSYNC to exit immediately

**`-T TRANSLATE, --translate=TRANSLATE`**  
This is a very crude prototype for path translation. Usefull only in *very* particular cases. Don't use it unless you *really* know that are you doing.

**`-n, --dry-run`**  
This does not need any explanation, right?

**`-s, --sync-only`**  
This option trigger an one-shot full synchronization, then exits

**`-k, --skip-initial-sync`**  
This option skips launch-time full synchronization. Usefull when you know that your sides are already synchronized

**`-f, --force`**  
Normally, PSYNC will refuse to delete non-empty directory, or move a directory when it's target is another non-empty directory. This option will *force* PSYNC to complete the above operation on non-empty directory. Please note that in normal usage scenario you don't need to force anything, so use this option only if you know what are you doing.
