"""Scanner d'injection (français + anglais) : un SIGNAL pour le journal, jamais un contrôle.

La garde reste `taint` (llm.py) : un contenu qui passe le scanner n'est pas pour autant sûr, un contenu signalé
n'est pas bloqué. Ne sert qu'à rendre une tentative visible dans le journal.
"""
import re
import unicodedata

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"))
_VERB = r"(?:appelle|appelez|execute|executez|lance|lancez|utilise|utilisez|call|run|invoke|use)"

# (nom du motif, regex sur du texte sans accents, en minuscules)
PATTERNS = [
    ("ignore_consignes", r"\b(?:ignore|ignorez|oublie|oubliez|desobeis|disregard|forget|ignore all|ignore any)\b.{0,40}"
                         r"\b(?:consignes?|instructions?|regles?|directives?|prompt|rules|guidelines)\b"),
    ("ignore_consignes", r"\bignore (?:all |any )?(?:previous|prior|above|earlier)\b"),
    ("nouvelle_consigne", r"\b(?:nouvelles? (?:consignes?|instructions?)|new instructions?|consigne cachee|"
                          r"instruction cachee|hidden instruction)\b"),
    ("a_l_assistant", r"\b(?:note|message|consigne|instruction)s? (?:a|au|pour) (?:l'|le |les )?(?:assistant|modele|llm|ia|jarvis)\b"),
    ("a_l_assistant", r"\b(?:assistant|jarvis|ai|llm)\s*,?\s*(?:tu dois|you must|you should|please|execute|appelle|lance)\b"),
    ("changement_role", r"\b(?:tu es maintenant|vous etes maintenant|you are now|tu dois maintenant|desormais tu|"
                        r"mode (?:maintenance|developpeur|admin|debug|dieu)|(?:developer|maintenance|admin|debug|god) mode|"
                        r"system override|override)\b"),
    ("fausse_autorite", r"\b(?:(?:le |ton |ce )?proprietaire|owner|administrateur|admin)\b.{0,40}"
                        r"\b(?:autorise|a valide|a deja valide|demande|authorized?|approved?|valide)\b"),
    ("sans_confirmation", r"\b(?:sans (?:demander|confirmation|attendre)|pas de confirmation|ne demande pas|"
                          r"do not ask|don't ask|without (?:asking|confirmation)|no confirmation)\b"),
    ("faux_role", r"(?:^|\n)\s*[\[(<]?(?:system|systeme|assistant|developer|developpeur|\[instruction\]|important|urgent)"
                  r"[\])>]?\s*:"),
    ("ignore_consignes", r"\b(?:oublie|oubliez|ignore|ignorez)\b.{0,15}\b(?:tout|ce qui precede)\b"),
    ("fausse_autorite", r"\b(?:ordre|consigne|message|instruction|note) (?:du |de la |de l')?"
                        r"(?:systeme|developpeur|proprietaire|administrateur)\b|\b(?:action requise|tres important)\s*:"),
    ("ordre_pc", r"\b(?:verrouille la session|eteins le pc|eteins l'ecran|supprime (?:tous|le dossier|les fichiers)|"
                 r"ferme toutes les appl\w*|termine le processus|lis (?:mes|le) (?:mails|presse-papiers)|"
                 r"mets le volume|fais une capture)\b"),
    ("nom_outil", r"(?<![\w.])(?:mail_recent|lock_session|screen_off|power_cancel|delete_file|move_file|kill_process|"
                  r"run_script|clipboard_read|clipboard_write|claude_code|set_volume|media_control|open_app|close_app|"
                  r"tv_\w+|scene_\w+)(?![\w.])"),
    ("balise",r"<\s*/?\s*data\b|<\|im_(?:start|end)\|>|\[/?inst\]|\[/?system\]|\[instruction\]"),
    ("ordre_outil", rf"\b{_VERB}\b\s+(?:l'outil |l'|the tool |tool |la |le )?(?:power|delete_file|move_file|kill_process|"
                    rf"run_script|clipboard_read|clipboard_write|screenshot|mail_recent|lock_session|screen_off|"
                    rf"power_cancel|claude_code|open_app|close_app|set_volume|mute|media_control|tv_\w+|scene_\w+)\b"),
    ("ordre_outil", r"\b(?:power|delete_file|kill_process|run_script|clipboard_read|clipboard_write|claude_code)\b"
                    r".{0,20}\b(?:shutdown|restart|avec|with|pid|action)\b"),
]
_COMPILED = [(n, re.compile(p)) for n, p in PATTERNS]


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).translate(_ZERO_WIDTH)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower().replace("’", "'")
    return re.sub(r"[ \t]+", " ", text)


def scan(text) -> list[str]:
    """Noms (sans doublon, ordre stable) des motifs d'injection trouvés dans `text` ; liste vide = rien vu."""
    norm = _norm(text)
    return list(dict.fromkeys(n for n, rx in _COMPILED if rx.search(norm)))
