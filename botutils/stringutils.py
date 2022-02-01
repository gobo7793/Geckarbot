import re
import locale
from collections import namedtuple
from typing import Union, Any, Callable, Optional

import emoji
from nextcord.ext import commands


Number = namedtuple("Number", "number unit")
_pattern = re.compile(r"(-?)(\d*)[.,]?(\d*)\s*(.*)")


def parse_number(s: str) -> Number:
    """
    Parses any string of the form "4,43cm", "4", ".3 m" or "4 cm" into a `Number` object. Accepts both `.` and `,` as
    decimal points.
    A Number object has the attributes `number` (can be int or float) and `unit` (can be any string, including "").

    :param s: string to parse
    :return: `Number` object that represents the parsed number
    :raise ValueError: If `Number.number` cannot be filled, i.e. `s` does not begin with a decimal.
    """
    sign, i, f, unit = _pattern.match(s.strip()).groups()
    if i:
        i = int(i)
    elif f:
        i = 0
    else:
        raise ValueError("s is not a number string")

    sign = -1 if sign else 1
    i = sign * i

    if f:
        lf = len(f)
        f = int(f)
        if f != 0:
            r = i + sign * (int(f) / (10 ** lf))
        else:
            r = i
    else:
        r = i
    return Number(r, unit)


def format_number(n: Union[Number, int, float], decplaces: int = 2, split_unit: bool = True) -> str:
    """
    Formats a number into a nice-looking string.

    :param n: number
    :param decplaces: amount of decimal places to be displayed
    :param split_unit: Splits number and unit with a whitespace if True (and len(unit) > 1).
    :return:
    """
    if isinstance(n, Number):
        n, unit = n
    else:
        unit = None

    if isinstance(n, int):
        r = str(n)
    else:
        r = locale.format_string("%.{}f".format(decplaces), n)

    if unit:
        if len(unit) == 1 or not split_unit:
            r = "{}{}".format(r, unit)
        else:
            r = "{} {}".format(r, unit)

    return r


def paginate(items: list, prefix: str = "", suffix: str = "", msg_prefix: str = "", msg_suffix: str = "",
             delimiter: str = "\n", f: Callable = lambda x: x,
             if_empty: Any = None, prefix_within_msg_prefix: bool = True, threshold: int = 1900) -> str:
    """
    Generator for pagination. Compiles the entries in `items` into strings that are shorter than 2000 (discord max
    message length). If a single item is longer than 2000, it is put into its own message.

    :param items: List of items that are to be put into message strings
    :param prefix: The first message has this prefix.
    :param suffix: The last message has this suffix.
    :param msg_prefix: Every message has this prefix.
    :param msg_suffix: Every message has this suffix.
    :param delimiter: Delimiter for the list entries.
    :param f: function that is invoked on every `items` entry.
    :param prefix_within_msg_prefix: If this is True, `msg_prefix` comes before `prefix` in the first message.
        If not, `prefix` comes before `msg_prefix` in the first message.
    :param if_empty: If the list of items is empty, this one is inserted as the only item. Caution: f is executed
        on this.
    :param threshold: Threshold to split messages. Useful for embed field values which have a max. length of 1024.
    :return: The paginated string to send in discord messages
    :raises RuntimeError: If `items` is a string
    """
    if isinstance(items, str):
        raise RuntimeError("Pagination does not work on strings")
    current_msg = []
    remaining = None
    first = True

    if len(items) == 0 and if_empty is not None:
        items = [if_empty]

    i = 0
    while i != len(items):
        if remaining is None:
            item = str(f(items[i]))
        else:
            item = remaining
            remaining = None

        # Build potential prefix and suffix of this message candidate
        _prefix = msg_prefix
        if first:
            if prefix_within_msg_prefix:
                _prefix = msg_prefix + prefix
            else:
                _prefix = prefix + msg_prefix

        _suffix = msg_suffix
        if i == len(items) - 1:
            _suffix = msg_suffix + suffix

        # Split item if too large
        if len(item) + len(_prefix) + len(_suffix) > threshold:
            _suffix = msg_suffix
            li = len(item) + len(_prefix) + len(_suffix)
            item = item[:li]
            remaining = item[li:]
            first = False

            # Handle message that was accumulated so far
            if current_msg:
                yield "".join(current_msg) + msg_suffix

            # Handle the split message
            yield _prefix + item + _suffix
            continue

        so_far = delimiter.join(current_msg)
        if len(_prefix + so_far + delimiter + item + _suffix) > threshold:
            first = False
            yield _prefix + so_far + _suffix
            current_msg = []

        current_msg.append(item)

        # Last
        if i == len(items) - 1:
            if not first:
                _prefix = msg_prefix
            yield _prefix + delimiter.join(current_msg) + _suffix
        i += 1


