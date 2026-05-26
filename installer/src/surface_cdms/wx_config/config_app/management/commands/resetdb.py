#!/usr/bin/env python

import os
import subprocess
import time

from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Resets the database and migrations, then runs the server'

    def handle(self, *args, **options):
        # Remove the SQLite database file
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'db.sqlite3')
        dump_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'dump.rdb')

        # remove db.sqlite file
        if os.path.exists(db_path):
            os.remove(db_path)
            self.stdout.write(self.style.SUCCESS(f'Successfully deleted {db_path}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'stale database file not found'))

        # remove dump.rdb file
        if os.path.exists(dump_path):
            os.remove(dump_path)
            self.stdout.write(self.style.SUCCESS(f'Successfully deleted {dump_path}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'stale dump file not found'))

        # Remove migration files
        for root, dirs, files in os.walk('..'):
            for file in files:
                if file.endswith('.py') and 'migrations' in root and file != '__init__.py':
                    os.remove(os.path.join(root, file))
                    self.stdout.write(self.style.SUCCESS(f'Deleted {os.path.join(root, file)}'))
                if file.endswith('.pyc') and 'migrations' in root:
                    os.remove(os.path.join(root, file))
                    self.stdout.write(self.style.SUCCESS(f'Deleted {os.path.join(root, file)}'))

        # Make migrations and migrate
        self.stdout.write('Making migrations...')
        os.system('python3 manage.py makemigrations')
        self.stdout.write('Applying migrations...')
        os.system('python3 manage.py migrate')
        # Collect static files
        self.stdout.write('Collecting Static files...')
        os.system('python3 manage.py collectstatic --noinput')
