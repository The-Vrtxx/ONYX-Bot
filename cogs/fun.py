import random
import re
from io import BytesIO

import discord
from discord.ext import commands

COLOR = discord.Color.from_rgb(44, 38, 67)

JOKES = [
    ("Why did the computer go to the doctor?", "Because it had a virus."),
    ("Why was the math book sad?", "It had too many problems."),
    ("Why did the scarecrow win an award?", "Because he was outstanding in his field."),
    ("What do you call a sleeping dinosaur?", "A dino-snore."),
    ("Why did the bicycle fall over?", "It was two-tired."),
    ("What kind of tree fits in your hand?", "A palm tree."),
    ("Why did the computer get cold?", "It left its Windows open."),
    ("What do you call cheese that isn't yours?", "Nacho cheese."),
    ("Why don't skeletons fight each other?", "They don't have the guts."),
    ("What do clouds wear under their clothes?", "Thunderwear."),
    ("Why did the golfer bring two pairs of pants?", "In case he got a hole in one."),
    ("What did one wall say to the other wall?", "I'll meet you at the corner."),
]
FACTS = [
    "Octopuses have three hearts.", "A group of flamingos is called a flamboyance.",
    "Bananas are berries, botanically speaking.", "A day on Venus is longer than its year.",
    "Wombat droppings are cube-shaped.", "The Eiffel Tower can become slightly taller in hot weather.",
    "The fingerprints of a koala can look remarkably similar to human fingerprints.",
    "The Moon is slowly moving away from Earth.",
    "Some sea otters hold hands while resting so they don't drift apart.",
    "A bolt of lightning can heat the air around it to temperatures hotter than the Sun's surface.",
    "The world's largest desert is Antarctica.", "Sharks are older than trees in Earth's evolutionary history.",
]
WOULD_YOU_RATHER = [
    ("Have the ability to speak every language", "Be able to play every musical instrument"),
    ("Explore the deepest ocean", "Explore the surface of Mars"),
    ("Always have perfect Wi-Fi", "Never have to charge your phone"),
    ("Visit any point in history for one day", "Visit any point in the future for one day"),
    ("Have a photographic memory", "Be able to learn any skill twice as fast"),
    ("Live in a treehouse", "Live in a houseboat"),
    ("Have a personal robot assistant", "Have a personal teleportation device"),
    ("Only watch movies", "Only watch TV shows"),
    ("Be an expert chef", "Be an expert photographer"),
    ("Have unlimited books", "Have unlimited video games"),
    ("Be able to pause time", "Be able to rewind time"),
    ("Travel anywhere for free", "Eat at any restaurant for free"),
]
TRIVIA = [
    ("Which planet is known as the Red Planet?", ["Venus", "Mars", "Jupiter", "Mercury"], 1, "Mars looks reddish because of iron minerals in its soil."),
    ("How many sides does a hexagon have?", ["Five", "Six", "Seven", "Eight"], 1, "A hexagon has six sides."),
    ("What is the largest ocean on Earth?", ["Atlantic", "Indian", "Pacific", "Arctic"], 2, "The Pacific Ocean is the largest."),
    ("Which animal is the largest mammal?", ["African elephant", "Blue whale", "Giraffe", "Polar bear"], 1, "The blue whale is the largest known animal."),
    ("What is the chemical symbol for gold?", ["Ag", "Go", "Gd", "Au"], 3, "Au comes from the Latin word aurum."),
    ("How many colors are traditionally listed in a rainbow?", ["Five", "Six", "Seven", "Eight"], 2, "The traditional list has seven colors."),
    ("Which instrument has keys, pedals, and strings?", ["Flute", "Piano", "Trumpet", "Violin"], 1, "A piano produces sound when hammers strike strings."),
    ("What is the capital of Japan?", ["Seoul", "Beijing", "Tokyo", "Bangkok"], 2, "Tokyo is Japan's capital."),
    ("Which gas do plants absorb from the atmosphere?", ["Oxygen", "Carbon dioxide", "Helium", "Hydrogen"], 1, "Plants use carbon dioxide during photosynthesis."),
    ("How many degrees are in a right angle?", ["45", "90", "180", "360"], 1, "A right angle measures 90 degrees."),
    ("Which is the smallest prime number?", ["0", "1", "2", "3"], 2, "Two is the smallest prime number and the only even prime."),
    ("What is the largest planet in our solar system?", ["Earth", "Saturn", "Jupiter", "Neptune"], 2, "Jupiter is the largest planet in our solar system."),
]
RIDDLES = [
    ("What has keys but can't open locks?", "A piano."),
    ("What gets wetter the more it dries?", "A towel."),
    ("What has a neck but no head?", "A bottle."),
    ("What has many teeth but cannot bite?", "A comb."),
    ("What can travel around the world while staying in one corner?", "A stamp."),
    ("What has one eye but cannot see?", "A needle."),
    ("What has cities but no houses, forests but no trees, and water but no fish?", "A map."),
]
TRUTHS = [
    "What's a skill you'd love to learn?", "What's a movie you can watch over and over?",
    "What's the funniest thing that happened to you recently?",
    "If you could visit one country, where would you go?",
    "What's a small thing that always improves your day?",
    "What fictional world would you like to visit?",
    "What's a food combination you think is underrated?",
]
SAFE_DARES = [
    "Describe your day using only three emojis.", "Share your best clean joke.",
    "Talk like a sports commentator for your next message.", "Name five movies in ten seconds.",
    "Give someone in the server a genuine compliment.",
    "Describe your favorite song without saying its title.",
    "Send a GIF that matches your current mood.",
]
MEME_FORMATS = [
    ("Drake Hotline Bling", "Not this: {topic}", "YES THIS: {topic}"),
    ("Two Buttons", "Option A: {topic}", "Option B: also {topic}"),
    ("Expanding Brain", "Thinking about {topic}", "Overthinking {topic} at 3 AM"),
    ("Distracted Boyfriend", "Me trying to focus", "Me getting distracted by {topic}"),
    ("Change My Mind", "{topic} is the most underrated thing ever."),
    ("Nobody:", "Absolutely nobody:", "Me: {topic}"),
]