def format_andlist(andlist: list, ands: str = "and", emptylist: str = "nobody", fulllist: str = "everyone",
                   fulllen: Optional[int] = None) -> str:
    """
    Builds a string such as "a, b, c and d".

    :param andlist: List of elements to be formatted in a string.
    :param ands: "and"-string that sits between the last two users.
    :param emptylist: Returned if andlist is empty.
    :param fulllist: Returned if andlist has length fulllen.
    :param fulllen: Length of the full andlist. Useful to say "everyone" instead of listing everyone.
    :return: String that contains all elements or emptylist if the list was empty.
    """
    if fulllen is not None and len(andlist) == fulllen:
        return fulllist

    if len(andlist) == 0:
        return emptylist

    if len(andlist) == 1:
        return str(andlist[0])

    s = ", ".join(andlist[:-1])
    return "{} {} {}".format(s, ands, andlist[-1])


def sg_pl(number: int, singular: str, plural: str) -> str:
    """
    Returns the singular or plural term based on the number

    :param number: The number to determine
    :param singular: The singular term
    :param plural: The plural term
    :return: The correct term for the given number
    """
    if number == 1:
        return singular
    return plural


async def emojize(demote_str: str, ctx: commands.Context) -> str:
    """
    Converts the demojized str represantation of the emoji back to an emoji string

    :param demote_str: The string representation of the emoji
    :param ctx: The command context for the discord.py emoji converters
    :return: The emojized string
    """
    try:
        emote = await commands.PartialEmojiConverter().convert(ctx, demote_str)
    except commands.CommandError:
        emote = emoji.emojize(demote_str, True)
    return str(emote)


async def demojize(emote: str, ctx: commands.Context) -> str:
    """
    Converts the emojized str of the emoji to its demojized str representation

    :param emote: The msg with the emoji (only the emoji)
    :param ctx: The command context for the discord.py emoji converters
    :return: The demojized string or an empty string if no emoji found
    """
    try:
        converted = await commands.PartialEmojiConverter().convert(ctx, emote)
    except commands.CommandError:
        converted = emoji.demojize(emote, True)
    return str(converted)


def clear_link(link: str) -> str:
    """
    Removes trailing and leading < and > from links

    :param link: The link
    :return: The cleared link
    """
    if link.startswith('<'):
        link = link[1:]
    if link.endswith('>'):
        link = link[:-1]
    return link


def table(tablelist: Union[list, tuple], header: bool = False, prefix: str = "```", suffix: str = "```") -> str:
    """
    Takes a list of the form [[0, 1], [2, 3], [4, 5]], interprets it as a list of table lines and formats it into
    a string that (assuming monospace) looks like a table.
    Does not support max table width or any sort of line break.

    :param tablelist: List of lines.
    :param header: Flag to format the first line in a way that displays it as the header line. If False, tablelist
        is interpreted as if there was no header line.
    :param prefix: table prefix, defaults to ```
    :param suffix: table suffix, defaults to ```
    :return: Formatted
    :raises RuntimeError: If the table rows do not have the same length (i.e. table is not a rectangle)
    """
    # dim check
    for i in range(1, len(tablelist)):
        if len(tablelist[i]) != len(tablelist[i-1]):
            raise RuntimeError("Table does not have uniform dimensions: {}")

    width = len(tablelist[0])
    height = len(tablelist)

    # Calc cell widths
    cellwidths = []
    for j in range(width):
        for i in range(height):
            candidate = len(str(tablelist[i][j]))
            if i == 0:
                cellwidths.append(candidate)
                continue

            if candidate > cellwidths[j]:
                cellwidths[j] = candidate

    # Build lines
    r = []
    for i in range(height):
        # underline header
        if header and i == 1:
            h = []
            for j in range(width):
                h.append("-" * (cellwidths[j] + 2))
            r.append("+".join(h))

        # Build table row
        row = []
        for j in range(width):
            item = str(tablelist[i][j])
            item = " " + item + " " * (cellwidths[j]+1 - len(item))
            row.append(item)
        r.append("|".join(row))

    return prefix + "\n".join(r) + suffix
