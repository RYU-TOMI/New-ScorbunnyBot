import discord
import asyncio

class SearchView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)
        self.value = None

    async def _handle(self, interaction: discord.Interaction, value: int):
        self.value = value
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="1️⃣", style=discord.ButtonStyle.primary)
    async def button_one(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle(interaction, 1)

    @discord.ui.button(label="2️⃣", style=discord.ButtonStyle.primary)
    async def button_two(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle(interaction, 2)

    @discord.ui.button(label="3️⃣", style=discord.ButtonStyle.primary)
    async def button_three(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle(interaction, 3)

    @discord.ui.button(label="4️⃣", style=discord.ButtonStyle.primary)
    async def button_four(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle(interaction, 4)

    @discord.ui.button(label="5️⃣", style=discord.ButtonStyle.primary)
    async def button_five(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle(interaction, 5)

    @discord.ui.button(label="취소❌", style=discord.ButtonStyle.danger, row=1)
    async def button_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = None
        await interaction.response.defer()
        self.stop()

    async def on_timeout(self):
        self.value = None
        self.stop()