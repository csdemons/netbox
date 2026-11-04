"""Проверка реальной миграции данных 0.3.0 -> 0.4.0 на тестовой PostgreSQL."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from netbox_server_wizard.models import Project


class ChangelogMigrationTests(TransactionTestCase):
    migrate_from = [("netbox_server_wizard", "0001_initial")]
    migrate_to = [("netbox_server_wizard", "0002_changelog_fields")]

    def test_migration_preserves_existing_projects(self):
        # Эта операция меняет схему ТОЛЬКО тестовой базы manage.py test.
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        old_project = old_apps.get_model("netbox_server_wizard", "Project")
        old_project.objects.create(name="Уже существующий проект")

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.assertTrue(Project.objects.filter(name="Уже существующий проект").exists())
        self.assertIsNotNone(Project._meta.get_field("last_updated"))
        self.assertIsNotNone(Project._meta.get_field("created"))
