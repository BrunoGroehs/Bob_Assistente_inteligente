"""Linha do tempo verificável de um turno, sem prompts ou reasoning do provedor."""

from copy import deepcopy
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4

from .access import proteger_texto
from .schemas import BobError


class Rastreamento:
    def __init__(self, pergunta, segredos=()):
        self.id = uuid4().hex
        self.inicio = monotonic()
        self.segredos = tuple(s for s in segredos if isinstance(s, str) and s)
        self.pergunta = self.limpar(pergunta)
        self.etapas = []

    def limpar(self, valor):
        if isinstance(valor, str):
            for segredo in self.segredos:
                valor = valor.replace(segredo, "[segredo omitido]")
            try:
                proteger_texto(valor)
            except BobError:
                return "[conteúdo protegido]"
            return valor[:8000] + ("… [texto truncado]" if len(valor) > 8000 else "")
        if isinstance(valor, dict):
            privadas = {"api_key", "authorization", "token", "password", "senha", "reasoning", "reasoning_details", "email", "cpf", "telefone"}
            return {self.limpar(str(k)): "[conteúdo protegido]" if str(k).lower() in privadas else self.limpar(v) for k, v in valor.items()}
        if isinstance(valor, (list, tuple)):
            return [self.limpar(v) for v in valor]
        return valor

    def registrar(self, tipo, agente="sistema", **detalhes):
        etapa = {"numero": len(self.etapas) + 1, "tipo": tipo, "agente": agente,
                 "horario": datetime.now(timezone.utc).isoformat(), **self.limpar(detalhes)}
        self.etapas.append(etapa)
        return etapa["numero"]

    @staticmethod
    def resumir(resultado):
        campos = ("status", "codigo", "mensagem", "dataset_id", "colunas", "quantidade_linhas",
                  "grupos_suprimidos", "truncado", "parametros", "escopo", "renderizado")
        resumo = {k: resultado[k] for k in campos if k in resultado}
        if "componentes" in resultado:
            resumo["componentes"] = [{k: c[k] for k in ("id", "tipo", "titulo", "dataset_id", "versao") if k in c}
                                     for c in resultado["componentes"]]
        return resumo

    def finalizar(self, resultado):
        # Perfil revogado: não devolve evidências obtidas com permissões anteriores.
        if resultado.get("codigo") == "ACESSO_ALTERADO":
            self.etapas.clear()
        self.registrar("resposta_final", status=resultado["status"], resposta=resultado.get("resposta", ""),
                       codigo=resultado.get("codigo"))
        return {**resultado, "rastreamento": {"id": self.id, "pergunta": self.pergunta,
                "status": resultado["status"], "duracao_ms": round((monotonic() - self.inicio) * 1000),
                "etapas": deepcopy(self.etapas)}}
