#!/bin/bash

PYTHON=python3

exitcode=-1

while [ $exitcode -ne 0 ]; do
    $PYTHON Geckarbot.py $exitcode
    exitcode=$?

    if [ $exitcode -eq 10 ]; then
        git pull origin master
    fi
