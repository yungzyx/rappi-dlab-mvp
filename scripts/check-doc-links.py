#!/usr/bin/env python3
"""Revisa los enlaces relativos de los .md versionados: que el archivo exista y, si el enlace trae
ancla (#…), que el destino tenga un título con esa ancla (como las arma GitHub). También revisa que
ninguna tabla quede cortada: una fila que no sigue a otra fila tiene que ser un encabezado.

Uso, desde la raíz del repositorio:  python3 scripts/check-doc-links.py
Sale con 1 si encuentra un enlace roto o una tabla cortada. Solo usa la biblioteca estándar.
"""

import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
HTML_REF = re.compile(r"""<(?:img|a)\b[^>]*?\b(?:src|href)=["']([^"']+)["']""", re.IGNORECASE)
HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
HTML_ANCHOR = re.compile(r"""<a\s+[^>]*(?:name|id)=["']([^"']+)["']""", re.IGNORECASE)
FENCE = re.compile(r"^ {0,3}(```|~~~)")
TABLE_ROW = re.compile(r"^ {0,3}\|")
TABLE_DELIMITER = re.compile(r"^ {0,3}\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")


def tracked_markdown() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.md"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode()
    return [ROOT / name for name in out.split("\0") if name]


def prose_lines(text: str):
    """Las líneas fuera de bloques de código, con su número."""
    fenced = False
    for number, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            yield number, line


def slug(title: str) -> str:
    """El ancla que GitHub le da a un título."""
    title = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", title)  # un enlace en el título deja su texto
    title = re.sub(r"<[^>]+>", "", title).lower()
    kept = []
    for char in title:
        category = unicodedata.category(char)
        if char in " -_" or category[0] in "LN" or category == "Mn":
            kept.append(char)
    return "".join(kept).replace(" ", "-")


_anchors: dict[Path, set[str]] = {}


def anchors(path: Path) -> set[str]:
    if path not in _anchors:
        seen: dict[str, int] = {}
        found: set[str] = set()
        for _, line in prose_lines(path.read_text(encoding="utf-8")):
            found.update(HTML_ANCHOR.findall(line))
            match = HEADING.match(line)
            if not match:
                continue
            base = slug(match.group(2))
            count = seen.get(base, 0)
            seen[base] = count + 1
            found.add(base if count == 0 else f"{base}-{count}")
        _anchors[path] = found
    return _anchors[path]


def broken_tables(md: Path) -> list[str]:
    """Filas sueltas: GitHub corta la tabla en una línea que no es fila (una en blanco, un párrafo)
    y muestra lo que sigue como texto, salvo que empiece con encabezado y separador."""
    numbered = list(prose_lines(md.read_text(encoding="utf-8")))
    lines = [line for _, line in numbered]
    problems = []
    for index, (number, line) in enumerate(numbered):
        starts = TABLE_ROW.match(line) and not (index and TABLE_ROW.match(lines[index - 1]))
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if starts and not TABLE_DELIMITER.match(following):
            problems.append(f"{md.relative_to(ROOT)}:{number}: fila de tabla sin encabezado (¿tabla cortada?)")
    return problems


def check(md: Path) -> list[str]:
    problems = broken_tables(md)
    for number, line in prose_lines(md.read_text(encoding="utf-8")):
        line = re.sub(r"`[^`]*`", "", line)  # lo que va entre comillas invertidas no es un enlace
        for target in LINK.findall(line) + HTML_REF.findall(line):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE) or target.startswith("//"):
                continue  # http:, https:, mailto:…
            path_part, _, anchor = target.partition("#")
            path_part = unquote(path_part.split("?", 1)[0])
            dest = (md.parent / path_part).resolve() if path_part else md
            where = f"{md.relative_to(ROOT)}:{number}"
            if not dest.exists():
                problems.append(f"{where}: no existe {target}")
            elif anchor and dest.suffix == ".md" and unquote(anchor).lower() not in anchors(dest):
                problems.append(f"{where}: {dest.relative_to(ROOT)} no tiene el ancla #{anchor}")
    return problems


def main() -> int:
    files = tracked_markdown()
    problems = [problem for md in files if md.exists() for problem in check(md)]
    for problem in problems:
        print(problem)
    print(f"Enlaces y tablas en {len(files)} archivos .md: {len(problems)} problemas.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
