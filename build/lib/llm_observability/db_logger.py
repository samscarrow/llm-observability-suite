import sqlalchemy
from sqlalchemy import text

class DBLogger:
    def __init__(self, db_uri: str):
        self.engine = sqlalchemy.create_engine(db_uri)

    def log_event(self, table_name: str, event_data: dict):
        with self.engine.connect() as connection:
            columns = ", ".join(event_data.keys())
            placeholders = ", ".join(f":{key}" for key in event_data.keys())
            statement = text(f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})")
            connection.execute(statement, **event_data)