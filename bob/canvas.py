"""Ponte entre os cartões nativos do Streamlit e posições pessoais da sessão."""

from pathlib import Path
from .browser_storage import salvar_workspace

import streamlit as st
import streamlit.components.v2 as components

ASSETS = Path(__file__).resolve().parents[1] / "assets"


def montar_canvas(sessao, visiveis, geracao):
    canvas = components.component("bob_canvas", js=(ASSETS / "canvas.js").read_text(encoding="utf-8"))
    def salvar():
        valor = st.session_state[f"canvas_{geracao}"].layout
        if valor and valor.get('revision') == st.session_state.get('canvas_revision', 0):
            sessao.posicionar(valor['positions'], valor.get('manual_ids', []))
            salvar_workspace()

    canvas(key=f"canvas_{geracao}", data={
        "ids": [c["id"] for c in visiveis],
        "positions": getattr(sessao, "posicoes", {}),
        "manual_ids": sorted(getattr(sessao, "posicoes_manuais", set())),
        "revision": st.session_state.get('canvas_revision', 0),
    }, on_layout_change=salvar, height=0)
