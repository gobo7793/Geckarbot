import logging

from data import Config, Storage
from plugins.fantasy.utils import Platform

log = logging.getLogger(__name__)


def migrate(plugin):
    """
    Migrates the config versions of the fantasy plugin

    :param plugin: The class:`plugins.fantasy.fantasy.Plugin` instance
    """
    if Config.get(plugin)["version"] == 2:
        _2_to_3(plugin)
    if Config.get(plugin)["version"] == 3:
        _3_to_4(plugin)
    if Config.get(plugin)["version"] == 4:
        _4_to_5(plugin)
    if Config.get(plugin)["version"] == 5:
        _5_to_6(plugin)
    if Config.get(plugin)["version"] == 6:
        _6_to_7(plugin)


def _6_to_7(plugin):
    log.info("Migrating config from version 6 to version 7")

    Config.get(plugin)["espn_credentials"] = {
        "swid": Storage.get(plugin)["espn_credentials"]["swid"],
        "espn_s2": Storage.get(plugin)["espn_credentials"]["espn_s2"]
    }
    del Storage.get(plugin)["espn_credentials"]

    Config.get(plugin)["version"] = 7
    Storage.save(plugin)
    Config.save(plugin)

    log.info("Update finished")


def _5_to_6(plugin):
    log.info("Migrating config from version 5 to version 6")

    leagues_data = Storage.get(plugin)["leagues"]
    Storage.get(plugin)["leagues"] = dict(enumerate(leagues_data))
    def_data = Storage.get(plugin)["def_league"]
    for k in Storage.get(plugin)["leagues"]:
        league = Storage.get(plugin)["leagues"][k]
        if def_data and league["league_id"] == def_data[0] and league["platform"] == def_data[1]:
            Storage.get(plugin)["def_league"] = k
            break
    else:
        Storage.get(plugin)["def_league"] = -1

    Config.get(plugin)["version"] = 6
    Storage.save(plugin)
    Config.save(plugin)

    log.info("Update finished")


def _4_to_5(plugin):
    log.info("Migrating config from version 4 to version 5")

    Storage.get(plugin)["def_league"] = []

    Config.get(plugin)["version"] = 5
    Storage.save(plugin)
    Config.save(plugin)

    log.info("Update finished")


def _3_to_4(plugin):
    log.info("Migrating config from version 3 to version 4")

    for league in Storage.get(plugin)["leagues"]:
        league['platform'] = Platform.ESPN
        league['league_id'] = league['espn_id']
        del league['espn_id']
    Storage.get(plugin)["espn_credentials"] = Storage.get(plugin)["api"]

    new_cfg = plugin.default_config()
    new_cfg["channel_id"] = Config.get(plugin)["channel_id"]
    new_cfg["mod_role_id"] = Config.get(plugin)["mod_role_id"]
    new_cfg["espn"]["url_base_league"] = Config.get(plugin)["url_base_league"] + "{}"
    new_cfg["espn"]["url_base_scoreboard"] = Config.get(plugin)["url_base_scoreboard"] + "{}"
    new_cfg["espn"]["url_base_standings"] = Config.get(plugin)["url_base_standings"] + "{}"
    new_cfg["espn"]["url_base_boxscore"] = Config.get(plugin)["url_base_boxscore"]
    new_cfg["version"] = 4

    Config.set(plugin, new_cfg)
    Storage.save(plugin)
    Config.save(plugin)

    log.info("Update finished")


def _2_to_3(plugin):
    log.info("Migrating config from version 2 to version 3")

    Config.get(plugin)["url_base_boxscore"] = plugin.default_config()["espn"]["url_base_boxscore"]
    Config.get(plugin)["version"] = 3
    Config.save(plugin)

    log.info("Update finished")
