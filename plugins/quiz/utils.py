from botutils import converters


def uemoji(config, user):
    """
    :param config: Plugin config
    :param user: User to return the emoji prefix for
    :return: Returns `user`'s emoji prefix.
    """
    if user is None:
        return ""

    if not isinstance(user, int):
        user = user.id
    if user in config["emoji"]:
        return "{} ".format(config["emoji"][user])
    return ""


def get_best_username(config, user, mention=False):
    """
    Wrapper for get_best_username() that includes the user's registered prefix emoji.

    :param config: Plugin config
    :param user: User to get the best username for
    :param mention: If True, returns the username as a mention
    :return: Best username for `user`
    """
    if mention:
        s = user.mention
    else:
        s = converters.get_best_username(user)
    return "{}{}".format(uemoji(config, user), s)
