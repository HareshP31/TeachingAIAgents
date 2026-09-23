"""Schema marker.

This project deliberately uses psycopg and explicit SQL instead of an ORM. The
idempotent schema definition lives in :mod:`app.db.migrations`; typed API and
graph payloads live in :mod:`app.schemas`.
"""
