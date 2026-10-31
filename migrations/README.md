Flask-Migrate repository. Commands (from project root, with `FLASK_APP=run.py` set):

- `python -m flask db upgrade` — apply pending revisions
- `python -m flask db migrate -m "message"` — autogenerate a revision from model changes
- `python -m flask db stamp head` — mark DB current without running DDL (existing tables from SQL)

See the project `README.md` for full database setup.