class TriviaView(discord.ui.View):
    def __init__(self, options, answer_index, explanation, author_id):
        super().__init__(timeout=90)
        self.options, self.answer_index = options, answer_index
        self.explanation, self.author_id, self.answered = explanation, author_id, False
        for index, option in enumerate(options):
            button = discord.ui.Button(label=option, style=discord.ButtonStyle.secondary,
                                       custom_id=f"onyx_trivia_{index}", row=index // 2)
            button.callback = self.make_callback(index)
            self.add_item(button)

    def make_callback(self, selected):
        async def callback(interaction):
            if interaction.user.id != self.author_id:
                return await interaction.response.send_message(
                    "This trivia round belongs to the person who started it. Start your own with `,trivia`!", ephemeral=True)
            if self.answered:
                return await interaction.response.send_message("This question has already been answered.", ephemeral=True)
            self.answered = True
            correct = selected == self.answer_index
            for item in self.children:
                item.disabled = True
                if item.label == self.options[self.answer_index]:
                    item.style = discord.ButtonStyle.success
                elif item.label == self.options[selected] and not correct:
                    item.style = discord.ButtonStyle.danger
            result = "Correct!" if correct else f"Not quite! The answer was **{self.options[self.answer_index]}**."
            embed = discord.Embed(title="🧠 Trivia Result", description=f"{result}\n\n{self.explanation}",
                                  color=discord.Color.green() if correct else discord.Color.orange())
            await interaction.response.edit_message(embed=embed, view=self)
        return callback

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class Fun(commands.Cog):
    """Lighthearted games, conversation starters, and random commands."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="8ball", aliases=["eightball"], help="Ask the magic 8-ball a question.")
    async def eightball(self, ctx, *, question: str):
        answers = ["It is certain.", "Without a doubt.", "Most likely.", "Outlook good.", "Signs point to yes.",
                   "Ask again later.", "Cannot predict that right now.", "Better not tell you.",
                   "Don't count on it.", "My sources say no.", "Very doubtful."]
        embed = discord.Embed(title="🎱 Magic 8-Ball", color=COLOR)
        embed.add_field(name="Question", value=question[:1024], inline=False)
        embed.add_field(name="Answer", value=random.choice(answers), inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="coinflip", aliases=["flip"], help="Flip a coin.")
    async def coinflip(self, ctx):
        await ctx.send(embed=discord.Embed(title="🪙 Coin Flip",
                      description=f"**{random.choice(['Heads', 'Tails'])}!**", color=COLOR))

    @commands.command(name="roll", help="Roll dice, e.g. ,roll 2d20.")
    async def roll(self, ctx, dice: str = "1d6"):
        match = re.fullmatch(r"(\d{1,2})[dD](\d{1,5})", dice.strip())
        if not match:
            return await ctx.send("Use dice notation like `,roll 1d6` or `,roll 2d20`.")
        count, sides = map(int, match.groups())
        if not 1 <= count <= 20 or not 2 <= sides <= 10000:
            return await ctx.send("You can roll 1–20 dice, with 2–10,000 sides each.")
        results = [random.randint(1, sides) for _ in range(count)]
        embed = discord.Embed(title="🎲 Dice Roll", color=COLOR)
        embed.add_field(name="Dice", value=f"`{count}d{sides}`", inline=True)
        embed.add_field(name="Results", value=", ".join(f"`{v}`" for v in results), inline=True)
        embed.add_field(name="Total", value=f"**{sum(results):,}**", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="choose", help="Choose randomly between options separated by |.")
    async def choose(self, ctx, *, options: str):
        choices = [x.strip() for x in options.split("|") if x.strip()]
        if not 2 <= len(choices) <= 20:
            return await ctx.send("Give me 2–20 choices. Example: `,choose pizza | tacos | pasta`.")
        if any(len(x) > 200 for x in choices):
            return await ctx.send("Each choice must be 200 characters or fewer.")
        await ctx.send(embed=discord.Embed(title="🤔 ONYX Chooses...",
                      description=f"**{random.choice(choices)}**", color=COLOR))

    @commands.command(name="rate", help="Give something a random ONYX rating.")
    async def rate(self, ctx, *, subject: str):
        if len(subject) > 180:
            return await ctx.send("Keep the subject under 180 characters.")
        score = random.randint(0, 100)
        comment = ("A bold choice. Room to grow." if score < 20 else
                   "A solid middle ground." if score < 40 else
                   "Pretty good! ONYX approves." if score < 60 else
                   "Excellent. That's a strong result." if score < 80 else
                   "Legendary status. Top tier.")
        await ctx.send(embed=discord.Embed(title="📊 ONYX Rating",
                      description=f"**{subject}**\n\n# {score}/100\n{comment}", color=COLOR))

    @commands.command(name="joke", help="Get a clean joke.")
    async def joke(self, ctx):
        question, answer = random.choice(JOKES)
        embed = discord.Embed(title="😂 ONYX Joke", description=f"{question}\n\n||{answer}||", color=COLOR)
        embed.set_footer(text="Tap the spoiler to reveal the punchline.")
        await ctx.send(embed=embed)

    @commands.command(name="fact", help="Get an interesting random fact.")
    async def fact(self, ctx):
        await ctx.send(embed=discord.Embed(title="🧠 Random Fact", description=random.choice(FACTS), color=COLOR))

    @commands.command(name="wouldyourather", aliases=["wyr"], help="Get a would-you-rather prompt.")
    async def wouldyourather(self, ctx):
        first, second = random.choice(WOULD_YOU_RATHER)
        await ctx.send(embed=discord.Embed(title="🤔 Would You Rather?",
                      description=f"🇦 **{first}**\n\n**OR**\n\n🇧 **{second}**", color=COLOR))

    @commands.command(name="trivia", help="Start an interactive multiple-choice trivia question.")
    async def trivia(self, ctx):
        question, options, answer, explanation = random.choice(TRIVIA)
        embed = discord.Embed(title="🧠 ONYX Trivia", description=question, color=COLOR)
        embed.set_footer(text="Choose an answer below. You have 90 seconds.")
        await ctx.send(embed=embed, view=TriviaView(options, answer, explanation, ctx.author.id))

    @commands.command(name="rps", aliases=["rockpaperscissors"], help="Play rock-paper-scissors against ONYX.")
    async def rps(self, ctx, choice: str):
        choice = choice.casefold()
        choices = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
        if choice not in choices:
            return await ctx.send("Choose `rock`, `paper`, or `scissors`.")
        bot_choice = random.choice(list(choices))
        if choice == bot_choice:
            result = "It's a tie!"
        elif (choice, bot_choice) in {("rock", "scissors"), ("paper", "rock"), ("scissors", "paper")}:
            result = "You win!"
        else:
            result = "ONYX wins this round!"
        await ctx.send(embed=discord.Embed(title="🪨 Rock Paper Scissors",
                      description=f"You: {choices[choice]} **{choice.title()}**\nONYX: {choices[bot_choice]} **{bot_choice.title()}**\n\n**{result}**", color=COLOR))

    @commands.command(name="teamup", help="Generate a silly teamwork score for two members.")
    async def teamup(self, ctx, first: discord.Member, second: discord.Member = None):
        second = second or ctx.author
        score = random.randint(0, 100)
        names = "You" if first.id == second.id else f"{first.mention} + {second.mention}"
        line = random.choice(["A legendary duo in the making.", "Could use a planning meeting.",
                              "Perfectly balanced teamwork.", "Ready to take on a group project."])
        await ctx.send(embed=discord.Embed(title="🤝 ONYX Team-Up Meter",
                      description=f"{names}\n\n# {score}% teamwork\n{line}", color=COLOR),
                      allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="ship", help="Get a silly, platonic duo score for two members.")
    async def ship(self, ctx, first: discord.Member, second: discord.Member = None):
        second = second or ctx.author
        score = random.randint(0, 100)
        labels = ["Chaotic teammates", "A dependable duo", "The server's dream team",
                  "Two minds, one shared braincell", "Legendary co-op energy"]
        embed = discord.Embed(title="🚀 ONYX Duo Meter",
            description=f"{first.display_name} + {second.display_name}\n\n# {score}% duo energy\n**{random.choice(labels)}**",
            color=COLOR)
        embed.set_footer(text="Just a random friendship/teamwork score — not a real compatibility test.")
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="compliment", help="Send a friendly, random compliment.")
    async def compliment(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        lines = ["You bring great energy to the room.", "Your creativity deserves more credit.",
                 "You make teamwork better.", "Your sense of humor is a server resource.",
                 "You have a talent for making people feel included.",
                 "You make this community more interesting.",
                 "You have a great way of looking at problems."]
        await ctx.send(f"✨ {member.mention}, {random.choice(lines)}",
                       allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="roast", help="Give a member a harmless, playful roast.")
    async def roast(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        lines = ["Your Wi-Fi signal has more direction than your plans.",
                 "You bring loading-screen energy to every group project.",
                 "Your browser tabs have formed their own government.",
                 "You'd lose a game of hide-and-seek in an empty room.",
                 "Your alarm clock has trust issues.",
                 "You're the reason instructions come with pictures.",
                 "Your keyboard needs a vacation from those typos."]
        await ctx.send(f"🔥 {member.mention}, {random.choice(lines)}",
                       allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="meme", help="Generate a text meme using a topic.")
    async def meme(self, ctx, *, topic: str = "Monday morning"):
        if len(topic) > 120:
            return await ctx.send("Keep the meme topic under 120 characters.")
        template = random.choice(MEME_FORMATS)
        lines = [part.format(topic=topic) for part in template[1:]]
        embed = discord.Embed(title=f"😂 Meme Generator • {template[0]}",
                              description="\n\n".join(lines), color=COLOR)
        embed.set_footer(text="Text meme generated by ONYX.")
        await ctx.send(embed=embed)

    @commands.command(name="fortune", help="Get a random fortune.")
    async def fortune(self, ctx):
        fortunes = ["A new opportunity may arrive when you least expect it.",
                    "Your next great idea might start as a small question.",
                    "A little patience can make a big difference.",
                    "The best part of the day may still be ahead.",
                    "A conversation could lead to something interesting.",
                    "Your future self will appreciate today's effort."]
        await ctx.send(embed=discord.Embed(title="🔮 ONYX Fortune",
                      description=random.choice(fortunes), color=COLOR))

    @commands.command(name="number", aliases=["randomnumber"], help="Pick a random number: ,number 1 100.")
    async def number(self, ctx, minimum: int = 1, maximum: int = 100):
        if minimum > maximum:
            return await ctx.send("The minimum must be less than or equal to the maximum.")
        if maximum - minimum > 1_000_000_000:
            return await ctx.send("Please choose a smaller range.")
        await ctx.send(f"🎯 Your number: **{random.randint(minimum, maximum):,}**")

    @commands.command(name="riddle", help="Get a riddle. The answer is hidden in a spoiler.")
    async def riddle(self, ctx):
        question, answer = random.choice(RIDDLES)
        await ctx.send(embed=discord.Embed(title="🧩 ONYX Riddle",
                      description=f"{question}\n\n||{answer}||", color=COLOR))

    @commands.command(name="truth", help="Get a friendly conversation truth prompt.")
    async def truth(self, ctx):
        await ctx.send(embed=discord.Embed(title="💬 Truth Prompt", description=random.choice(TRUTHS), color=COLOR))

    @commands.command(name="dare", help="Get a harmless, friendly dare.")
    async def dare(self, ctx):
        await ctx.send(embed=discord.Embed(title="🎯 Friendly Dare", description=random.choice(SAFE_DARES), color=COLOR))

    @commands.command(name="emojify", help="Turn text into emoji-style letters.")
    async def emojify(self, ctx, *, text: str):
        if len(text) > 80:
            return await ctx.send("Keep the text under 80 characters.")
        mapping = {letter: f":regional_indicator_{letter}:" for letter in "abcdefghijklmnopqrstuvwxyz"}
        mapping.update({"0": ":zero:", "1": ":one:", "2": ":two:", "3": ":three:", "4": ":four:",
                        "5": ":five:", "6": ":six:", "7": ":seven:", "8": ":eight:", "9": ":nine:",
                        "?": ":grey_question:", "!": ":grey_exclamation:", " ": "   "})
        result = " ".join(mapping.get(char.lower(), char) for char in text)
        if len(result) > 1900:
            return await ctx.send("That text becomes too long when converted.")
        await ctx.send(result, allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="mock", help="Convert text into alternating-case meme text.")
    async def mock(self, ctx, *, text: str):
        if len(text) > 500:
            return await ctx.send("Keep the text under 500 characters.")
        upper, result = False, []
        for char in text:
            if char.isalpha():
                result.append(char.upper() if upper else char.lower())
                upper = not upper
            else:
                result.append(char)
        await ctx.send("".join(result), allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="reverse", help="Reverse a piece of text.")
    async def reverse(self, ctx, *, text: str):
        if len(text) > 1500:
            return await ctx.send("Keep the text under 1,500 characters.")
        await ctx.send(f"```{text[::-1]}```", allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="clap", help="Put 👏 between 👏 every 👏 word.")
    async def clap(self, ctx, *, text: str):
        if len(text) > 400:
            return await ctx.send("Keep the text under 400 characters.")
        await ctx.send(" 👏 ".join(text.split()), allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="wyrvote", help="Post a two-option Would You Rather vote.")
    async def wyrvote(self, ctx, *, prompt: str):
        parts = [part.strip() for part in prompt.split("|", 1)]
        if len(parts) != 2 or not all(parts):
            return await ctx.send("Use `,wyrvote Option A | Option B`.")
        if any(len(part) > 150 for part in parts):
            return await ctx.send("Keep each option under 150 characters.")
        embed = discord.Embed(title="🤔 Would You Rather?",
                              description=f"🇦 **{parts[0]}**\n\n🇧 **{parts[1]}**", color=COLOR)
        message = await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        await message.add_reaction("🇦")
        await message.add_reaction("🇧")

    @commands.command(name="pick", help="Pick a random member currently in the server.")
    async def pick(self, ctx):
        members = [member for member in ctx.guild.members if not member.bot]
        if not members:
            return await ctx.send("I couldn't find any members to pick.")
        chosen = random.choice(members)
        await ctx.send(f"🎉 ONYX picked {chosen.mention}!",
                       allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="quote", help="Create a quote card from a replied-to message.")
    @commands.guild_only()
    async def quote(self, ctx):
        reference = ctx.message.reference
        if reference is None or reference.message_id is None:
            return await ctx.send("Reply directly to the message you want to quote, then type `,quote`.")
        try:
            quoted = reference.resolved
            if quoted is None:
                quoted = await ctx.channel.fetch_message(reference.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return await ctx.send("I couldn't access that message. Check that I can read its channel.")
        content = (quoted.content or "").strip()
        if not content and not quoted.attachments:
            return await ctx.send("That message doesn't contain text or an attachment to quote.")

        try:
            avatar_bytes = await quoted.author.display_avatar.with_size(512).read()
            from PIL import Image, ImageDraw, ImageFont, ImageOps

            canvas = Image.new("RGB", (1200, 600), (5, 8, 14))
            panel = Image.new("RGBA", (1120, 520), (0, 0, 0, 255))
            avatar = ImageOps.fit(Image.open(BytesIO(avatar_bytes)).convert("RGB"),
                                  (500, 520), centering=(0.5, 0.5))
            panel.paste(avatar, (0, 0))
            shade = Image.new("RGBA", (500, 520), (0, 0, 0, 0))
            shade_pixels = shade.load()
            for px in range(500):
                alpha = int(225 * (px / 499) ** 1.7)
                for py in range(520):
                    shade_pixels[px, py] = (0, 0, 0, alpha)
            panel.alpha_composite(shade, (0, 0))
            draw = ImageDraw.Draw(panel)
            try:
                quote_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 35)
                name_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf", 28)
                meta_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
            except OSError:
                quote_font = name_font = meta_font = ImageFont.load_default()

            text = content[:850] if content else "Shared an attachment"
            if len(content) > 850:
                text += "…"
            if quoted.attachments:
                text += "\n\n[Attachment included]"
            lines, current = [], ""
            for word in text.split():
                trial = f"{current} {word}".strip()
                if draw.textlength(trial, font=quote_font) <= 545:
                    current = trial
                else:
                    if current:
                        lines.append(current)
                    current = word
            if current:
                lines.append(current)
            if len(lines) > 7:
                lines = lines[:7]
                lines[-1] = lines[-1].rstrip(".,;:") + "…"

            x, y = 565, 105 if len(lines) <= 5 else 65
            draw.text((x, y - 5), "“", font=quote_font, fill=(225, 230, 238))
            for line in lines:
                draw.text((x + 22, y), line, font=quote_font, fill=(248, 248, 250))
                y += 49
            y += 22
            draw.text((x + 22, y), f"— {quoted.author.display_name[:32]}",
                      font=name_font, fill=(190, 198, 211))
            y += 52
            timestamp = quoted.created_at.strftime("%b %d, %Y • %I:%M %p").replace(" 0", " ")
            draw.text((x + 22, y), f"ONYX  •  {timestamp}",
                      font=meta_font, fill=(110, 120, 138))
            result = canvas.convert("RGBA")
            result.alpha_composite(panel, (40, 40))
            output = BytesIO()
            result.convert("RGB").save(output, format="PNG", optimize=True)
            output.seek(0)
            await ctx.send(file=discord.File(output, filename="onyx-quote.png"))
        except ImportError:
            await ctx.send("Pillow is missing. Add `Pillow>=10.0.0` to requirements.txt and redeploy.")
        except (discord.HTTPException, OSError, ValueError):
            await ctx.send("I couldn't create that quote card. Try again with a shorter message.")


async def setup(bot):
    await bot.add_cog(Fun(bot))
