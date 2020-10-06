from conf import Storage


def is_teamname_abbr(team):
    return team is not None and len(team) <= 3


class TeamnameDict:
    def __init__(self, plugin):
        self.teamdict = {}
        teamnames = Storage().get(plugin)['teamnames']
        for long_name, team in teamnames.items():
            self.teamdict[team['short_name'].lower()] = long_name
            self.teamdict[long_name.lower()] = team['short_name']
        for long_name, team in teamnames.items():
            for name in team['other']:
                if is_teamname_abbr(name):
                    # Abbreviation
                    self.teamdict.setdefault(name.lower(), long_name)
                else:
                    # Long name
                    self.teamdict.setdefault(name.lower(), team['short_name'])

    def get_long(self, team):
        name = self.teamdict.get(team.lower())
        if is_teamname_abbr(name):
            name = self.teamdict.get(name.lower())
        return name

    def get_abbr(self, team):
        name = self.teamdict.get(team.lower())
        if not is_teamname_abbr(name):
            name = self.teamdict.get(name.lower())
        return name