"""Chat de la PWA : une demande à la fois, exécutée dans un thread, avec confirmations N2 par l'appareil demandeur.

- Le serveur crée la demande de confirmation (id aléatoire, aperçu calculé ICI, jamais le texte du LLM) ; elle sert une
  seule fois, expire après 60 s, et seul l'appareil qui a posé la question peut l'approuver. Approuver = `True` strict.
- N3 : l'appareil doit signer le défi de CETTE demande avec sa clé d'accès (WebAuthn) ; sans clé, ou sans WebAuthn, refusé.
- Le journal garde la longueur et le SHA-256 de la demande, jamais son texte (l'audit est en ajout seul, non purgeable).
"""
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass, field

import jarvis.tools.home  # noqa: F401  (enregistre les outils domotique)
import jarvis.tools.mail  # noqa: F401  (enregistre le connecteur mail)
import jarvis.tools.pc  # noqa: F401  (enregistre les outils PC)
import jarvis.tools.social  # noqa: F401  (enregistre le planning lol-clipper)
from jarvis.core.audit import Audit
from jarvis.core import levels
from jarvis.core.levels import effective
from jarvis.core.llm import LLMUnavailable, ask
from jarvis.core.permissions import Refused, execute
from jarvis.core.router import Router
from jarvis.core.push import Push
from jarvis.core.tools import REGISTRY, Level, Tool
from jarvis.core.webauthn import Passkeys

_now = time.monotonic  # remplacé dans les tests
CONFIRM_TTL_S = 60
RENOTIFY_S = 15  # F3 : le push de la création arrive pendant que la PWA est encore visible (rien affiché) ; un second suit
JOB_MAX_S = 300  # au-delà, les confirmations suivantes d'un même job sont refusées d'office (constat 4)
JOBS_MAX = 20
ANSWER_MAX = 4000
PREVIEW_MAX = 300  # un aperçu long cacherait la cible réelle ; la coupe est explicite (…)
TEXT_MAX = 1000


@dataclass
class Pending:
    id: str
    tool: str
    preview: str
    deadline: float
    level: int = 2
    webauthn: dict | None = None  # N3 : options de navigator.credentials.get, défi lié à cette demande
    verified: bool = False
    event: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


@dataclass
class Job:
    id: str
    device: int
    done: bool = False
    answer: str | None = None
    pending: Pending | None = None
    deadline: float = field(default_factory=lambda: _now() + JOB_MAX_S)
    strong: bool = False  # posé par _confirm quand l'assertion N3 est vérifiée, consommé une fois par strong_auth
    aborted: bool = False  # un refus ou une expiration : le LLM ne peut pas harceler de nouvelles confirmations


