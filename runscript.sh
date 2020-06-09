#!/bin/bash

PYTHON=python3
UPDATECODE=10

exitcode=-1

while [[ ${exitcode} -ne 0 ]]; do
    ${PYTHON} Geckarbot.py ${exitcode}
    exitcode=$?

    if [[ ${exitcode} -eq ${UPDATECODE} ]]; then
        git pull origin master
    fi

    if [[ ${exitcode} -ne 0 ]]; then
        echo "Unexpected Bot exit code: ${exitcode}"
    fi
done
