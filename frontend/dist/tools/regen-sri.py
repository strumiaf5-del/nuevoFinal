#!/usr/bin/env python3
"""regen-sri.py — regenera los hashes SRI (integrity=sha384-...) de los HTML.

USO:
  python3 tools/regen-sri.py            # reescribe hashes desactualizados (in-place)
  python3 tools/regen-sri.py --check    # solo verifica; exit 1 si hay stale/missing

Correr desde frontend/ (o con path absoluto — el script resuelve su propia root).

Por qué existe: los <script>/<link> de index.html y login.html llevan
integrity="sha384-...". Cada vez que cambia un .js/.css referenciado sin
regenerar el hash, el browser BLOQUEA el recurso (SRI mismatch) y la app
rompe en cascada. frontend-sync.sh corre este script antes de cada deploy
para que eso nunca llegue a producción.

Nota: NO toca <script id="sliders-meta"> (JSON inline) ni URLs externas.
"""
import base64
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # frontend/
HTML_FILES = ["index.html", "login.html"]

TAG_RE = re.compile(
    r'<(?P<tag>\w+)\b(?P<pre>[^>]*?)integrity="sha384-(?P<hash>[A-Za-z0-9+/=]+)"(?P<post>[^>]*?)>'
    r"|"
    r'<(?P<tag2>\w+)\b(?P<pre2>[^>]*?)(?:src|href)="(?P<path>[^"]+)"(?P<post2>[^>]*?)>',
    re.S,
)


def sri_of(path: Path) -> str:
    digest = hashlib.sha384(path.read_bytes()).digest()
    return base64.b64encode(digest).decode().rstrip("=")


def local_ref(attrs: str) -> str | None:
    m = re.search(r'(?:src|href)="([^"]+)"', attrs)
    if not m:
        return None
    ref = m.group(1)
    if ref.startswith(("http://", "https://", "//", "data:", "blob:", "#")):
        return None
    return ref


def process(html_path: Path, check_only: bool) -> tuple[int, int, list[str]]:
    """Devuelve (total, changed, missing)."""
    text = html_path.read_text(encoding="utf-8")
    original = text
    changed = 0
    total = 0
    missing: list[str] = []

    # Recorrer tags por posición para poder reemplazar de atrás hacia adelante
    # (evita desplazar offsets).
    for m in reversed(list(re.finditer(r"<(?:script|link)\b[^>]*>", text, re.S))):
        tag = m.group(0)
        ref = local_ref(tag)
        if ref is None:
            continue
        target = (ROOT / ref).resolve()
        try:
            target.relative_to(ROOT)
        except ValueError:
            missing.append(f"{html_path.name}: {ref} (fuera de frontend/)")
            continue
        if not target.is_file():
            missing.append(f"{html_path.name}: {ref} (no existe)")
            continue
        total += 1
        actual = sri_of(target)
        hm = re.search(r'integrity="sha384-([A-Za-z0-9+/=]+)"', tag)
        if hm is None:
            changed += 1
            if not check_only:
                if tag.endswith("/>"):
                    new_tag = tag[:-2].rstrip() + f' integrity="sha384-{actual}"/>'
                else:
                    new_tag = tag[:-1].rstrip() + f' integrity="sha384-{actual}">'
                text = text[: m.start()] + new_tag + text[m.end() :]
        elif hm.group(1) != actual:
            changed += 1
            if not check_only:
                new_tag = tag.replace(
                    f'integrity="sha384-{hm.group(1)}"', f'integrity="sha384-{actual}"'
                )
                text = text[: m.start()] + new_tag + text[m.end() :]

    if missing:
        return total, changed, missing

    if not check_only and text != original:
        html_path.write_text(text, encoding="utf-8")

    return total, changed, missing


def main() -> int:
    check_only = "--check" in sys.argv[1:]
    grand_total = grand_changed = 0
    all_missing: list[str] = []
    any_change = False

    for name in HTML_FILES:
        hp = ROOT / name
        if not hp.is_file():
            print(f"SKIP {name} (no existe)", file=sys.stderr)
            continue
        total, changed, missing = process(hp, check_only)
        grand_total += total
        grand_changed += changed
        all_missing.extend(missing)
        status = "STALE" if changed else "OK"
        if changed:
            any_change = True
        action = " (check)" if check_only else (f" → {changed} regenerados" if changed else "")
        print(f"{name}: {status} [{total} declaraciones]{action}")

    if all_missing:
        print("\nARCHIVOS REFERENCIADOS QUE NO EXISTEN:", file=sys.stderr)
        for item in all_missing:
            print(f"  ✗ {item}", file=sys.stderr)
        return 1

    if check_only and (grand_changed or any_change):
        print(
            f"\n✗ {grand_changed} hashes desactualizados. "
            f"Corré: python3 tools/regen-sri.py",
            file=sys.stderr,
        )
        return 1

    if check_only:
        print(f"\n✓ {grand_total}/{grand_total} hashes OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
