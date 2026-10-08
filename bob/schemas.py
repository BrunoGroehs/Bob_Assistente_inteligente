"""Contratos pequenos compartilhados pelas ferramentas e pelos agentes."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .chart_templates import TemplateGrafico

UFS = frozenset("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())


class Contrato(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Usuario(Contrato):
    id: str = Field(min_length=1)
    papel: Literal["leitor", "analista", "administrador"]
    ufs: tuple[str, ...] = ()

    @field_validator("ufs")
    @classmethod
    def validar_ufs(cls, value):
        if not set(value) <= UFS:
            raise ValueError("UF inválida.")
        return tuple(sorted(set(value)))


class Objetivo(Contrato):
    descricao: str = Field(min_length=1, max_length=500)
    ufs_solicitadas: list[str] = Field(default_factory=list, max_length=27)
    ultimos_dias: int | None = Field(default=None, ge=1, le=3660)


class Consulta(Contrato):
    sql: str = Field(min_length=1, max_length=10000)
    objetivo: Objetivo


class PedidoPainel(Contrato):
    dataset_ids: list[str] = Field(min_length=1, max_length=8)
    pedido: str = Field(min_length=1, max_length=1000)
    contexto: str = Field(default="", max_length=1000)


class AcaoSugerida(Contrato):
    descricao: str = Field(min_length=1, max_length=700)
    publico: str = Field(min_length=1, max_length=300)
    canal: Literal["WhatsApp", "E-mail", "Telefone", "App", "Site", "A definir"]
    mensagem: str | None = Field(default=None, min_length=1, max_length=1200)


class Componente(Contrato):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,60}$")
    tipo: Literal["indicador", "tabela", "barras", "linhas", "mapa", "acao", "grafico"]
    dataset_id: str
    titulo: str = Field(min_length=1, max_length=120)
    x: str | None = None
    y: str | None = None
    acao: AcaoSugerida | None = None
    template: TemplateGrafico | None = None
    serie: str | None = None
    partes_exclusivas: bool = False

    @model_validator(mode="after")
    def validar_configuracao(self):
        if (self.tipo == "acao") != (self.acao is not None):
            raise ValueError("Somente componentes de ação devem conter uma ação sugerida.")
        if (self.tipo == "grafico") != (self.template is not None):
            raise ValueError("Somente tipo grafico usa template, obrigatório para esse tipo.")
        if self.tipo != "grafico" and (self.serie or self.partes_exclusivas):
            raise ValueError("serie e partes_exclusivas são configurações de templates de gráfico.")
        return self


class Painel(Contrato):
    componentes: list[Componente] = Field(min_length=1, max_length=8)


class Publicacao(Contrato):
    especificacao: Painel


class BobError(Exception):
    def __init__(self, codigo: str, mensagem: str):
        super().__init__(mensagem)
        self.codigo = codigo

    def resposta(self):
        return {
            "status": "acesso_negado" if self.codigo.startswith("ACESSO_") else "erro",
            "codigo": self.codigo,
            "mensagem": str(self),
        }