class Chat:
    def __init__(self, audit: Audit, passkeys: Passkeys | None = None, push: Push | None = None):
        self.audit = audit
        self.push = push  # notification générique quand une confirmation attend (l'appli peut être en arrière-plan)
        self.passkeys = passkeys
        levels.load(audit)  # le serveur applique toujours les niveaux réglés par le propriétaire
        self.busy = threading.Lock()  # un seul appel à la fois (un seul LLM local) : le reste reçoit « occupé »
        self.lock = threading.Lock()
        self.jobs: dict[str, Job] = {}
        self.router = Router()

    def start(self, device: int, text: str) -> str | None:
        """Identifiant de la demande, ou None si une autre est en cours."""
        if not 0 < len(text) <= TEXT_MAX:
            raise ValueError("texte invalide")
        if not self.busy.acquire(blocking=False):
            return None
        try:
            self.audit.log(f"pwa:{device}", "chat", {"len": len(text), "sha256": hashlib.sha256(text.encode()).hexdigest()},
                           None, "auto", None)
            job = Job(secrets.token_urlsafe(12), device)
            with self.lock:
                while len(self.jobs) >= JOBS_MAX:  # les plus anciennes sont terminées : une seule tourne à la fois
                    del self.jobs[next(iter(self.jobs))]
                self.jobs[job.id] = job
            threading.Thread(target=self._run, args=(job, text), daemon=True).start()
        except BaseException:
            self.busy.release()
            raise
        return job.id

    def status(self, device: int, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or job.device != device:  # l'appareil d'un autre ne voit rien
                return None
            p = job.pending
            pending = None if p is None else {"id": p.id, "tool": p.tool, "preview": p.preview,
                                              "level": p.level, "webauthn": p.webauthn,
                                              "expires_in": max(0, round(p.deadline - _now()))}
            return {"status": "done" if job.done else "running", "answer": job.answer, "pending": pending}

    def approve(self, device: int, confirmation_id: str, approve: bool, assertion: dict | None = None) -> bool:
        """Vrai si la demande existait, appartenait à cet appareil et n'avait ni expiré ni déjà servi.

        N3 : sans assertion valide pour CETTE demande, « oui » vaut refus (et interrompt le job).
        """
        with self.lock:
            for job in self.jobs.values():
                p = job.pending
                if p and job.device == device and secrets.compare_digest(p.id, confirmation_id):
                    if p.event.is_set() or _now() > p.deadline:
                        return False
                    p.approved = approve is True
                    if p.approved and p.level >= Level.N3:
                        p.verified = p.approved = (assertion is not None and self.passkeys is not None
                                                   and self.passkeys.verify(device, f"confirm:{p.id}", assertion))
                        if not p.verified:
                            self.audit.log(f"pwa:{device}", "webauthn", {"tool": p.tool}, 3, "refusé", "assertion absente ou invalide")
                    p.event.set()
                    return True
        return False

    def _confirm(self, job: Job, tool: Tool, args: dict) -> bool:
        level = effective(tool)
        job.strong = False
        if level >= Level.N3 and not (self.passkeys and self.passkeys.has(job.device)):  # inutile de demander
            self.audit.log(f"pwa:{job.device}", "confirm", {"tool": tool.name}, int(level), "refusé",
                           "N3 refusé : aucune clé d'accès pour cet appareil")
            return False
        if job.aborted or _now() > job.deadline:
            self.audit.log(f"pwa:{job.device}", "confirm", {"tool": tool.name}, int(level), "refusé",
                           "job interrompu après un refus ou trop long")
            return False
        preview = tool.preview(args)
        if len(preview) > PREVIEW_MAX:
            preview = preview[:PREVIEW_MAX] + "… (aperçu tronqué : refuse si tu ne reconnais pas la cible)"
        p = Pending(secrets.token_urlsafe(16), tool.name, preview, _now() + CONFIRM_TTL_S, int(level))
        if level >= Level.N3:
            p.webauthn = self.passkeys.request_options(job.device, f"confirm:{p.id}")
        with self.lock:
            job.pending = p
        if self.push:
            self.push.notify(job.device, self.audit)
        first = min(RENOTIFY_S, CONFIRM_TTL_S)
        answered = p.event.wait(first)
        if not answered and self.push and CONFIRM_TTL_S > first:  # l'utilisateur a quitté l'appli depuis : on le prévient encore une fois
            self.push.notify(job.device, self.audit)
            answered = p.event.wait(CONFIRM_TTL_S - first)
        with self.lock:
            job.pending = None
        if not answered:
            self.audit.log(f"pwa:{job.device}", "confirm", {"tool": tool.name}, None, "refusé", "expirée")
        ok = answered and p.approved is True
        job.strong = ok and p.verified
        job.aborted = job.aborted or not ok
        return ok

    def _strong(self, job: Job) -> bool:
        ok, job.strong = job.strong, False  # une assertion ne sert qu'à la confirmation qui vient de la vérifier
        return ok

    def _run(self, job: Job, text: str) -> None:
        source = f"pwa:{job.device}"
        confirm = lambda tool, args: self._confirm(job, tool, args)  # noqa: E731
        strong = lambda tool, args: self._strong(job)  # noqa: E731
        answer = "Erreur interne"
        try:
            routed = self.router.route(text)
            if routed is None:
                answer = ask(text, audit=self.audit, confirm=confirm, strong_auth=strong, source=f"{source}/llm")
            else:
                name, args = routed
                result = execute(name, args, source=source, audit=self.audit, confirm=confirm, strong_auth=strong)
                # Outil privé (presse-papiers, capture, script) : le résultat n'est jamais renvoyé, comme au journal.
                answer = f"<{type(result).__name__}, {len(str(result))} car.>" if REGISTRY[name].private else str(result)
        except Refused:
            answer = "Action refusée."
        except LLMUnavailable as e:
            answer = str(e)
        except ValueError as e:
            answer = str(e)
        except BaseException as e:  # pas de trace : elle pourrait contenir des arguments ou des noms de fichiers
            answer = f"Erreur interne : {type(e).__name__}"
        finally:  # quoi qu'il arrive, la demande se termine et le verrou « occupé » est rendu
            with self.lock:
                job.answer, job.done = answer[:ANSWER_MAX], True
            self.busy.release()
