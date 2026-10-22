"""Onglets Bien-être et Réseaux lus sur le PC pour le Core du mini-PC, via l'agent (N0, jamais proposés au LLM).

Les données restent celles des projets du PC (bien-etre-pc, lol-clipper) : le Core les relaie telles que
`core.bienetre.snapshot` et `core.social` les filtrent déjà.
"""
from jarvis.core import bienetre, social
from jarvis.tools.pc.drivers import status as drivers_status
from jarvis.core.tools import Level, tool
from jarvis.core.youtube_stats import YouTubeStats

_youtube = YouTubeStats()  # jeton de lol-clipper lu sur le PC, jamais transmis au Core


@tool("pc_bienetre", "Bilan de santé du PC (onglet Bien-être).", Level.N0, owner_only=True)
def pc_bienetre() -> dict:
    started = bienetre.refresh_if_stale()  # `started` : le Core journalise le lancement (ici, `on_run` n'est pas branché)
    return {**bienetre.with_drivers(bienetre.snapshot(), drivers_status()), "started": started}


@tool("pc_social", "Clips publiés et programmés, compteurs YouTube (onglet Réseaux).", Level.N0, owner_only=True)
def pc_social() -> dict:
    return social.with_youtube(social.snapshot(), _youtube)
