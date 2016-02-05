# psync
psync is a realtime, two-way syncronization utility written in Python

## Summary
[How it works](https://github.com/shodanshok/psync#how-it-works)  
[Repository content and file structure](https://github.com/shodanshok/psync#repository-content-and-file-structure)  
[Usage](https://github.com/shodanshok/psync#usage)  
[Command line options summary](https://github.com/shodanshok/psync#command-line-options-quick-summary)  
[Command line options explained](https://github.com/shodanshok/psync#command-line-options-explained)  
[Config file notes]  
[FAQ]  

## How it works
The basic idea is that, using inotify, one should be able to synchronize in (more or less) realtime two directory subtree (called *left* and *right* in this document), being on the same server or two different ones. This idea is not a new concept after all - utilities as lsyncd already accomplished this task.

What make psync different is that it is a *two-way* synchronization tool, so that you can create/edit/rename files and directories on *both* replica sides, with psync keeping the two sets aligned. Moreover, being a (quasi) realtime synchronization, it avoid the unpleasant managing of the conflicting/deleted file repository/history (DSFR users anyone?)

A significant problem in concurrent, two-way replication is to identify which events must be propagated and which one should be discarded. Let assume a naive propagate-all-events approach: after a left-generated event is replicated on the right side, *an identical event will be immediately propagated from right to left.* The reason is quite simple: the right instance has no means to differentiate between left-induced events and locally (genuine) generated ones. Obviously, events should not be fired back to their source. This can not only results in an event loop (event is propagated left->right, then right->left, and so on) but it is a data-loss prone scenario.  

This can be fixed only with a "central brain" which coordinate events and filter them. This is one of the key reason why I had to write psync. For more information about that topic, give a look at the FAQ entries.

**HOW EVENTS ARE COLLECTED AND PROPAGATED**  
As stated above, events are collected using [inotify](http://linux.die.net/man/7/inotify). After being collected, events are queued and issued to the replication partner. The partner apply them in a manner that avoid re-catching (and re-propagating) events back to source; this is accomplished by ad-hoc rules excluding certain "protected" filename/suffixes (eg: "psync.ignore") that psync know to ignore, avoiding sending back the event to its source.

Sending data is accomplished via [rsync](https://rsync.samba.org/), which need to be installed on both partners. Moves and deletion are accomplished via a custom helper script. In particular, moves are executed without needing to re-transfer any data (most of the times). Both rsync and helper-based events need SSH automatic (non-interactive) access, so it is mandatory to use public/private keys to automate the login phase.

Below you can find some event propagation examples. **L** and **R** means left and right, respectively.

*CLOSE_WRITE*  
L: CREATE test.txt (this event will be skipped) 
L: CLOSE_WRITE test.txt  
*... wait some seconds ...*
R: CREATE .test.txt.ABCDEF (temporary rsync file; this event will be skipped)  
R: CLOSE_WRITE .test.txt.ABCDEF (temporary rsync file; this event will be skipped)  
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

## Repository content and file structure
In order to perform well in low-bandwidth, high latency link, psync is composed of a centralized, left-only "brain" called `psync.py` and decentralized `filter.py`, `helpers.py` and `cinotify` files. In addition, I wrote some (rather crude) shell wrapper to start/stop it and to check replication correctness. These wrapper are nor elegant nor polished, by they accomplish their work. You are welcome to contribute with better "glue code" (and to enhance/rewrite/refactor the core code also!).  

Some more in-depth information:

**`psync.py`** is psync's central brain. It decides if/when/how to propagate an event, and it manage various heartbeats to be sure all is working properly.  
**`filter.py`** is a decentralized python script in charge of collecting events. It accomplish its task opening a pipe to the next component...  
**`cinotify/cinotify`** is a (binary) inotify reader. It listen on a inotify file descriptor and prints events on standard output. Why I need a separate, C-based inotify reader rather than implementing it in `filter.py`? The simple answer is speed: all current python-based inotify implementation are *very* slow, so slow that you can not monitor any subtree remotely large. The astute reader will ask why I don't used the already-ready [inotifywait](https://github.com/rvoicilas/inotify-tools/wiki) tool. In fact, I *used* it in previous psync version, but I discovered [one very serious bug in how it handle directory renames](https://github.com/rvoicilas/inotify-tools/issues/59). As I don't think to 100% understand inotifywait code, and the project seems dead, I wrote a custom C-based inotify reader and, without much imagination, I called it `cinotify`. In its directory, you will find an x86-64 compiled version (called, again, `cinotify`) and its source code (`cinotify.c`)  
**`libs/helpers.py`** is a small collection of helpers functions. Helpers are the small programs needed to manage the rename-dance necessary to avoid events to be backfired. Feel free to issue `libs/helpers.py --help` to have more information.  
**`libs/utils.py`** contain various shared utility functions  
**`libs/config.py`** is psync's configuration file (more on that later)  
**`conf/`** this directory contains various configuration files for other subsystem (eg: bash, logrotate, cron, ecc). It also symlink `libs/config.py`  
**`start, stop, check and runcheck`** are some (crude) shell wrapper used to start/stop/check psync operations


## Usage
`psync.py -r remotehost \<srcroot\> \<dstroot\>`  
*Example:* `psync -r slave.assyoma.it /opt/fileserver /opt/fileserver`  
*Note:* psync (and I means *all* the psync tree, not only the psync.py file) should be installed on both sides (left and right)  
*Note:* as psync will use SSH to propagate events, you *need* to setup pubkey based automatic login
By default, logs will be written inside `/var/log/psync/psync.log` file.

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
Files to exclude/ignore from full-merge RSYNC operation (see the "HOW psync WORKS" paragraph for more information)

**`-x RSYNC_EXTRA, --extra=RSYNC_EXTRA`**  
Extra RSYNC options to pass (eg: "-L")

**`-b BANNED, --banned=BANNED`**  
Sometime, you want the replication to exit immediately if a particular program is running. This option enable you to specify a banned program, that will leat psync to exit immediately

**`-T TRANSLATE, --translate=TRANSLATE`**  
This is a very crude prototype for path translation. Usefull only in *very* particular cases. Don't use it unless you *really* know that are you doing.

**`-n, --dry-run`**  
This does not need any explanation, right?

**`-s, --sync-only`**  
This option trigger an one-shot full synchronization, then exits

**`-k, --skip-initial-sync`**  
This option skips launch-time full synchronization. Usefull when you know that your sides are already synchronized

**`-f, --force`**  
Normally, psync will refuse to delete non-empty directory, or move a directory when it's target is another non-empty directory. This option will *force* psync to complete the above operation on non-empty directory. Please note that in normal usage scenario you don't need to force anything, so use this option only if you know what are you doing.

## Config file notes
psync config files define various default parameters and give access to some internal configuration values. It is nothing more than a python file which is included in all the other python scripts. The main configuration parameters are:

**`safesuffix=`** this is the default safesuffix (ie: ignored filename) used for the rename-dance by the `helpers.py` script  
**`debug=`** the default debug level [0, 1, 2, 3]  
**`event_interval=`** define the time (in seconds) between event collection and aknowledge by `filter.py`. After the specified time, events are forwarded to `psync.py` which will propagate them [number]  
**`force=`** default force setting [0, 1]  
**`dryrun=`** only simulate event propagation [True, False]  
**`first_sync_only=`** synchronize the two replica set and then exit [True, False]  
**`skip_initial_sync=`** skip initial synchronization [True, False]  
**`banned=`** banned program name [string]  
**`translate=`** default translate string (does not use it unless you **really** know what are you doing) [string]  
**`rsync_excludes=`** rsync file exclusion [list]  
**`rsync_extra=`** rsync extra options [list]  
**`inotify_extra=`** cinotify extra options [list]  
**`tempfiles=`** identifies temporary files [regex]  
**`excludes=`** to-be-ignored files [regex]  
**`separator=`** `cinotify` use this separator as field-delimiter. It should be a character (or string) which will not be used in legal file names (as default, I used the ':' character as it is not allowed on Windows nor on SMB/CIFS shares) [string]  
**`fullsync=`** is an array containing the time of the day (expressed in hours) when a full, complete replication (with new files and ACLs propagated) will be executed. If you want no such replication, leave it empty or set an unrealistic value (eg: 99) [array]  
**`pending_lifetime=`** maximum time, in seconds, meanwhile an identical received events will be treated as a backfired event (ie: ignored) [number]  
**`pending_events=`** events to be tracked for backfiring [string]  
**`ssh_options=`** default SSH options [string]  
**`rsync_event_recurse=`** if set, rsync will use recursive scan by default (use only if you really know what are you doing)  
**`alert_threshold=`** threshould over which the scheduled checks done via `rcheck.py` will signal an alarm  
**`rsync_style=`** how to treat synchronization (ie: CLOSE_WRITE) events. If set to 1, backfired sync events will be re-issued to the replication partner with "safe" rsync settings (ie: --existing). If set to 2, backfired sync event will be ignored for the duration of `pending_lifetime`. If set to 3, all rsync events will be batched for later execution [1, 2, 3]  
**`acl_from_left_only=`** is set to True, ACLs will be set only from left to right. If set to False, ACLs can be set from right to left also (but be sure to read the ACCESS LIST paragraph first).  
**`timeout=`** general timeout (in seconds), used as a base for other timeouts [number]  
**`itimeout=`** initial cinotify timeout, in seconds [number]  
**`etimeout=`** execute (for event propagation) timeout (in seconds) [number]  
**`maxtimeout=`** max connection timeout (in seconds). After this timer expires, psync will die and exit  
