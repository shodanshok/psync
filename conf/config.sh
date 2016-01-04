#!/bin/bash

# PATH
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin:/root/bin
export PATH

# Variables
script=`basename $0`
basedir=`dirname $0`
logdir="/var/log/psync/"

# Init code
cd $basedir
mkdir -p "$logdir"

# Functions
function send_email {
    if [ $send_mail -eq 1 ]; then
        echo -e "$mailobj" | $mailcmd
    else
        echo -e "$mailobj"
    fi
}
