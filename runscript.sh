#!/bin/bash

PYTHON=python3
TAGFILE=".update"
UPDATECODE=10
RESTARTCODE=11
SIMULATE=1  # 0 for true

exitcode=-1

while [[ ${exitcode} -ne 0 ]]; do
    ${PYTHON} -m pip install -r requirements.txt
    ${PYTHON} Geckarbot.py ${exitcode}
    exitcode=$?

    # update
    if [[ ${exitcode} -eq ${UPDATECODE} ]]; then
        if [[ ${SIMULATE} -ne 0 ]]; then
            git fetch origin release --tags
            git checkout tags/$(cat ${TAGFILE})
        else
            echo "Simulating update to $(cat ${TAGFILE})"
        fi
        continue
    fi

    # restart
    if [[ ${exitcode} -eq ${RESTARTCODE} ]]; then
      continue
    fi

    # anything else
    if [[ ${exitcode} -ne 0 ]]; then
        echo "Unexpected Bot exit code: ${exitcode}"
    fi
done
