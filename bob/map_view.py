"""Mapa clicável com SVG local e dados já autorizados."""

from pathlib import Path
import streamlit as st
import streamlit.components.v2 as components
from .maps import mapa_svg, NOMES
from .browser_storage import salvar_workspace


def mapa_interativo(sessao, componente, geracao):
    id_ = componente['id']
    sessao.mapas = getattr(sessao, 'mapas', {})
    estado = sessao.mapas.get(id_)
    resultado = componente['resultado']
    root = Path(__file__).resolve().parents[1] / 'assets'
    mapa = components.component('bob_map', html='<div class="bob-map"></div>',
        js=(root / 'map.js').read_text(encoding='utf-8'),
        css=(root / 'map.css').read_text(encoding='utf-8'))

    def selecionar():
        uf = st.session_state[f'map_{geracao}_{id_}'].estado
        if uf in sessao.perfil.ufs:
            sessao.mapas[id_] = uf
        elif uf == 'Brasil':
            sessao.mapas.pop(id_, None)
        salvar_workspace()

    mapa(key=f'map_{geracao}_{id_}', data={
        'svg': mapa_svg(sessao.perfil.ufs, resultado['dados'], componente['x'], componente['y'], estado),
        'ufs': list(sessao.perfil.ufs), 'estado': estado,
        'label': NOMES.get(estado, 'Brasil'),
    }, on_estado_change=selecionar, height='content')
