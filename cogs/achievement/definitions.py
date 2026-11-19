from cogs.achievements.categories.arcade import ARCADE_ACHIEVEMENTS
from cogs.achievements.categories.community import COMMUNITY_ACHIEVEMENTS
from cogs.achievements.categories.exploration import EXPLORATION_ACHIEVEMENTS
from cogs.achievements.categories.progression import PROGRESSION_ACHIEVEMENTS
from cogs.achievements.categories.social import SOCIAL_ACHIEVEMENTS

CATEGORIES={
"arcade":("Arcade",ARCADE_ACHIEVEMENTS),
"community":("Community",COMMUNITY_ACHIEVEMENTS),
"exploration":("Exploration",EXPLORATION_ACHIEVEMENTS),
"progression":("Progression",PROGRESSION_ACHIEVEMENTS),
"social":("Social & Fun",SOCIAL_ACHIEVEMENTS),
}
ACHIEVEMENTS={aid:{**d,"category":key} for key,(_,items) in CATEGORIES.items() for aid,d in items.items()}
