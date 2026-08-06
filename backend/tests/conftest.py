import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_BASE_URL", "http://test")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://job_graph:job_graph@postgres:5432/job_graph_test",
)
os.environ.setdefault("REDIS_URL", "redis://redis:6379/0")
os.environ.setdefault("NEO4J_URI", "bolt://neo4j:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "job_graph_dev")
os.environ.setdefault("FILE_STORAGE_ROOT", "/tmp/job-graph-tests")
os.environ.setdefault("SESSION_SECRET", "test-secret-at-least-32-characters")
os.environ.setdefault("CORS_ORIGINS", '["http://localhost:3000"]')
os.environ.setdefault("ALGORITHM_SERVICE_URL", "http://algorithm:8001")
