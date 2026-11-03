import json

from django.db import migrations, transaction
from apps.app.fields import EncryptedTextField


def migrate_oauth_files(apps, schema_editor):
    User = apps.get_model("admin_app", "User")
    database = schema_editor.connection.alias
    token_field = User._meta.get_field("token")
    credentials_field = User._meta.get_field("credentials")

    users = User.objects.using(database).only(
        "pk", "token", "credentials"
    )
    for user in users.iterator():
        token_name = user.token.name
        credentials_name = user.credentials.name

        if token_name:
            with token_field.storage.open(token_name, "rb") as token_file:
                token_info = json.load(token_file)
            if not isinstance(token_info, dict):
                raise ValueError(
                    f"Expected a JSON object in legacy Gmail token for user {user.pk}."
                )
            user.oauth_token = json.dumps(token_info)
            user.save(using=database, update_fields=["oauth_token"])

        for field, name in (
            (token_field, token_name),
            (credentials_field, credentials_name),
        ):
            if name:
                transaction.on_commit(
                    lambda storage=field.storage, filename=name: storage.delete(
                        filename
                    ),
                    using=database,
                )


class Migration(migrations.Migration):
    dependencies = [
        ("admin_app", "0003_company_unique_company_osm_object"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="oauth_token",
            field=EncryptedTextField(blank=True, null=True),
        ),
        migrations.RunPython(migrate_oauth_files),
        migrations.RemoveField(
            model_name="user",
            name="credentials",
        ),
        migrations.RemoveField(
            model_name="user",
            name="token",
        ),
        migrations.RenameField(
            model_name="user",
            old_name="oauth_token",
            new_name="token",
        ),
    ]
