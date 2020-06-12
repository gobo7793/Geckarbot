#!/bin/bash

PYTHON=python3
TAGFILE=".update"
UPDATECODE=10
SIMULATE=0  # 0 for true

exitcode=-1

while [[ ${exitcode} -ne 0 ]]; do
    ${PYTHON} Geckarbot.py ${exitcode}
    exitcode=$?

    if [[ ${exitcode} -eq ${UPDATECODE} ]]; then
        if [[ ! SIMULATE ]]; then
            git fetch origin master
            git checkout tags/$(cat ${TAGFILE})
        else
            echo "Simulating update to $(cat ${TAGFILE})"
        fi
        continue
    fi

    if [[ ${exitcode} -ne 0 ]]; then
        echo "Unexpected Bot exit code: ${exitcode}"
    fi
done
