"""Notifications utilisateur — bureau et/ou e-mail.

Pluggable : chaque notifier est isolé, un échec ne casse pas les autres.
Marque les alertes comme `notifie=True` une fois envoyées (au moins par un canal).
"""

from __future__ import annotations

import logging
import smtplib
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from core.settings import get_settings
from data.database import session_scope
from data.models import Alerte
from data.repositories import alertes_a_notifier

logger = logging.getLogger(__name__)


class Notifier(ABC):
    name: str = "base"
    enabled: bool = False

    @abstractmethod
    def notify(self, titre: str, message: str) -> bool:
        """Renvoie True en cas de succès."""


class DesktopNotifier(Notifier):
    name = "desktop"

    def __init__(self) -> None:
        self.enabled = get_settings().notify_desktop_enabled

    def notify(self, titre: str, message: str) -> bool:
        if not self.enabled:
            return False
        try:
            from plyer import notification  # type: ignore
            notification.notify(
                title=titre[:64],
                message=message[:240],
                app_name="invest-immo-scrapper",
                timeout=10,
            )
            return True
        except Exception as exc:
            logger.warning("Notif bureau échouée (%s) : %s", type(exc).__name__, exc)
            return False


class EmailNotifier(Notifier):
    name = "email"

    def __init__(self) -> None:
        s = get_settings()
        self.enabled = bool(
            s.notify_email_enabled and s.smtp_host and s.smtp_to and s.smtp_from
        )
        self.s = s

    def notify(self, titre: str, message: str) -> bool:
        if not self.enabled:
            return False
        try:
            msg = MIMEMultipart()
            msg["From"] = self.s.smtp_from
            msg["To"] = self.s.smtp_to
            msg["Subject"] = f"[invest-immo] {titre}"
            msg.attach(MIMEText(message, "plain", "utf-8"))
            with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=15) as srv:
                srv.starttls()
                if self.s.smtp_user:
                    srv.login(self.s.smtp_user, self.s.smtp_password)
                srv.send_message(msg)
            return True
        except Exception as exc:
            logger.warning("Notif e-mail échouée : %s", exc)
            return False


def all_notifiers() -> list[Notifier]:
    return [DesktopNotifier(), EmailNotifier()]


def envoyer_alertes_en_attente() -> dict:
    """Envoie les alertes non encore notifiées via tous les notifiers activés."""
    notifiers = [n for n in all_notifiers() if n.enabled]
    if not notifiers:
        return {"envoyees": 0, "raison": "aucun notifier activé"}

    envoyees = 0
    with session_scope() as s:
        for a in alertes_a_notifier(s):
            success_any = False
            for n in notifiers:
                try:
                    if n.notify(a.titre, a.message):
                        success_any = True
                except Exception:
                    logger.exception("Notifier %s a planté", n.name)
            if success_any:
                a.notifie = True
                envoyees += 1
    return {"envoyees": envoyees, "notifiers": [n.name for n in notifiers]}
