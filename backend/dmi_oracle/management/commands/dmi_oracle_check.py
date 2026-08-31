"""Connectivity/schema check against the DMI Oracle database.

Read-only by design (ping/tables/describe/sample are all SELECT statements).
Requires the 'dmi_db' database alias, which config.settings only registers
when ORACLE_DMI_HOST is set in the environment.
"""
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import connections

IDENTIFIER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_$#]*$')


def _validate_identifier(name, label):
    if not IDENTIFIER_RE.match(name):
        raise CommandError(f"Invalid {label}: {name!r}")
    return name


class Command(BaseCommand):
    help = "Ping/introspect the DMI Oracle database (dmi_db alias). Read-only."

    def add_arguments(self, parser):
        parser.add_argument(
            'action', choices=['ping', 'tables', 'describe', 'sample'], nargs='?', default='ping',
        )
        parser.add_argument('--table', help='Table name for describe/sample')
        parser.add_argument('--limit', type=int, default=5, help='Row limit for sample (max 100)')
        parser.add_argument('--like', help="SQL LIKE filter for the tables action, e.g. '%%EXAM%%'")

    def handle(self, *args, **options):
        if 'dmi_db' not in connections.databases:
            raise CommandError(
                "The 'dmi_db' database alias is not configured. Set ORACLE_DMI_HOST "
                "(and _PORT / _SERVICE_NAME / _USER / _PASSWORD) in the environment."
            )
        conn = connections['dmi_db']
        action = options['action']

        if action == 'ping':
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM DUAL")
                cursor.fetchone()
            self.stdout.write(self.style.SUCCESS("Connexion Oracle DMI OK."))
            return

        if action == 'tables':
            pattern = (options.get('like') or '%').upper()
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT table_name FROM user_tables WHERE table_name LIKE :1 ORDER BY table_name",
                    [pattern],
                )
                rows = cursor.fetchall()
            if not rows:
                self.stdout.write("Aucune table trouvee pour ce filtre.")
            for (name,) in rows:
                self.stdout.write(name)
            return

        table = options.get('table')
        if not table:
            raise CommandError("--table est requis pour describe/sample")
        table = _validate_identifier(table, 'table')

        if action == 'describe':
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT column_name, data_type, data_length, nullable "
                    "FROM user_tab_columns WHERE table_name = :1 ORDER BY column_id",
                    [table.upper()],
                )
                rows = cursor.fetchall()
            if not rows:
                raise CommandError(f"Table introuvable ou inaccessible: {table}")
            for column_name, data_type, data_length, nullable in rows:
                self.stdout.write(f"{column_name:30s} {data_type:15s} len={data_length} nullable={nullable}")
            return

        if action == 'sample':
            limit = max(1, min(options['limit'], 100))
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT * FROM {table} WHERE ROWNUM <= {limit}")
                columns = [c[0] for c in cursor.description]
                for row in cursor.fetchall():
                    self.stdout.write(str(dict(zip(columns, row))))
            return
