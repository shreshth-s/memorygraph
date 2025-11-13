# backend/db.py
import psycopg
from psycopg.rows import dict_row

DB = {
    "host": "localhost",
    "port": "5433",          # change if yours differs
    "user": "postgres",
    "password": "1904",  # <- put the 5433 one here
    "dbname": "mgdb",
}

def conn():
    return psycopg.connect(row_factory=dict_row, **DB)
