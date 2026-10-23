import logging

from django.apps import AppConfig
from django.db import DatabaseError
from django.db.models.signals import pre_migrate

logger = logging.getLogger(__name__)

PGVECTOR_HELP = (
    "The PostgreSQL 'vector' extension (pgvector) could not be created in "
    "database '{db}'. The database user probably lacks permission. One-time "
    "fix: connect to the 'template1' database as a superuser and run "
    "CREATE EXTENSION IF NOT EXISTS vector; (do the same in your existing "
    "database). New databases, including Django's test database, then "
    "inherit it."
)


def ensure_pgvector_extension(sender, using="default", **kwargs):
    """
    Create the pgvector extension before migrations run.

    assistant/migrations/0001_initial.py creates a vector column but nothing
    created the extension, so fresh databases (including Django's test
    database) failed to migrate. Doing it here works for existing, fresh and
    test databases without editing an applied migration.
    """
    from django.db import connections

    connection = connections[using]

    if connection.vendor != "postgresql":
        return

    try:
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except DatabaseError as exc:
        message = PGVECTOR_HELP.format(db=connection.settings_dict.get("NAME"))
        logger.error(message)
        raise DatabaseError(message) from exc


class AssistantConfig(AppConfig):
    name = "assistant"

    def ready(self):
        pre_migrate.connect(
            ensure_pgvector_extension,
            sender=self,
            dispatch_uid="assistant.ensure_pgvector_extension",
        )
