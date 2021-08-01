#!/usr/bin/env python3

# pylint: disable=import-error,wrong-import-position,missing-class-docstring

import sys
import signal
from threading import Thread, Lock
from datetime import datetime
from calendar import monthrange
import random
import logging

from typing import Tuple

sys.path.append(".")
sys.path.append("..")
import test_timers


LEVEL = logging.INFO


class TestThread(Thread):
    """
    Thread that executes next_occurence tests.
    Every thread executes random tests independently and registers failed test cases with the main thread.
    The main thread collects and printes failed test cases every INTERVAL tests that it executes.
    """
    INTERVAL = 100

    def __init__(self, seed, main_thread=None):
        super().__init__()
        self.is_main = not bool(main_thread)
        self.main_thread = self if self.is_main else main_thread
        self.random = random.Random(seed)
        self.logger = logging.getLogger(__name__)

        # main thread things
        self.failed_test_buffer = [] if self.is_main else None
        self.lock = Lock() if self.is_main else None

        self._killed = False
        self.test_counter = 0
        self.failed_test_counter = 0

    def kill(self):
        self._killed = True
        return self.test_counter + 1, self.failed_test_counter

    def main_thread_obligations(self):
        """
        Collects failed test messages and prints them
        """
        with self.lock:
            for el in self.failed_test_buffer:
                print(el)
            self.failed_test_buffer = []

    def generate_random_date(self) -> datetime:
        """
        Generates a random datetime date based on the thread's seeded random.

        :return: random datetime
        """
        year = self.random.randint(1980, 2050)
        month = self.random.randint(1, 12)
        r = datetime(
            year=year,
            month=month,
            day=self.random.randint(1, monthrange(year, month)[1]),
            hour=self.random.randint(0, 23),
            minute=self.random.randint(0, 59)
        )
        return r

    def generate_testcase(self) -> Tuple[datetime, dict, datetime]:
        """
        Generates a random set of `now, td, expected` which serves as a test case.

        :return: now, td, expected as to be used by test_timers.tcase_cron_alg()
        """
        now = self.generate_random_date()
        tc = self.generate_random_date()
        td = {
            "year": tc.year,
            "month": tc.month,
            "monthday": tc.day,
            "hour": tc.hour,
            "minute": tc.minute,
        }
        expected = None if tc < now else tc
        return now, td, expected

    def append_failed_test(self, msg: str):
        """
        Appends a failed test message to the main thread's buffer.

        :param msg: Message to be appended
        """
        with self.main_thread.lock:
            self.main_thread.failed_test_buffer.append(msg)

    def run(self):
        i = 0
        while True:
            if i == self.INTERVAL - 1:
                i = 0
                if self.is_main:
                    self.main_thread_obligations()

            # Execute test
            now, td, expected = self.generate_testcase()
            try:
                test_timers.tcase_cron_alg(now, td, expected)
            except AssertionError as e:
                self.failed_test_counter += 1
                self.append_failed_test(str(e))
            self.test_counter += 1

            if self._killed:
                return
            i += 1


def get_seed():
    """
    Generates a seed for a testing thread.
    """
    return random.SystemRandom().random()


class Main:
    def __init__(self):
        signal.signal(signal.SIGINT, self.signal_handler)
        self.threads = []
        logging.basicConfig(level=LEVEL)

    def signal_handler(self, *_):
        """
        Signal handler callback for SIGINT
        """
        print()
        for i in range(len(self.threads)):
            tc, ftc = self.threads[i].kill()
            print("Thread {}: Executed {} tests; {} tests failed".format(i, tc, ftc))

        print("Done.")

    def main(self):
        """
        Main method; parses args and does testing thread setup
        """
        # Parse args
        threadcount = 1
        found_q = False
        for arg in sys.argv[1:]:
            if arg.startswith("-q"):
                if found_q:
                    print("Duplicate arg: -q")
                    return

                found_q = True
                threadcount = int(arg[2:])

            if arg in ("help", "--help", "-h"):
                print("Usage: {} [-qX] [help]\n  -qX: Amount of threads\n  help: Prints this help".format(sys.argv[0]))
                return

        # Thread setup
        main_thread = None
        for i in range(threadcount):
            t = TestThread(get_seed(), main_thread=main_thread)
            if main_thread is None:
                main_thread = t
            self.threads.append(t)
            t.start()
            print("Started thread {}".format(i))


if __name__ == "__main__":
    Main().main()
