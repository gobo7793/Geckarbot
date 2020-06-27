import random
import datetime
import logging
import discord
from discord.ext import commands
from conf import Config

from Geckarbot import BasePlugin
from subsystems import timers


class Plugin(BasePlugin, name="Funny/Misc Commands"):

    def __init__(self, bot):
        super().__init__(bot)
        bot.register(self)

        self.reminders = {}

    def get_new_reminder_id(self):
        """
        Acquires a new reminder id
        :return: free id that can be used for a new timer
        """
        highest = 0
        for el in self.reminders:
            if el >= highest:
                highest = el + 1
        return highest

    @commands.command(name="dice", brief="Simulates rolling dice.",
                      usage="[NumberOfSides] [NumberOfDices]")
    async def dice(self, ctx, number_of_sides: int = 6, number_of_dice: int = 1):
        """Rolls number_of_dice dices with number_of_sides sides and returns the result"""
        dice = [
            str(random.choice(range(1, number_of_sides + 1)))
            for _ in range(number_of_dice)
        ]
        results = ', '.join(dice)
        if len(results) > 2000:
            pos_last_comma = results[:1995].rfind(',')
            results = f"{results[:pos_last_comma + 1]} ..."
        await ctx.send(results)

    @commands.command(name="kicker", help="Returns frequently used links to kicker.de")
    async def kicker_table(self, ctx):
        embed = discord.Embed(title=Config().lang(self, 'kicker_title'))
        embed.add_field(name=Config().lang(self, 'kicker_1BL'), value=Config().lang(self, 'kicker_1BL_link'))
        embed.add_field(name=Config().lang(self, 'kicker_2BL'), value=Config().lang(self, 'kicker_2BL_link'))
        embed.add_field(name=Config().lang(self, 'kicker_3FL'), value=Config().lang(self, 'kicker_3FL_link'))
        embed.add_field(name=Config().lang(self, 'kicker_ATBL'), value=Config().lang(self, 'kicker_ATBL_link'))
        await ctx.send(embed=embed)

    @commands.command(name="ping", help="Pings the bot.")
    async def ping(self, ctx):
        await ctx.send(Config().lang(self, 'ping_out'))

    @commands.command(name="mud", brief="Pings the bot.")
    async def mud(self, ctx):
        await ctx.send(Config().lang(self, 'mud_out'))

    @commands.command(name="mudkip", brief="MUDKIP!")
    async def mudkip(self, ctx):
        await ctx.send(Config().lang(self, 'mudkip_out'))

    @commands.command(name="nico", help="Punches Nico.")
    async def nico(self, ctx):
        await ctx.send(Config().lang(self, 'nico_output'))

    @commands.command(name="mimimi", help="Provides an .mp3 file that plays the sound of 'mimimi'.")
    async def mimimi(self, ctx):
        await ctx.trigger_typing()
        file = discord.File(f"{Config().storage_dir(self)}/mimimi.mp3")
        await ctx.send(file=file)

    @commands.command(name="geck", help="GECKARBOR!")
    async def geck(self, ctx):
        await ctx.trigger_typing()
        file = discord.File(f"{Config().storage_dir(self)}/treecko.jpg")
        await ctx.send(Config().lang(self, 'geck_out'), file=file)

    @commands.command(name="liebe", help="Provides love to the channel")
    async def liebe(self, ctx):
        await ctx.send(Config().lang(self, 'liebe_out'))

    @commands.command(name="tippspiel", help="Gives the link to the Tippspiel-Sheet")
    async def tippspiel(self, ctx):
        await ctx.send(Config().lang(self, 'tippspiel_output'))

    @commands.command(name="remindme", help="Reminds the author.",
                      usage="<duration|DD.MM.YYYY HH:MM|cancel> [message|cancel_id]",
                      description="Reminds the author in x minutes, hours or days or on a fixed date and time or "
                                  "cancels the users reminder with given ids. The duration unit can be set with "
                                  "trailing m for minutes, h for hours or d for days. If none is set, the duration "
                                  "unit is in minutes. Duration example: 5h = 5 hours. If no cancel id is given, "
                                  "all user reminders will be removed")
    async def reminder(self, ctx, *args):
        full_message = " ".join(args[1:])
        if args[0] == "cancel":
            if len(args) == 2:
                try:
                    remove_id = int(args[1])
                except ValueError:
                    raise commands.BadArgument(message=Config().lang(self, 'remind_del_id_err'))
            else:
                remove_id = -1

            # remove reminder with id
            if remove_id >= 0:
                if self.reminders[remove_id].data[0].author.id == ctx.author.id:
                    self.reminders[remove_id].cancel()
                    del(self.reminders[remove_id])
                    logging.info("Reminder {} removed".format(remove_id))
                    await ctx.send(Config().lang(self, 'remind_del'))
                    return

                await ctx.send(Config().lang(self, 'remind_wrong_del'))
                return

            # remove all reminders from user
            to_remove = []
            for el in self.reminders:
                if self.reminders[el].data[0].author.id == ctx.author.id:
                    to_remove.append(el)
            for el in to_remove:
                self.reminders[el].cancel()
                del(self.reminders[el])
                logging.info("Reminder {} removed".format(el))

            await ctx.send(Config().lang(self, 'remind_del'))
            return

        # set reminder
        try:
            remind_time = datetime.datetime.strptime(f"{args[0]} {args[1]}", "%d.%m.%Y %H:%M")
            full_message = " ".join(args[2:])
        except ValueError:
            try:
                if args[0].endswith("m"):
                    remind_time = datetime.datetime.now() + datetime.timedelta(minutes=int(args[0][:-1]))
                elif args[0].endswith("h"):
                    remind_time = datetime.datetime.now() + datetime.timedelta(hours=int(args[0][:-1]))
                elif args[0].endswith("d"):
                    remind_time = datetime.datetime.now() + datetime.timedelta(days=int(args[0][:-1]))
                else:
                    remind_time = datetime.datetime.now() + datetime.timedelta(minutes=int(args[0]))
            except ValueError:
                raise commands.BadArgument(message=Config().lang(self, 'remind_duration_err'))

        logging.info("Adding reminder for {} at {}: {}".format(ctx.author.name, remind_time, full_message))

        timedict = timers.timedict(year=remind_time.year, month=remind_time.month, monthday=remind_time.day,
                                   hour=remind_time.hour, minute=remind_time.minute)
        job = self.bot.timers.schedule(self.reminder_callback, timedict, repeat=False)
        job.data = (ctx, full_message)

        reminder_id = self.get_new_reminder_id()
        self.reminders[reminder_id] = job

        await ctx.send(Config().lang(self, 'remind_set', remind_time.strftime('%d.%m.%Y %H:%M'), reminder_id))

    async def reminder_callback(self, job):
        ctx = job.data[0]
        message = job.data[1]
        remind_text = ""
        if message:
            remind_text = Config().lang(self, 'remind_callback_msg', message)
        await ctx.channel.send(Config().lang(self, 'remind_callback', ctx.author.mention, remind_text))
