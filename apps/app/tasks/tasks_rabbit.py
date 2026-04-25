from asyncio.log import logger
from typing import Optional, List
from pathlib import Path
from django.contrib.auth import get_user_model

from apps.web.mail_send import MailSend
from apps.celery import celery_rabbit

User = get_user_model()


@celery_rabbit.task(name='apps.app.send_email_task', queue='rabbit_tasks', bind=True)
def send_email_task(self, user_id: int, to: str, subject: str, text: str, attachments: Optional[List[str]] = None, sender_email: str | None = None):
    user = User.objects.get(id=user_id)
    mailer = MailSend(user.username)
    mailer.send(to, subject, text, attachments, sender_email=sender_email)
    return {"to": to, "status": "queued", "sender": sender_email}


@celery_rabbit.task(name='apps.app.cleanup_attachments', queue='rabbit_tasks', bind=True)
def cleanup_attachments(self, attachment_paths: List[str]):
    if not attachment_paths:
        return {"removed": 0}
    try:
        parent = Path(attachment_paths[0]).parent
    except Exception:
        return {"removed": 0}
    removed = 0
    for fp in attachment_paths:
        p = Path(fp)
        if p.is_file():
            try:
                p.unlink()
                removed += 1
            except OSError:
                logger.warning(f"Failed to remove file {p}. It may not exist.")
    try:
        parent.rmdir()
    except OSError:
        logger.warning(f"Failed to remove directory {parent}. It may not be empty or does not exist.")
    return {"removed": removed}


@celery_rabbit.task(name='apps.app.send_bulk_emails', queue='rabbit_tasks', bind=True)
def send_bulk_emails(self, payloads: list, user_id: int, delay_s: int = 5):
    if not payloads:
        return {"count": 0}
    for i, p in enumerate(payloads):
        send_email_task.apply_async(kwargs={"user_id": user_id, **p}, countdown=i * delay_s, queue='rabbit_tasks')
    attachment_paths = payloads[0].get('attachments') if isinstance(payloads[0], dict) else []
    if attachment_paths:
        total_delay = (len(payloads) - 1) * delay_s + 30
        cleanup_attachments.apply_async(args=[attachment_paths], countdown=total_delay, queue='rabbit_tasks')
    return {"count": len(payloads)}
