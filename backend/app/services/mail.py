import logging

from sqlalchemy.orm import Session

from ..models import MailLog

log = logging.getLogger("brightloop.mail")


def send_mail(db: Session, to: str, subject: str, body: str) -> None:
    """Captured, not delivered: the message lands in mail_log and the server log. Swap this one
    function for an SMTP or provider call to go live."""
    db.add(MailLog(to=to, subject=subject, body=body))
    log.info("MAIL to=%s subject=%s\n%s", to, subject, body)
