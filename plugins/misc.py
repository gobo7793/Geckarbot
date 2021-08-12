import logging
import random
import string
import locale
from datetime import datetime, timezone, timedelta
from math import pi

import discord
from discord.ext import commands

from botutils import restclient, utils, timeutils
from botutils.converters import get_best_username
from botutils.utils import add_reaction
from botutils.stringutils import table, parse_number, format_number, Number
from data import Lang, Config, Storage
from base import BasePlugin
from subsystems.helpsys import DefaultCategories

log = logging.getLogger(__name__)
_KEYSMASH_CMD_NAME = "keysmash"


def _create_keysmash():
    return "".join(random.choices(string.ascii_lowercase, k=random.randint(25, 35)))


class Plugin(BasePlugin, name="Funny/Misc Commands"):
    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self, DefaultCategories.MISC)

        # Add commands to help category 'utils'
        to_add = ("dice", "choose", "multichoose", "money")
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
        response = await restclient.Client("https://api.wolframalpha.com/v1/")\
            .request("result", params={'i': " ".join(args), 'appid': self.bot.WOLFRAMALPHA_API_KEY}, parse_json=False)
        await ctx.send(Lang.lang(self, 'alpha_response', response))

    @commands.command(name="choose")
    async def cmd_choose(self, ctx, *args):
        full_options_str = " ".join(args)
        if "sabaton" in full_options_str.lower():
            await ctx.send(Lang.lang(self, 'choose_sabaton'))

        options = [i for i in full_options_str.split("|") if i.strip() != ""]
        if len(options) < 1:
            await ctx.send(Lang.lang(self, 'choose_noarg'))
            return
        result = random.choice(options)
        await ctx.send(Lang.lang(self, 'choose_msg') + result.strip())

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

    @commands.command(name="multichoose")
    async def cmd_multichoose(self, ctx, count: int, *args):
        full_options_str = " ".join(args)
        options = [i for i in full_options_str.split("|") if i.strip() != ""]
        if count < 1 or len(options) < count:
            await ctx.send(Lang.lang(self, 'choose_falsecount'))
            return
        result = random.sample(options, k=count)
        await ctx.send(Lang.lang(self, 'choose_msg') + ", ".join(x.strip() for x in result))

    @commands.command(name="mud")
    async def cmd_mud(self, ctx):
        await ctx.send(Lang.lang(self, 'mud_out'))

    @commands.command(name="mudkip")
    async def cmd_mudkip(self, ctx):
        await ctx.send(Lang.lang(self, 'mudkip_out'))

    @commands.command(name="mimimi")
    async def cmd_mimimi(self, ctx):
        async with ctx.typing():
            file = discord.File(f"{Config().resource_dir(self)}/mimimi.mp3")
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
                file = discord.File(treecko_file)
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

        pizzas = []
        single_unit = None
        single_relprice = None
        for i in range(len(args) // 2):
            d = parse_number(args[i*2])
            price = parse_number(args[i*2 + 1])
            pizzas.append([d, price, None])

        for i in range(len(pizzas)):
            d, price, _ = pizzas[i]
            rel = pi * (d.number / 2)**2
            single_relprice = rel
            unit = ""
            if price.unit and d.unit:
                unit = "{}/{}²".format(price.unit, d.unit)
                single_unit = unit
            pizzas[i][2] = Number(rel, unit)

            # Format to string in-place
            for j in range(len(pizzas[0])):
                split_unit = False if j == 0 else True
                pizzas[i][j] = format_number(pizzas[i][j], split_unit=split_unit)

        # Format table or print single result
        if len(pizzas) == 1:
            a = single_unit if single_unit else Lang.lang(self, "pizza_a")
            await ctx.send(Lang.lang(self, "pizza_single_result", format_number(single_relprice), a))
        else:
            # Add table header
            h = [Lang.lang(self, "pizza_header_d"),
                 Lang.lang(self, "pizza_header_price"),
                 Lang.lang(self, "pizza_header_rel")]
            pizzas.insert(0, h)
            await ctx.send(table(pizzas, header=True))
