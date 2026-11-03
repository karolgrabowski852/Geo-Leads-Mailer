from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.app.utils import save_files


@override_settings(DJANGO_SETTINGS_MODULE='apps.settings_test')
class UtilsTests(TestCase):
    def test_save_files_writes_to_disk(self):
        f1 = SimpleUploadedFile("a.txt", b"hello")
        f2 = SimpleUploadedFile("b.txt", b"world")
        paths = save_files([f1, f2])
        self.assertEqual(len(paths), 2)
