"""MySQL connection boundary; credentials are only read from the environment."""

import os

import pymysql
from dotenv import load_dotenv

load_dotenv()


def connect():
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "dq_app"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "data_quality_agent"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=5,
        read_timeout=30,
        write_timeout=30,
    )
