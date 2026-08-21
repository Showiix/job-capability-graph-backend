from neo4j import AsyncGraphDatabase

from app.core.config import get_settings

settings = get_settings()
neo4j_driver = AsyncGraphDatabase.driver(
    settings.neo4j_uri,
    auth=(settings.neo4j_username, settings.neo4j_password.get_secret_value()),
)
