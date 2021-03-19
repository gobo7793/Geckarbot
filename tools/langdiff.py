#!/usr/bin/env python3

"""
Lists all lang strings that are not present in every language that is present in the respective lang file.
"""

import json
import os

LANGDIR = "lang"


class Found:
    def __init__(self):
        self.found = {}
        """
        structure:
        {
            langcode: {
                langstring: [not_found_in_these_langcodes ...]
            }
        } 
        """

    def __len__(self):
        r = 0
        for langcode in self.found:
            for langstring in self.found[langcode]:
                r += len(self.found[langcode][langstring])
        return r

    def append(self, langcode, langstring, not_found_in):
        if langcode not in self.found:
            self.found[langcode] = {}

        if langstring not in self.found[langcode]:
            self.found[langcode][langstring] = []

        self.found[langcode][langstring].append(not_found_in)

    def to_messages(self, prefix=""):
        for langcode in self.found:
            yield "{}{}:".format(prefix, langcode)
            for langstring in self.found[langcode]:
                yield "  {}{} not found in {}".format(prefix, langstring, ", ".join(self.found[langcode][langstring]))


def diff(filename):
    with open("{}/{}".format(LANGDIR, filename)) as f:
        s = json.load(f)

    found = Found()

    for key in s:
        for diffto in s:
            if key == diffto:
                continue

            for langstring in s[key]:
                if langstring not in s[diffto]:
                    found.append(key, langstring, diffto)

    if not found:
        return

    print("{}:".format(filename))
    for msg in found.to_messages(prefix="  "):
        print(msg)
    print()


def main():
    errors = {}

    try:
        langdir = os.listdir(LANGDIR)
    except FileNotFoundError:
        print("Directory {} not found. Please execute from project root directory.".format(LANGDIR))
        return 1

    for filename in langdir:
        try:
            diff(filename)
        except Exception as e:
            errors[filename] = e

    if errors:
        print("Errors while handling files:")
        for key in errors:
            print("{}: {}".format(key, errors[key]))


if __name__ == "__main__":
    main()
