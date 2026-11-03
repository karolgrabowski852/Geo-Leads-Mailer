from django.conf import settings
import logging
import os
import uuid

logger = logging.getLogger(__name__)


def save_files(upload_files: list) -> list[str]:
    attachment_paths: list[str] = []
    base_dir = settings.EMAIL_ATTACHMENTS_DIR
    batch_dir = os.path.join(base_dir, uuid.uuid4().hex)
    os.makedirs(batch_dir, exist_ok=True)
    for f in upload_files:
        dest_path = os.path.join(batch_dir, f.name)
        with open(dest_path, 'wb') as out:
            for chunk in f.chunks():
                out.write(chunk)
        attachment_paths.append(dest_path)
    return attachment_paths
