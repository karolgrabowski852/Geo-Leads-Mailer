from django.db import migrations


def copy_auth_users_to_admin_user(apps, schema_editor):
    table_names = set(schema_editor.connection.introspection.table_names())
    if "auth_user" not in table_names or "admin_app_user" not in table_names:
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO admin_app_user
                (
                    password, last_login, is_superuser, username,
                    first_name, last_name, email, is_staff, is_active,
                    date_joined, language, country
                )
            SELECT
                au.password,
                au.last_login,
                au.is_superuser,
                au.username,
                au.first_name,
                au.last_name,
                au.email,
                au.is_staff,
                au.is_active,
                au.date_joined,
                'pl',
                'PL'
            FROM auth_user au
            WHERE NOT EXISTS (
                SELECT 1 FROM admin_app_user aau
                WHERE aau.username = au.username OR aau.email = au.email
            )
            """
        )


class Migration(migrations.Migration):

    dependencies = [
        ("admin_app", "0002_user_auth_fields"),
    ]

    operations = [
        migrations.RunPython(
            copy_auth_users_to_admin_user, migrations.RunPython.noop
        ),
    ]
