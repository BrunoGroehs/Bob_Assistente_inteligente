"""Workspace local durável: identificador opaco no navegador, estado no servidor."""

import json
import os
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from .schemas import Consulta, Usuario
from .session import SessaoLocal
from .tracing import Rastreamento

ARQUIVO = Path(os.environ.get('BOB_WORKSPACE_STORE', Path(__file__).resolve().parents[1] / '.bob' / 'workspaces.sqlite3'))
VALIDO = re.compile(r'^[a-f0-9]{64}$')
EXPIRACAO = 30 * 86400


def conectar(arquivo):
    arquivo = Path(arquivo)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(arquivo, timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, atualizado REAL, estado TEXT)')
    return db


def salvar(sessao, id_, arquivo=ARQUIVO):
    if not VALIDO.fullmatch(id_):
        raise ValueError('Identificador de workspace inválido.')
    perfil = sessao.backend.usuario()
    componentes = sessao.componentes() if perfil.papel != 'administrador' and perfil.ufs else []
    limpar = Rastreamento('', (sessao.client.api_key,)).limpar
    estado = {
        'versao': 1, 'banco': str(sessao.backend.banco.resolve()), 'perfil': perfil.model_dump(),
        'consultas': {id_: ds['consulta'].model_dump() for id_, ds in sessao.backend._datasets.items()},
        'componentes': [{k: v for k, v in c.items() if k not in {'resultado', 'versao', 'evidencia_em'}} for c in componentes],
        'versoes': {c['id']: {k: c[k] for k in ('versao', 'evidencia_em') if k in c} for c in componentes},
        'mensagens': limpar(sessao.mensagens), 'conversas': limpar(sessao.backend.conversas),
        'ordem': sessao.ordem, 'posicoes': sessao.posicoes,
        'posicoes_manuais': sorted(getattr(sessao, 'posicoes_manuais', set())),
        'acoes_concluidas': sessao.acoes_concluidas,
        'mapas': getattr(sessao, 'mapas', {}),
    }
    with closing(conectar(arquivo)) as db, db:
        db.execute('DELETE FROM workspaces WHERE atualizado < ?', (time.time() - EXPIRACAO,))
        db.execute('INSERT OR REPLACE INTO workspaces VALUES (?, ?, ?)', (id_, time.time(), json.dumps(estado, ensure_ascii=False)))


def restaurar(banco, id_, usuario=None, arquivo=ARQUIVO):
    if not VALIDO.fullmatch(id_):
        raise ValueError('Identificador de workspace inválido.')
    with closing(conectar(arquivo)) as db:
        linha = db.execute('SELECT estado FROM workspaces WHERE id=? AND atualizado>=?', (id_, time.time()-EXPIRACAO)).fetchone()
    if not linha:
        return None
    estado = json.loads(linha[0])
    caminho = Path(banco).resolve()
    origens = {str(caminho)}
    if caminho.parent.name == 'data':
        origens.add(str(caminho.parent.parent / 'Instruções' / caminho.name))
    if estado.get('versao') != 1 or estado['banco'] not in origens:
        return None
    salvo = Usuario.model_validate(estado['perfil'])
    # Em uma implantação autenticada, o chamador deve fornecer o perfil atual.
    if usuario is not None and salvo != usuario:
        return SessaoLocal(banco, usuario)
    sessao = SessaoLocal(banco, usuario or salvo)
    if salvo.papel == 'analista' and salvo.ufs:
        # Reexecuta as consultas com as permissões e a validação SQL atuais.
        for dataset_id, consulta in estado['consultas'].items():
            sessao.backend._consultar(Consulta.model_validate(consulta), dataset_id=dataset_id)
        if estado['componentes']:
            resposta = sessao.backend.publicar_painel({'componentes': estado['componentes']})
            if resposta['status'] != 'publicado':
                return None
            for id_, versao in estado.get('versoes', {}).items():
                if id_ in sessao.backend._componentes:
                    sessao.backend._componentes[id_].update(versao)
    sessao.mensagens = estado['mensagens'][-40:]
    sessao.backend.conversas = estado['conversas'][-5:]
    sessao.ordem = estado['ordem']
    permitidos = {c['id'] for c in sessao.componentes()} if salvo.papel != 'administrador' and salvo.ufs else set()
    if permitidos:
        sessao.posicionar({k: v for k, v in estado['posicoes'].items() if k in permitidos},
                         [k for k in estado.get('posicoes_manuais', []) if k in permitidos and k in estado['posicoes']])
    sessao.acoes_concluidas = {k: v for k, v in estado['acoes_concluidas'].items() if k in permitidos}
    sessao.mapas = {k: v for k, v in estado.get('mapas', {}).items() if k in permitidos and v in salvo.ufs}
    return sessao
