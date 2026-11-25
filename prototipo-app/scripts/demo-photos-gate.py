"""Las reglas del scraper para las fotos de la demo sin conexión (scripts/demo-photos.mjs lo corre con el Python de
rappi-scraper antes de bajar algo): toma sus candados de descarga (rappi-scraper/data/scraper.lock y, con DATABASE_URL,
el de la base), revisa robots.txt para cada dirección y dice con qué User-Agent bajarlas, el del scraper.

Lee de la entrada una línea con la lista JSON de direcciones y escribe una línea JSON: `{"user_agent": …}` si se puede
bajar, `{"busy": …}` si otra descarga tiene el candado o `{"denial": …}` si robots.txt no permite una. Con
`user_agent`, los candados duran hasta que se cierra la entrada (o muere el script de Node)."""

import json
import sys

import requests

from rappi_scraper import config
from rappi_scraper.lock import DownloadInProgress, download_lock
from rappi_scraper.scraping.robots import RobotsPolicy


def robots_txt(url: str) -> str | None:
    """El robots.txt de un sitio; None si no tiene (cualquier 4xx). Un 5xx o la red lanzan: no permite nada."""
    response = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=config.TIMEOUT_SECONDS)
    if 400 <= response.status_code < 500:
        return None
    response.raise_for_status()
    return response.text


def answer(**fields: str) -> None:
    print(json.dumps(fields, ensure_ascii=False), flush=True)


urls = json.loads(sys.stdin.readline())
try:
    with download_lock():
        robots = RobotsPolicy(config.UA_PROJECT, robots_txt)
        denial = next((reason for url in urls if (reason := robots.denial(url))), None)
        if denial:
            answer(denial=denial)
            sys.exit(7)
        answer(user_agent=config.USER_AGENT)
        sys.stdin.read()
except DownloadInProgress as exc:
    answer(busy=str(exc))
    sys.exit(1)
