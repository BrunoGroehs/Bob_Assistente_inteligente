"""Renderização SVG de malhas públicas locais, sem scripts ou serviços externos."""

import json
from functools import lru_cache
from html import escape
from math import cos, radians
from pathlib import Path

from .access import ESTADOS, uf_do_estado

CODIGOS = dict(zip(
    "11 12 13 14 15 16 17 21 22 23 24 25 26 27 28 29 31 32 33 35 41 42 43 50 51 52 53".split(),
    "RO AC AM RR PA AP TO MA PI CE RN PB PE AL SE BA MG ES RJ SP PR SC RS MS MT GO DF".split(),
))
NOMES = {uf: nome for nome, uf in ESTADOS.items()}


@lru_cache(maxsize=1)
def malhas():
    arquivo = Path(__file__).resolve().parent.parent / "assets" / "brasil-ufs.geojson"
    return json.loads(arquivo.read_text(encoding="utf-8"))["features"]


def mapa_svg(escopo, dados=(), x="estado", y="clientes", estado=None):
    """Ausência de resultado não significa zero; só colore valores autorizados."""
    valores = {uf_do_estado(str(linha[x])): linha[y] for linha in dados
               if uf_do_estado(str(linha[x])) in escopo and isinstance(linha[y], (int, float))}
    features = [f for f in malhas() if not estado or CODIGOS[f["properties"]["codarea"]] == estado]
    if not features:
        raise ValueError("Estado sem malha disponível.")
    formas = []
    for feature in features:
        geo = feature["geometry"]
        poligonos = geo["coordinates"] if geo["type"] == "MultiPolygon" else [geo["coordinates"]]
        aneis = [[(lon * cos(radians(15)), -lat) for lon, lat, *_ in anel]
                 for poligono in poligonos for anel in poligono]
        formas.append((CODIGOS[feature["properties"]["codarea"]], aneis))
    pontos = [p for _, aneis in formas for anel in aneis for p in anel]
    min_x, max_x = min(p[0] for p in pontos), max(p[0] for p in pontos)
    min_y, max_y = min(p[1] for p in pontos), max(p[1] for p in pontos)
    escala = min(560 / (max_x - min_x), 340 / (max_y - min_y))
    dx, dy = (600 - (max_x - min_x) * escala) / 2, (380 - (max_y - min_y) * escala) / 2
    minimo, maximo = min(valores.values(), default=0), max(valores.values(), default=0)
    paths, labels = [], []
    for uf, aneis in formas:
        autorizado = uf in escopo
        valor = valores.get(uf)
        cor = "#e5e7eb" if not autorizado else "#e1e8ee"
        if valor is not None:
            intensidade = (valor - minimo) / (maximo - minimo) if maximo != minimo else .55
            claro, escuro = (202, 223, 231), (44, 91, 112)
            cor = "#" + "".join(f"{round(a + (b-a)*intensidade):02x}" for a, b in zip(claro, escuro))
        detalhe = "Fora do acesso" if not autorizado else "Sem valor exibível" if valor is None else f"{y}: {valor:g}"
        path = " ".join("M " + " L ".join(f"{dx+(px-min_x)*escala:.2f},{dy+(py-min_y)*escala:.2f}" for px, py in anel) + " Z" for anel in aneis)
        paths.append(f'<path data-uf="{uf}" d="{path}" fill="{cor}" fill-rule="evenodd" stroke="#fafafa" stroke-width="1.3"><title>{escape(NOMES[uf] + " · " + detalhe)}</title></path>')
        # Centro da caixa do anel principal: rótulos de UFs, sem localidades inventadas.
        principal = max(aneis, key=len)
        cx = (min(p[0] for p in principal) + max(p[0] for p in principal)) / 2
        cy = (min(p[1] for p in principal) + max(p[1] for p in principal)) / 2
        if uf not in {"DF", "SE", "AL", "PB", "RN", "ES", "RJ"} or estado:
            labels.append(f'<text x="{dx+(cx-min_x)*escala:.2f}" y="{dy+(cy-min_y)*escala:.2f}" text-anchor="middle" fill="#334155" font-size="10" font-family="system-ui" pointer-events="none">{uf}</text>')
    titulo = escape(NOMES.get(estado, "Brasil — estados e Distrito Federal"))
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="380" viewBox="0 0 600 380" role="img" aria-label="{titulo}"><title>{titulo}</title>{"".join(paths)}{"".join(labels)}</svg>'
