from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # DB (ton projet utilise POSTGRES_* dans .env)
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_server: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "postgres"

    # Pool de connexions (v1.2)
    db_pool_size: int = 20
    db_pool_max_overflow: int = 10
    db_pool_timeout: int = 5

    # Auth (si tu l'as)
    jwt_secret: str = "changethis_secret_key"

    # Google compare (Option A)
    google_routes_api_key: str | None = None

    # ------------------------------------------------------------------
    # Routing (v1.2)
    # ------------------------------------------------------------------
    # Modèle de coût de Dijkstra/A*:
    #   time     -> coût en minutes (km/kmh), objectif = trajet le plus rapide
    #   distance -> coût osm2po (distance), comportement d'origine
    cost_model: str = "time"
    # Algorithme:
    #   auto     -> Dijkstra pour les segments courts, A* au-delà d'astar_long_route_km
    #   dijkstra -> toujours Dijkstra (comportement d'origine)
    #   astar    -> toujours A* (repli Dijkstra en cas d'échec)
    routing_algo: str = "auto"
    astar_long_route_km: float = 40.0

    # Cache des segments de route (invalidation exacte par version d'obstacles)
    route_cache: bool = True
    route_cache_ttl_min: int = 10
    route_cache_retention_hours: int = 6

    # ------------------------------------------------------------------
    # Obstacles (v1.2)
    # ------------------------------------------------------------------
    # Si true: le routing lit event_edge_closure (fermetures multi-edges,
    # sens, pénalité). Si false: CTE d'origine sur events_road_closed.edge_id.
    multi_edge_closures: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def db_url(self) -> str:
        # SQLAlchemy psycopg (Python 3.12)
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_server}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
