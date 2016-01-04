#!/usr/bin/python2

import optparse
import os.path
import hashlib
import random
import time
import sys
import os

# Custom imports
sys.dont_write_bytecode = True
import utils
import config

### EXIT CODES ###
utils.PSUCCESS = 0
utils.PERROR = 1
##################


def parse_options():
    parser = optparse.OptionParser()
    parser.add_option("-d", "--debug", dest="debug", type="int",
                      help="Enable debugger", action="store",
                      default=config.debug)
    parser.add_option("-a", "--action", dest="action", action="store",
                      help="Action to perform", default=None)
    parser.add_option("-i", "--actionid", dest="actionid",
                      action="store", help="Action ID",
                      default=".{0:04}".format(random.randint(0, 999)))
    parser.add_option("-f", "--force", dest="force", action="count",
                      help="Force delete/move commands",
                      default=config.force)
    parser.add_option("-c", "--checksum", dest="checksum", action="store",
                      help="Action checksum", default=None)
    (options, args) = parser.parse_args()
    return (options, args)

def delete_file(filename):
    safename = filename+options.actionid+config.safesuffix
    try:
        os.rename(filename, safename)
        os.unlink(safename)
        print "Deleted file "+filename
        return True
    except:
        sys.stderr.write("Can not remove file "+filename+"\n")
        return False

def delete_dir(dirname):
    # If it a symlimk to dir, treat it as a file
    if os.path.islink(dirname):
        return delete_file(dirname)
    # If it is a real dir, go ahead
    dirname = dirname.rstrip("/")
    safename = dirname+options.actionid+config.safesuffix
    try:
        os.rename(dirname, safename)
        os.rmdir(safename)
        print "Deleted dir "+dirname
        return True
    except:
        sys.stderr.write("Can not remove dir "+dirname+"\n")
        return False

def delete(args, force=0):
    if type(args) is not list:
        args = [args]
    if not force:
        force = options.force
    exitcode = utils.PSUCCESS
    for arg in args:
        # Delete files and symlinks
        if os.path.isfile(arg) or os.path.islink(arg):
            if not delete_file(arg):
                exitcode = utils.PERROR
        # Delete directories
        elif os.path.isdir(arg):
            arg = arg.rstrip("/")
            if not force:
                # Check if empty
                dirlist = os.listdir(arg)
                if dirlist:
                    sys.stderr.write("Can not remove non-empty dir "+
                                     arg+"\n")
                    exitcode = utils.PERROR
                    continue
            # Go ahead with delete
            for base, dirs, files in os.walk(arg, topdown=False):
                for entry in files:
                    if not delete_file(base+"/"+entry):
                        exitcode = utils.PERROR
                for entry in dirs:
                    if not delete_dir(base+"/"+entry):
                        exitcode = utils.PERROR
            if not delete_dir(arg):
                exitcode = utils.PERROR
        else:
            # Path does not exists
            if not force:
                sys.stderr.write("Can not delete not-existant path "+
                                 arg+"\n")
    # Finally, return
    return exitcode

def move(args):
    exitcode = utils.PSUCCESS
    srcname = args[0].rstrip("/")
    dstname = args[1].rstrip("/")
    dstparent = os.path.dirname(dstname)
    if srcname == dstname:
        sys.stderr.write("Can not move same src and dst path "+srcname+"\n")
        exitcode = utils.PERROR
        return exitcode
    # If source does not exists, exit now
    if not os.path.exists(srcname):
        sys.stderr.write("Can not move not-existant entry "+srcname+"\n")
        exitcode = utils.PERROR
        return exitcode
    # Check if both source and destination exist and are directories
    if os.path.isdir(srcname) and os.path.isdir(dstname):
        # Be sure that destination dir is not a parent of source dir
        if not utils.is_parent_of(dstname, srcname):
            # If force is not set, continue only if source dir has
            # same name as destination dir OR if destination dir is empty OR
            # source and destination dirs are under the same parent AND
            # destination dir was very new
            if (
                    options.force or not os.listdir(dstname) or
                    os.path.basename(srcname) == os.path.basename(dstname) or
                    (os.path.dirname(srcname) == os.path.dirname(dstname) and
                     time.time() - os.stat(dstname).st_ctime < 60)
                ):
                print ("Destination dir already exists." +
                       " Removing it to follow the move")
                # Remove the (overlapping) destinatin dir
                if delete(dstname, force=1):
                    exitcode = utils.PERROR
            else:
                print "Destination dir already exists. Aborting"
                exitcode = utils.PERROR
        else:
            sys.stderr.write("Can not remove parent dir "+dstname+"\n")
            exitcode = utils.PERROR
    # Check if destination parent dir exists and if not, create it
    elif not os.path.isdir(dstparent):
        try:
            os.makedirs(dstparent)
            print "Created destination parent dir "+dstparent
        except:
            sys.stderr.write("Can not create parent dir "+dstparent)
            exitcode = utils.PERROR
    # If an error happened, flush stdout and exit with error
    if exitcode:
        return exitcode
    # Rename
    try:
        safename = srcname+options.actionid+config.safesuffix
        os.rename(srcname, safename)
        os.rename(safename, dstname)
        print "Moved " + srcname + " -> " + dstname
    except:
        sys.stderr.write("Can not move "+srcname+ " -> "+dstname+"\n")
        exitcode = utils.PERROR
    return exitcode

def verify_checksum():
    computed = options.action
    for arg in args:
        computed = utils.concat(computed, arg)
    computed = hashlib.md5(computed).hexdigest()
    if options.checksum == computed:
        if options.debug > 1:
            print ("Valid helper action checksum. Received: " +
                   options.checksum + " Computed: " + computed)
        return True
    elif options.checksum == "SKIP":
        return True
    else:
        sys.stderr.write("Invalid action checksum! " +
                         "Received: "+str(options.checksum) + " - " +
                         "Expected: "+computed + "\n")
        return False


# Option parsing
(options, args) = parse_options()

# Verify checksum
if not verify_checksum():
    exitcode = utils.PERROR
else:
    # Select action
    if options.action == "DELETE":
        exitcode = delete(args)
    elif options.action == "MOVE":
        exitcode = move(args)

# Flush stdout and exit
sys.stdout.flush()
quit(exitcode)
