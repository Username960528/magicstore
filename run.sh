#!/bin/bash

if [ -z "$1" ]; then
    echo "Usage: $(basename $0) <profile id>"
    exit 1
fi

time=$(date +%s)
sid=$1
[ -z "$delay" ] && delay=$(((RANDOM % 320) + 10 ))

. venv/bin/activate
echo "Profile #${sid} in ${delay}sec"
sleep $delay
python ./magicstore_automation.py $sid 2>&1 | tee logs/$sid-$time.txt
