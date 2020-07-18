from botutils import utils


def uemoji(config, user):
    if not isinstance(user, int):
        user = user.id
    if user in config["emoji"]:
        return "{} ".format(config["emoji"][user])
    return ""


def get_best_username(config, user, mention=False):
    print("config: {}".format(config))
    print("user: {}".format(user))
    if mention:
        s = user.mention
    else:
        s = utils.get_best_username(user)
    return "{}{}".format(uemoji(config, user), s)
