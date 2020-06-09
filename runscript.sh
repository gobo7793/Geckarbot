#!/bin/bash

PYTHON=python3
TAGFILE=".update"
UPDATECODE=10

exitcode=-1

while [[ ${exitcode} -ne 0 ]]; do
    ${PYTHON} Geckarbot.py ${exitcode}
    exitcode=$?

    if [[ ${exitcode} -eq ${UPDATECODE} ]]; then
        git fetch origin master
        git checkout tags/$(cat ${TAGFILE})
    fi

    if [[ ${exitcode} -ne 0 ]]; then
        echo "Unexpected Bot exit code: ${exitcode}"
    fi
done
