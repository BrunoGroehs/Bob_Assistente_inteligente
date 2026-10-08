"""Sessão local: conversa, componentes da IA e organização pessoal do workspace."""

from pathlib import Path
from math import isfinite

from .agents import Agentes
from .openrouter import OpenRouter
from .schemas import BobError, Usuario
from .tools import Backend


class SessaoLocal:
    def __init__(self, banco: Path, usuario: Usuario):
        self.perfil = usuario
        self.backend = Backend(banco, lambda: self.perfil)
        self.client = OpenRouter()
        self.agentes = Agentes(self.backend, self.client)
        self.mensagens = []
        self.ordem = []
        self.acoes_concluidas = {}
        self.posicoes = {}
        self.posicoes_manuais = set()

    def reiniciar(self, usuario=None):
        """Troca todo o estado, inclusive histórico do modelo e métricas de uso."""
        return SessaoLocal(self.backend.banco, usuario or self.perfil)

    def conversar(self, pergunta):
        self.mensagens.append({"role": "user", "content": pergunta})
        resultado = self.agentes.conversar(pergunta)
        self.mensagens.append({
            "role": "assistant",
            "content": resultado.get("resposta") or resultado.get("mensagem", "Não foi possível concluir a análise."),
            **({"rastreamento": resultado["rastreamento"]} if "rastreamento" in resultado else {}),
        })
        self.mensagens[:] = self.mensagens[-40:]
        return resultado

    def componentes(self):
        """Revalida acesso e mantém a ordem escolhida ao receber cartões da IA."""
        componentes = {c["id"]: c for c in self.backend.workspace()}
        ordem = [id_ for id_ in getattr(self, "ordem", []) if id_ in componentes]
        ordem.extend(id_ for id_ in componentes if id_ not in ordem)
        self.ordem = ordem
        return [componentes[id_] for id_ in ordem]

    def mover(self, componente_id, direcao):
        self.componentes()
        if componente_id not in self.ordem:
            raise BobError("ACESSO_RECURSO", "Componente indisponível nesta sessão.")
        if direcao not in (-1, 1):
            raise ValueError("Use -1 ou 1 para mudar a posição.")
        origem = self.ordem.index(componente_id)
        destino = origem + direcao
        if 0 <= destino < len(self.ordem):
            self.ordem[origem], self.ordem[destino] = self.ordem[destino], self.ordem[origem]

    def posicionar(self, posicoes, manuais=None):
        """Aceita só coordenadas finitas de cartões autorizados, sem alterar os dados."""
        permitidos = {c["id"] for c in self.componentes()}
        if not isinstance(posicoes, dict) or not set(posicoes) <= permitidos:
            raise BobError("ACESSO_RECURSO", "Componente indisponível nesta sessão.")
        manuais = set(posicoes) if manuais is None else set(manuais)
        if not manuais <= set(posicoes):
            raise BobError("ACESSO_RECURSO", "Posição manual indisponível nesta atualização.")
        novos = {}
        for id_, ponto in posicoes.items():
            if not isinstance(ponto, dict) or set(ponto) != {"x", "y"}:
                raise ValueError("Posição inválida.")
            if any(type(v) not in (int, float) or not isfinite(v) or not 0 <= v <= 20000 for v in ponto.values()):
                raise ValueError("Posição fora do workspace.")
            novos[id_] = dict(ponto)
        self.posicoes = {k: v for k, v in getattr(self, "posicoes", {}).items() if k in permitidos} | novos
        self.posicoes_manuais = ((getattr(self, "posicoes_manuais", set()) & permitidos) - set(posicoes)) | manuais

    def alternar_acao(self, componente_id):
        componentes = self.componentes()
        acao = next((c for c in componentes if c["id"] == componente_id and c["tipo"] == "acao"), None)
        if acao is None:
            raise BobError("ACESSO_RECURSO", "Ação indisponível nesta sessão.")
        concluidas = getattr(self, "acoes_concluidas", {})
        if concluidas.get(componente_id) == acao["versao"]:
            del concluidas[componente_id]
        else:
            concluidas[componente_id] = acao["versao"]
        self.acoes_concluidas = concluidas
