"""Reconecta a sessão Streamlit ao workspace salvo pelo navegador."""

import secrets
import sqlite3
from pathlib import Path
import streamlit as st
import streamlit.components.v2 as components

from .persistence import restaurar, salvar
from .schemas import BobError


def conectar_workspace(banco):
    st.session_state.setdefault('workspace_token', secrets.token_hex(32))
    bridge = components.component('bob_storage', js=(Path(__file__).resolve().parents[1] / 'assets/storage.js').read_text(encoding='utf-8'))

    def recebido():
        token = st.session_state['browser_storage'].token
        if token == st.session_state.get('workspace_active'):
            return
        try:
            sessao = restaurar(banco, token)
        except (BobError, ValueError, KeyError, TypeError, sqlite3.Error, OSError):
            sessao = None
            st.session_state.aviso = 'Não foi possível restaurar o workspace salvo. A sessão abriu vazia.'
        if sessao is not None:
            st.session_state.sessao = sessao
            st.session_state.geracao += 1
        st.session_state.workspace_token = token
        st.session_state.workspace_active = token

    bridge(key='browser_storage', data={'token': st.session_state.workspace_token, 'active': st.session_state.get('workspace_active')}, on_token_change=recebido, height=0)


def salvar_workspace():
    # Não sobrescreve um workspace existente antes de receber seu identificador.
    if st.session_state.get('workspace_active'):
        salvar(st.session_state.sessao, st.session_state.workspace_active)
