#!/usr/bin/env python3

###
# Lists all lang strings that are not present in every language that is present in the respective lang file.
###

import json
import os
import sys

LANGDIR = "lang"


class Found:
    """
    Represents all violations found in a lang file
    """
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
        for _, found in self.found.items():
            for _, el in found.items():
                r += len(el)
        return r

    def append(self, langcode: str, langstring: str, not_found_in: str):
        """
        Appends a violation

        :param langcode: language code
        :param langstring: lang key
        :param not_found_in: language code that this key is not found in
        """
        if langcode not in self.found:
            self.found[langcode] = {}

        if langstring not in self.found[langcode]:
            self.found[langcode][langstring] = []

        self.found[langcode][langstring].append(not_found_in)

    def to_messages(self, prefix: str = "") -> str:
        """
        Generator for messages

        :param prefix: indentation prefix
        :return: Iterator for messages that represent all found violations
        """
        for langcode, item in self.found.items():
            yield "{}{}:".format(prefix, langcode)
            for langstring, el in item.items():
                yield "  {}{} not found in {}".format(prefix, langstring, ", ".join(el))


def diff(filename: str) -> bool:
    """
    Does the diff for a specific file, also does the output

    :param filename: File name of the file to be diffed
    :return: `True` if violations were found, `False` otherwise
    """
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
        return False

    print("{}:".format(filename))
    for msg in found.to_messages(prefix="  "):
        print(msg)
    print()
    return True


def main() -> int:
    """
    main()

    :return: 1 in case of unhandled exceptions (I think). Otherwise works like a bitmask: +2 for I/O errors, +4 for
        found violations
    """
    # pylint: disable=broad-except

    errors = {}
    r = 0
    diffs_found = False

    try:
        langdir = os.listdir(LANGDIR)
    except FileNotFoundError:
        print("Directory {} not found. Please execute from project root directory.".format(LANGDIR))
        return 1

    for filename in langdir:
        try:
            if diff(filename):
                diffs_found = True
        except Exception as e:
            errors[filename] = e

    if errors:
        r += 2
        print("Errors while handling files:")
        for key, item in errors.items():
            print("{}: {}".format(key, item))

    if diffs_found:
        r += 4

    return r


if __name__ == "__main__":
    sys.exit(main())
