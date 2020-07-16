from botutils import utils


def uemoji(config, user):
    if not isinstance(user, int):
        user = user.id
    if user in config["emoji"]:
        return "{} ".format(config["emoji"][user])
    return ""


def get_best_username(config, user):
    return "{}{}".format(uemoji(config, user), utils.get_best_username(user))
