"""rappi-ia: conceptos, embeddings, búsqueda híbrida por vertical, el agente y analítica."""

# Primero el .env de rappi-ia: rappi_scraper carga el suyo al importarse y load_dotenv no sobreescribe
# (sin esto, DATABASE_URL_TEST apuntaría a la base de tests del scraper).
from . import config  # noqa: F401
