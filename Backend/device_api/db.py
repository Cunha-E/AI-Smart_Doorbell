#Now, the db.py is function-based, so there is no class, and nothing is inheriting from Resource

# 3rd-Party Imports:
from flask import current_app, g
import click
import sqlite3
# import firebase_admin # Import later when integrating with the database

def get_db():
    """
    Retrieves a database connection, creating one if it does not already exist.
    """
    if 'db' not in g:
        g.db = sqlite3.connect(
            current_app.config['DATABASE'],
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db(e=None):
    """Disconnects a database connection at the end of a request"""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    """Initializes the SQL Database for the Device API."""
    db = get_db()
    with current_app.open_resource('device.sql') as f:
        db.executescript(f.read().decode('utf8'))

@click.command('init-db')
def init_db_command():
    """Command line command to initialize the database"""
    init_db()
    click.echo('Database Initialized.')

def init_app(app):
    """Register database functions with the Flask app"""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
