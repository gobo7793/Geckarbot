from conf import Storage


def migrate_0_to_1(plugin):
    structure = Storage.get(plugin)
    for uid in structure["ladder"]:
        points = structure["ladder"][uid]
        structure["ladder"][uid] = {
            "points": points,
            "games_played": 1,
        }
    structure["version"] = 1
    Storage.save(plugin)


def migration(plugin, logger):
    migrations = {
        0: migrate_0_to_1
    }

    base = Storage.get(plugin)
    while True:
        # Determine version
        if "version" in base:
            version = base["version"]
        else:
            version = 0

        if version in migrations:
            logger.info("Migrating quiz data from version {} to the next".format(version))
            migrations[version](plugin)
        else:
            break
