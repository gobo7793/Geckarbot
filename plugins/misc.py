import locale
import logging
import random
import re
import string
import hashlib
from datetime import datetime, timezone, timedelta
from math import pi
from typing import List, Iterable, Dict, Optional

from aiohttp import ClientConnectorError
from nextcord import File, Embed
from nextcord.ext import commands
from nextcord.ext.commands import Context

from botutils import restclient, utils, timeutils
from botutils.converters import get_best_username
from botutils.timeutils import TimestampStyle
from botutils.utils import add_reaction
from botutils.stringutils import table, parse_number, format_number, Number
from base.data import Lang, Config, Storage
from base.configurable import BasePlugin
from services.helpsys import DefaultCategories

log = logging.getLogger(__name__)
_KEYSMASH_CMD_NAME = "keysmash"


def _create_keysmash():
    return "".join(random.choices(string.ascii_lowercase, k=random.randint(25, 35)))


class Plugin(BasePlugin, name="Funny/Misc Commands"):
    def __init__(self):
        super().__init__()
        self.bot = Config().bot
        self.bot.register(self, DefaultCategories.MISC)

        # Add commands to help category 'utils'
        to_add = ("dice", "choose", "multichoose", "shuffle", "money", "pizza", "timestamp", "hash")
        for cmd in self.get_commands():
            if cmd.name in to_add:
                self.bot.helpsys.default_category(DefaultCategories.UTILS).add_command(cmd)
                self.bot.helpsys.default_category(DefaultCategories.MISC).remove_command(cmd)

    def command_help_string(self, command):
        if command.name == _KEYSMASH_CMD_NAME:
            return _create_keysmash()
        return utils.helpstring_helper(self, command, "help")

    def command_description(self, command):
        return utils.helpstring_helper(self, command, "desc")

    def command_usage(self, command):
        return utils.helpstring_helper(self, command, "usage")

    def default_storage(self, container=None):
        return {'stopwatch': {}}

    @commands.command(name="dice")
    async def cmd_dice(self, ctx, number_of_sides: int = 6, number_of_dice: int = 1):
        """Rolls number_of_dice dices with number_of_sides sides and returns the result"""
        dice = [
            str(random.choice(range(1, number_of_sides + 1)))
            for _ in range(number_of_dice)
        ]
        results = ', '.join(dice)
        if len(results) > 2000:
            pos_last_comma = results[:1998].rfind(',')
            results = f"{results[:pos_last_comma + 1]}\u2026"
        await ctx.send(results)

    @commands.command(name="alpha")
    async def cmd_wolframalpha(self, ctx, *args):
        if not self.bot.WOLFRAMALPHA_API_KEY:
            await add_reaction(ctx.message, Lang.CMDERROR)
            return
        if not args:
            await Config().bot.helpsys.cmd_help(ctx, self, ctx.command)
            return

        response = await restclient.Client("https://api.wolframalpha.com/v1/")\
            .request("result", params={'i': " ".join(args), 'appid': self.bot.WOLFRAMALPHA_API_KEY}, parse_json=False)
        await ctx.send(Lang.lang(self, 'alpha_response', response))

    @staticmethod
    def parse_rnd_args(args: Iterable) -> List[str]:
        """
        Parses the args that were parsed to an RNG function (e.g. !choose).

        :param args: args
        :return:
        """
        full_options_str = " ".join(args)
        return [i for i in full_options_str.split("|") if i.strip() != ""]

    @commands.command(name="choose")
    async def cmd_choose(self, ctx, *args):
        options = self.parse_rnd_args(args)
        if "sabaton" in [el.lower() for el in options]:
            await ctx.send(Lang.lang(self, 'choose_sabaton'))
        if len(options) < 1:
            await ctx.send(Lang.lang(self, 'choose_noarg'))
            return
        result = random.choice(options)
        await ctx.send(Lang.lang(self, 'choose_msg') + result.strip())

    @commands.command(name="multichoose")
    async def cmd_multichoose(self, ctx, count: int, *args):
        options = self.parse_rnd_args(args)
        if count < 1 or len(options) < count:
            await ctx.send(Lang.lang(self, 'choose_falsecount'))
            return
        result = random.sample(options, k=count)
        await ctx.send(Lang.lang(self, 'choose_msg') + ", ".join(x.strip() for x in result))

    @commands.command(name="shuffle")
    async def cmd_shuffle(self, ctx, *args):
        options = self.parse_rnd_args(args)
        if len(options) < 1:
            await ctx.send(Lang.lang(self, 'choose_noarg'))
            return
        random.shuffle(options)
        await ctx.send(Lang.lang(self, 'choose_msg') + ", ".join(x.strip() for x in options))

    @commands.command(name="kw", aliases=["week"])
    async def cmd_week_number(self, ctx, *, date=None):
        day: datetime
        if date:
            day = timeutils.parse_time_input(date)
            if day == datetime.max:
                await add_reaction(ctx.message, Lang.CMDERROR)
                return
        else:
            day = datetime.today()
        week = day.isocalendar()[1]
        await ctx.send(Lang.lang(self, 'week_number', week))

    @commands.command(name="mud")
    async def cmd_mud(self, ctx):
        await ctx.send(Lang.lang(self, 'mud_out'))

    @commands.command(name="mudkip")
    async def cmd_mudkip(self, ctx):
        await ctx.send(Lang.lang(self, 'mudkip_out'))

    @commands.command(name="mimimi")
    async def cmd_mimimi(self, ctx):
        async with ctx.typing():
            file = File(f"{Config().resource_dir(self)}/mimimi.mp3")
            await ctx.send(file=file)

    @commands.command(name="money")
    async def cmd_money_converter(self, ctx, currency, arg2=None, arg3: float = None):
        if not self.bot.WOLFRAMALPHA_API_KEY:
            await add_reaction(ctx.message, Lang.CMDERROR)
            return
        if arg3:
            amount = arg3
            other_curr = arg2
        elif arg2:
            try:
                amount = float(arg2)
            except (TypeError, ValueError):
                other_curr = arg2
                amount = 1
            else:
                other_curr = "EUR"
        else:
            amount = 1
            other_curr = "EUR"
        response = await restclient.Client("https://api.wolframalpha.com/v1/")\
            .request("result", params={'i': f"convert {amount} {currency} to {other_curr}",
                                       'appid': self.bot.WOLFRAMALPHA_API_KEY}, parse_json=False)
        if response != "Wolfram|Alpha did not understand your input":
            await ctx.send(Lang.lang(self, 'alpha_response', response))
        else:
            await ctx.send(Lang.lang(self, 'money_error'))

    @commands.command(name="geck")
    async def cmd_geck(self, ctx):
        treecko_file = f"{Config().resource_dir(self)}/treecko.jpg"
        async with ctx.typing():
            try:
                file = File(treecko_file)
            except (FileNotFoundError, IsADirectoryError):
                await utils.add_reaction(ctx.message, Lang.CMDERROR)
                await utils.write_debug_channel(Lang.lang(self, 'geck_error', treecko_file))
                return
        await ctx.send(Lang.lang(self, 'geck_out'), file=file)

    @commands.command(name=_KEYSMASH_CMD_NAME)
    async def cmd_keysmash(self, ctx):
        msg = _create_keysmash()
        await ctx.send(msg)

    @commands.command(name="werwars", alsiases=["wermobbtgerade"])
    async def cmd_who_mobbing(self, ctx):
        after_date = (datetime.now(timezone.utc) - timedelta(minutes=30)).replace(tzinfo=None)
        users = [self.bot.user]
        messages = await ctx.channel.history(after=after_date).flatten()
        for message in messages:
            if message.author not in users:
                users.append(message.author)

        bully = random.choice(users)

        if bully is self.bot.user:
            text = Lang.lang(self, "bully_msg_self")
        else:
            text = Lang.lang(self, "bully_msg", get_best_username(bully))
        await ctx.send(text)

    @commands.command(name="stopwatch", aliases=["stoppuhr", "stopuhr"])
    async def cmd_stopwatch(self, ctx):
        if ctx.author.id in Storage().get(self)['stopwatch']:
            timediff = datetime.now() - datetime.fromisoformat(Storage().get(self)['stopwatch'].pop(ctx.author.id))
            timediff_parts = [timediff.days, timediff.seconds // 3600, timediff.seconds // 60 % 60,
                              timediff.seconds % 60 + round(timediff.microseconds / 1_000_000, 2)]
            timediff_zip = zip(timediff_parts, Lang.lang(self, 'stopwatch_units').split("|"))
            msg = ", ".join(f"{x} {y}" for x, y in timediff_zip if x != 0)
            await ctx.send(msg)
        else:
            Storage().get(self)['stopwatch'][ctx.author.id] = str(datetime.now())
            await ctx.send(Lang.lang(self, 'stopwatch_started'))
        Storage().save(self)

    @commands.command(name="pizza")
    async def cmd_pizza(self, ctx, *args):
        if len(args) % 2 == 1:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await ctx.send(Lang.lang(self, "pizza_argsdim", args[-1]))
            return

        if len(args) == 0:
            await add_reaction(ctx.message, Lang.CMDERROR)
            await self.bot.helpsys.cmd_help(ctx, self, ctx.command)
            return

        pizzas: List[List[...]] = []
        single_d_unit = None
        single_relprice = None
        single_relunit = None
        single_priceunit = None
        for i in range(len(args) // 2):
            # format: direct arg parsing, i.e. [d, price]
            prepizza = [None, None]
            for j in range(2):
                arg = args[i*2 + j]
                try:
                    prepizza[j] = parse_number(arg)
                except ValueError:
                    await add_reaction(ctx.message, Lang.CMDERROR)
                    await ctx.send(Lang.lang(self, "pizza_nan", arg))
                    return

            # format: [d, price, relative]
            pizzas.append([prepizza[0], prepizza[1], None])

        # Calc
        for i in range(len(pizzas)):
            d, price, _ = pizzas[i]
            rel = price.number / (pi * (d.number / 2)**2)
            single_relprice = rel
            unit = ""
            if d.unit:
                single_d_unit = d.unit + "²"
                if price.unit:
                    unit = "{}/{}²".format(price.unit, d.unit)
                    single_relunit = unit
            if price.unit:
                single_priceunit = price.unit
            pizzas[i][2] = Number(rel, unit)

        # Sort
        pizzas = sorted(pizzas, key=lambda x: x[2].number)

        # build percentages
        baserel = pizzas[0][2]
        perct = [""]
        for i in range(1, len(pizzas)):
            p = (pizzas[i][2].number / baserel.number - 1) * 100
            perct.append(" (+{}%)".format(locale.format_string("%.1f", p)))

        # Format to string in-place
        for i in range(len(pizzas)):
            for j in range(len(pizzas[0])):
                split_unit = not j == 0
                decpl = 4 if j == 2 else 2
                pizzas[i][j] = format_number(pizzas[i][j], decplaces=decpl, split_unit=split_unit)

                # add percentages
                if j == len(pizzas[0]) - 1:
                    pizzas[i][j] += perct[i]

        # Format table or print single result
        if len(pizzas) == 1:
            # Format units
            if single_relunit:
                a = single_relunit
            elif single_d_unit:
                a = Lang.lang(self, "pizza_a_unit", single_d_unit)
            else:
                a = Lang.lang(self, "pizza_a")
            if single_priceunit and not single_relunit:
                single_relprice = Number(single_relprice, single_priceunit)

            single_relprice = format_number(single_relprice, decplaces=4)
            await ctx.send(Lang.lang(self, "pizza_single_result", single_relprice, a))
        else:
            # Add table header
            h = [Lang.lang(self, "pizza_header_d"),
                 Lang.lang(self, "pizza_header_price"),
                 Lang.lang(self, "pizza_header_rel")]
            pizzas.insert(0, h)
            await ctx.send(table(pizzas, header=True))

    @commands.command(name="timestamp")
    async def cmd_timestamp(self, ctx, date: str, time_format: str = "", style: str = ""):
        ts_style = TimestampStyle.DATETIME_SHORT

        if not time_format:
            # !timestamp 18.11.2020
            timestamp = timeutils.parse_time_input(date)
        else:
            if not style:
                # !timestamp 18.11.2020 22:50
                try:
                    ts_style = TimestampStyle(time_format)
                    timestamp = timeutils.parse_time_input(date)
                except ValueError:
                    try:
                        ts_style = TimestampStyle[time_format]
                        timestamp = timeutils.parse_time_input(date)
                    except KeyError:
                        timestamp = timeutils.parse_time_input(date, time_format)
            else:
                # !timestamp 18.11.2020 22:50 R
                # !timestamp 18.11.2020 22:50 RELATIVE
                timestamp = timeutils.parse_time_input(date, time_format)
                style = style.upper() if len(style) > 1 else style
                try:
                    ts_style = TimestampStyle(style)
                except ValueError:
                    try:
                        ts_style = TimestampStyle[style]
                    except KeyError:
                        ts_style = TimestampStyle.DATETIME_SHORT

        unix_stamp = timeutils.to_unix_str(timestamp, ts_style)
        await ctx.send(f"{unix_stamp} → `{unix_stamp}`")

    @commands.command(name="hash")
    async def cmd_hash(self, ctx, alg: str, *, msg: str = ""):
        try:
            m = hashlib.new(alg.lower())
        except ValueError:
            await ctx.send(Lang.lang(self, "hash_alg_not_found", alg))
            await add_reaction(ctx.message, Lang.CMDERROR)
            return

        m.update(bytes(msg, "utf-8"))
        warning = Lang.lang(self, "hash_empty_string") if not msg else ""
        await ctx.send("{}`{}`".format(warning, m.hexdigest()))

    @commands.command(name="wiki")
    async def cmd_wiki(self, ctx: Context, lang: str, *, title: str = ""):
        langs = "de", "en", "fr", "es", "it"
        page = None
        if re.match("[a-zA-Z]{2,3}$", lang):
            page = await self.get_wikipage(lang, title)
        if not page:
            if len(lang) > 1 or lang not in r"!#$%&'()*+,\-./:;<=>?@[]^_`{|}~":  # Language Wildcard
                title = f"{lang} {title}"
            for _lang in langs:
                page = await self.get_wikipage(_lang, title)
                if page:
                    break
            else:
                # Nothing found
                await add_reaction(ctx.message, Lang.CMDNOCHANGE)
                return
        categories = [c['title'].split(":")[-1] for c in page['categories']]
        embed = Embed(description=page['extract'], timestamp=datetime.strptime(page['touched'], "%Y-%m-%dT%H:%M:%SZ"))
        embed.set_author(name=page['title'], url=page['fullurl'],
                         icon_url="https://de.wikipedia.org/static/apple-touch/wikipedia.png")
        embed.set_footer(text=f"Wikipedia ({page['pagelanguage'].upper()}) | " + ", ".join(categories[:3]))
        if 'thumbnail' in page:
            embed.set_thumbnail(url=page['thumbnail']['source'])
        await ctx.send(embed=embed)

    @staticmethod
    async def get_wikipage(lang: str, title: str) -> Optional[Dict[...]]:
        """
        Returns the page data for a wikipedia page.

        :param lang: language code for which wikipedia to search
        :param title: search term
        :return: page data if found, None else
        """
        if not title:
            return None
        try:
            result = await restclient.Client(f"https://{lang}.wikipedia.org/w/").request(
                "api.php", params={'action': "query", 'prop': "extracts|info|categories|pageimages", 'exchars': 500,
                                   'explaintext': True, 'exintro': True, 'redirects': 1, 'inprop': "url",
                                   'pithumbsize': 500, 'generator': "search", 'gsrsearch': title, 'gsrlimit': 1,
                                   'format': "json"})
        except ClientConnectorError:
            return None
        if 'query' not in result:
            return None
        _id, data = result['query']['pages'].popitem()
        if _id != "-1":
            return data
        return None
