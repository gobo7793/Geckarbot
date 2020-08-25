import emoji
from discord.ext import commands


def paginate(items, prefix="", suffix="", msg_prefix="", msg_suffix="", delimiter="\n", f=lambda x: x,
             if_empty=None, prefix_within_msg_prefix=True):
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
    :return:
    """
    threshold = 1900
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

            # Handle message that was accumulated so far
            if current_msg:
                yield "".join(current_msg) + msg_suffix

            # Handle the split message
            yield _prefix + item + _suffix
            first = False
            continue

        current_msg.append(item)
        so_far = delimiter.join(current_msg)
        if len(_prefix + so_far + delimiter + item + _suffix) > threshold or i == len(items) - 1:
            yield _prefix + so_far + _suffix
            first = False
            current_msg = []

        i += 1


def format_andlist(andlist, ands="and", emptylist="nobody", fulllist="everyone", fulllen=None):
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


def sg_pl(number, singular, plural):
    if number == 1:
        return singular
    return plural


async def emojize(demote_str, ctx):
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


async def demojize(emote, ctx):
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


def clear_link(link):
    """Removes trailing and leading < and > from links"""
    if link.startswith('<'):
        link = link[1:]
    if link.endswith('>'):
        link = link[:-1]
    return link
