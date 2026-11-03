from unittest.mock import patch

from django.test import SimpleTestCase

from apps.app.tasks.tasks_rabbit import send_bulk_emails


class SendBulkEmailsTests(SimpleTestCase):
    @patch("apps.app.tasks.tasks_rabbit.cleanup_attachments.apply_async")
    @patch("apps.app.tasks.tasks_rabbit.send_email_task.apply_async")
    def test_schedules_attachment_cleanup_after_all_emails(self, send_email, cleanup):
        attachments = ["/tmp/batch/file.txt"]
        payloads = [
            {"to": "first@example.com", "attachments": attachments},
            {"to": "second@example.com", "attachments": attachments},
        ]

        result = send_bulk_emails.run(payloads, user_id=1, delay_s=5)

        self.assertEqual(result, {"count": 2})
        cleanup.assert_called_once_with(
            args=[attachments], countdown=35, queue="rabbit_tasks"
        )

    @patch("apps.app.tasks.tasks_rabbit.cleanup_attachments.apply_async")
    @patch("apps.app.tasks.tasks_rabbit.send_email_task.apply_async")
    def test_schedules_cleanup_when_scheduling_an_email_fails(
        self, send_email, cleanup
    ):
        attachments = ["/tmp/batch/file.txt"]
        payloads = [
            {"to": "first@example.com", "attachments": attachments},
            {"to": "second@example.com", "attachments": attachments},
        ]
        send_email.side_effect = [None, RuntimeError("queue unavailable")]

        with self.assertRaisesRegex(RuntimeError, "queue unavailable"):
            send_bulk_emails.run(payloads, user_id=1, delay_s=5)

        cleanup.assert_called_once_with(
            args=[attachments], countdown=30, queue="rabbit_tasks"
        )
