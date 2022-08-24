from enum import Enum
from typing import List, Dict, Optional

from base.data import Lang
from botutils.converters import get_best_username
from botutils.stringutils import paginate, table
from plugins.lastfm.lfm_base import parse_layer, layer_api_map, Layer, Song


class Timeperiod(Enum):
    OVERALL = 0
    WEEK = 1
    MONTH_1 = 2
    MONTH_3 = 3
    MONTH_6 = 4
    YEAR = 5


tp_aliases: Dict[Timeperiod, List[str]] = {
    Timeperiod.OVERALL: ["all", "overall", "full"],
    Timeperiod.WEEK: ["7d", "week"],
    Timeperiod.MONTH_1: ["month", "1month", "1m"],
    Timeperiod.MONTH_3: ["3months", "3m"],
    Timeperiod.MONTH_6: ["6months", "6m"],
    Timeperiod.YEAR: ["year", "1y", "12months", "12m"],
}


tp_api_map: Dict[Timeperiod, str] = {
    Timeperiod.OVERALL: "overall",
    Timeperiod.WEEK: "7day",
    Timeperiod.MONTH_1: "1month",
    Timeperiod.MONTH_3: "3month",
    Timeperiod.MONTH_6: "6month",
    Timeperiod.YEAR: "12month"
}


method_api_map: Dict[Layer, str] = {
    Layer.TITLE: "toptracks",
    Layer.ALBUM: "topalbums",
    Layer.ARTIST: "topartists"
}


args_defaults = Layer.TITLE, Timeperiod.WEEK


def parse_timeperiod(s: str) -> Optional[Timeperiod]:
    for key, value in tp_aliases.items():
        if s in value:
            return key
    return None


def parse_args(args):
    """
    Parses args as gracefully as possible; ignores multiple occurences of the same argument type as well as non-args.

    :param args: List of passed arguments
    :return: List of parsed arguments: [Layer, Timeperiod]
    """
    layer_arg, tp_arg = args_defaults
    layer_set = False
    tp_set = False

    for arg in args:
        found = False

        ly = parse_layer(arg)
        if ly is not None and not layer_set:
            found = True
            layer_set = True
            layer_arg = ly

        tp = parse_timeperiod(arg)
        if tp is not None and not tp_set:
            found = True
            tp_set = True
            tp_arg = tp

        if not found:
            break

    return layer_arg, tp_arg


def format_entry(plugin, spot_no: int, entry: Song, first_place: Song) -> str:
    entry_s = entry.format()
    pct = ""
    if spot_no != 0 and plugin.get_config("top_show_percent"):
        pct = int(round(entry.playcount * 100 / first_place.playcount))
        pct = Lang.lang(plugin, "top_pct", pct)
    return Lang.lang(plugin, "top_entry", spot_no + 1, entry_s, entry.playcount, pct)


def format_header(plugin, tp: Timeperiod, layer: Layer, user) -> str:
    """
    Builds an introductory sentence to be used in a !top cmd response.

    :param plugin: Plugin ref
    :param tp: Requested timeperiod
    :param layer: Requested layer
    :param user: User
    :return: Header string
    """
    tp_text = Lang.lang(plugin, "tp_{}".format(tp_api_map[tp]))
    layer_text = Lang.lang(plugin, "layer_{}_pl".format(layer_api_map[layer]))
    user = get_best_username(user)
    return Lang.lang(plugin, "top_header", layer_text, user, tp_text)


async def cmd_top(plugin, ctx, *args):
    layer, tp = parse_args(args)
    params = {
        "method": "user.get" + method_api_map[layer],
        "user": plugin.get_lastfm_user(ctx.author),
        "period": tp_api_map[tp]
    }
    response = await plugin.api.request(params)

    first_song = None
    msgs = [format_header(plugin, tp, layer, ctx.author)]
    entries = []
    for i in range(plugin.get_config("top_length")):
        el = response.get(method_api_map[layer]).get(layer_api_map[layer])[i]
        song = Song.from_lastfm_response(plugin, el, layer=layer)
        if first_song is None:
            first_song = song

        song_s = song.format()
        pct = ""
        if i != 0 and plugin.get_config("top_show_percent"):
            pct = int(round(song.playcount * 100 / first_song.playcount))
            pct = Lang.lang(plugin, "top_pct", pct)
        playcount_s = Lang.lang(plugin, "top_playcount", song.playcount, pct)
        spot_s = Lang.lang(plugin, "top_spot", i + 1)
        entries.append((spot_s, song_s, playcount_s))

    if plugin.get_config("top_table"):
        msgs.append(table(entries))
    else:
        for el in entries:
            msgs.append(Lang.lang(plugin, "top_entry", *el))

    for msg in paginate(msgs):
        await ctx.send(msg)
