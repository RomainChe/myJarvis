"""Chat de la PWA : une demande à la fois, exécutée dans un thread, avec confirmations N2 par l'appareil demandeur.

- Le serveur crée la demande de confirmation (id aléatoire, aperçu calculé ICI, jamais le texte du LLM) ; elle sert une
  seule fois, expire après 60 s, et seul l'appareil qui a posé la question peut l'approuver. Approuver = `True` strict.
- N3 : toujours refusé tant que WebAuthn n'existe pas (étape 5), comme la CLI.
- Le journal garde la longueur et le SHA-256 de la demande, jamais son texte (l'audit est en ajout seul, non purgeable).
"""
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass, field

import jarvis.tools.home  # noqa: F401  (enregistre les outils domotique)
import jarvis.tools.pc  # noqa: F401  (enregistre les outils PC)
from jarvis.core.audit import Audit
from jarvis.core.llm import LLMUnavailable, ask
from jarvis.core.permissions import Refused, execute
from jarvis.core.router import Router
from jarvis.core.tools import Tool

_now = time.monotonic  # remplacé dans les tests
CONFIRM_TTL_S = 60
JOBS_MAX = 20
ANSWER_MAX = 4000
TEXT_MAX = 1000


@dataclass
class Pending:
    id: str
    tool: str
    preview: str
    deadline: float
    event: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


@dataclass
class Job:
    id: str
    device: int
    done: bool = False
    answer: str | None = None
    pending: Pending | None = None


class Chat:
    def __init__(self, audit: Audit):
        self.audit = audit
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
                                              "expires_in": max(0, round(p.deadline - _now()))}
            return {"status": "done" if job.done else "running", "answer": job.answer, "pending": pending}

    def approve(self, device: int, confirmation_id: str, approve: bool) -> bool:
        """Vrai si la demande existait, appartenait à cet appareil et n'avait ni expiré ni déjà servi."""
        with self.lock:
            for job in self.jobs.values():
                p = job.pending
                if p and job.device == device and secrets.compare_digest(p.id, confirmation_id):
                    if p.event.is_set() or _now() > p.deadline:
                        return False
                    p.approved = approve is True
                    p.event.set()
                    return True
        return False

    def _confirm(self, job: Job, tool: Tool, args: dict) -> bool:
        p = Pending(secrets.token_urlsafe(16), tool.name, tool.preview(args), _now() + CONFIRM_TTL_S)
        with self.lock:
            job.pending = p
        answered = p.event.wait(CONFIRM_TTL_S)
        with self.lock:
            job.pending = None
        if not answered:
            self.audit.log(f"pwa:{job.device}", "confirm", {"tool": tool.name}, None, "refusé", "expirée")
        return answered and p.approved is True

    def _run(self, job: Job, text: str) -> None:
        source = f"pwa:{job.device}"
        confirm = lambda tool, args: self._confirm(job, tool, args)  # noqa: E731
        no_strong = lambda tool, args: False  # noqa: E731  (N3 : WebAuthn en étape 5)
        answer = "Erreur interne"
        try:
            routed = self.router.route(text)
            if routed is None:
                answer = ask(text, audit=self.audit, confirm=confirm, strong_auth=no_strong, source=f"{source}/llm")
            else:
                name, args = routed
                answer = str(execute(name, args, source=source, audit=self.audit, confirm=confirm,
                                     strong_auth=no_strong))
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
