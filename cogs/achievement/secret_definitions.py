"""Private owner-facing definitions. Do not display this module to members."""
SECRET_ACHIEVEMENTS={
"the_chosen_one":dict(name="The Chosen One",description="Trigger a very rare random discovery.",hint="A rare chance event.",trigger="random_rare",chance=0.0005,title="The Chosen One",icon="🌠"),
"ghost":dict(name="Ghost",description="Send a message in a server with 10 or fewer members.",hint="Be active when the server is quiet.",trigger="quiet_message",chance=1,title="Ghost",icon="👻"),
"deja_vu":dict(name="Déjà Vu",description="Use the same command five times consecutively.",hint="Repetition can be memorable.",trigger="repeat_command",chance=1,title="Déjà Vu",icon="🔁"),
"midnight_club":dict(name="Midnight Club",description="Use an ONYX command between 00:00 and 04:00 UTC.",hint="The clock matters.",trigger="midnight",chance=1,title="Night Walker",icon="🌙"),
"the_collector":dict(name="The Collector",description="Use commands from five different ONYX cogs.",hint="Explore different parts of ONYX.",trigger="command_categories",chance=1,title="The Collector",icon="🗃️"),
"lucky_break":dict(name="Lucky Break",description="Trigger a rare random discovery.",hint="Sometimes chance is on your side.",trigger="random_break",chance=0.002,title="Lucky",icon="🍀"),
"behind_the_curtain":dict(name="Behind the Curtain",description="Use the hidden ,secrets command.",hint="Look behind the usual menus.",trigger="secrets_command",chance=1,title="Insider",icon="🎭"),
"the_long_game":dict(name="The Long Game",description="Return and use ONYX after 30 days without activity.",hint="Absence makes the return count.",trigger="return_after_absence",chance=1,title="The Long Game",icon="⏳"),
"unpredictable":dict(name="Unpredictable",description="Complete a randomly assigned daily challenge.",hint="A daily surprise may appear.",trigger="daily_challenge",chance=1,title="Wildcard",icon="🎲"),
"one_in_a_million":dict(name="One in a Million",description="Trigger an exceptionally rare discovery.",hint="The odds are tiny.",trigger="ultra_rare",chance=0.00001,title="One in a Million",icon="💎"),
}
