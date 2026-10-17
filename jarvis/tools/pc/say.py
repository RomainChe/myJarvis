"""say (N1) : lit un texte à voix haute sur le PC (Piper, sortie JARVIS_AUDIO_OUT). Demandé par le Core pour les rappels parlés."""
from jarvis.core.tools import Level, tool

SAY_MAX = 500
_speaker = None


def _get_speaker():
    global _speaker
    if _speaker is None:
        from jarvis.core.tts import Speaker
        _speaker = Speaker()
    return _speaker


@tool("say", "Lit un court texte à voix haute sur le PC (rappels, minuteurs).", Level.N1, hidden=("text",), taint_blocked=True, text=str)
def say(text: str) -> dict:
    if not text.strip():
        raise ValueError("texte vide")
    sp = _get_speaker()
    if sp.is_speaking():
        return {"say": "occupé"}
    sp.say(text[:SAY_MAX], block=False)
    return {"say": "ok"}
