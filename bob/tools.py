"""Estado da sessão e ferramentas. Aqui ficam as decisões de acesso."""

from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from .access import exigir_acesso, proteger_texto, uf_do_estado, ufs_no_texto
from .chart_templates import validar_template
from .database import abrir_recorte, descobrir_schema, executar, validar_sql
from .schemas import BobError, Consulta, Painel, Usuario


def agora():
    return datetime.now(timezone.utc).isoformat()


def erro_contrato():
    return BobError("ARGUMENTOS_INVALIDOS", "Argumentos inválidos. Use exatamente os campos e tipos do contrato.").resposta()


def validar_grafico(componente, dataset):
    try:
        validar_template(componente, dataset)
    except ValueError as erro:
        raise BobError("PAINEL_INVALIDO", str(erro)) from None


class Backend:
    def __init__(self, banco: Path, obter_usuario, hoje=None):
        self.banco = Path(banco)
        self.obter_usuario = obter_usuario
        self.hoje = hoje or (lambda: datetime.now(ZoneInfo("America/Sao_Paulo")).date())
        self._perfil = None
        self._datasets = {}
        self._componentes = {}
        self.conversas = []
        self.eventos = []

    def usuario(self) -> Usuario:
        """Revalida o perfil a cada operação e invalida estado de permissões antigas."""
        try:
            atual = Usuario.model_validate(self.obter_usuario())
        except (BobError, ValidationError, OSError):
            self._limpar()
            raise BobError("ACESSO_USUARIO", "Não foi possível confirmar suas permissões.") from None
        if atual != self._perfil:
            self._limpar()
            self._perfil = atual
        return atual

    def _limpar(self):
        self._datasets.clear()
        self._componentes.clear()
        self.conversas.clear()
        self.eventos.clear()
        self._perfil = None

    def contexto(self):
        usuario = self.usuario()
        exigir_acesso(usuario, "consultar")
        with closing(abrir_recorte(self.banco, usuario)) as recorte:
            schema = descobrir_schema(recorte)
            cobertura = {}
            for tabela, colunas in schema.items():
                for coluna in colunas:
                    if coluna.startswith("data_"):
                        extremos = recorte.execute(f'SELECT MIN("{coluna}"), MAX("{coluna}") FROM "{tabela}"').fetchone()
                        cobertura[tabela] = [str(v)[:7] if v else None for v in extremos]
        return {"ufs_permitidas": usuario.ufs, "schema": schema, "cobertura_meses": cobertura, "hoje": self.hoje().isoformat()}

    def consultar_dados(self, sql, objetivo):
        try:
            consulta = Consulta(sql=sql, objetivo=objetivo)
            dataset = self._consultar(consulta)
            return {"status": "ok", **self._publico(dataset)}
        except ValidationError:
            return erro_contrato()
        except BobError as erro:
            self.eventos.append({"acao": "consulta", "codigo": erro.codigo})
            return erro.resposta()

    def _consultar(self, consulta: Consulta, acao="consultar", dataset_id=None, validar_resultado=None):
        usuario = self.usuario()
        solicitadas = set(consulta.objetivo.ufs_solicitadas) | ufs_no_texto(consulta.objetivo.descricao)
        exigir_acesso(usuario, acao, solicitadas)
        proteger_texto(consulta.sql)
        proteger_texto(consulta.objetivo.descricao)
        if dataset_id is None and len(self._datasets) >= 20:
            raise BobError("LIMITE_SESSAO", "A sessão atingiu o limite de 20 resultados. Inicie uma nova sessão.")
        parametros = {}
        dias = consulta.objetivo.ultimos_dias
        if dias:
            dia = self.hoje()
            parametros = {"inicio": (dia - timedelta(days=dias - 1)).isoformat(), "fim": (dia + timedelta(days=1)).isoformat()}
        with closing(abrir_recorte(self.banco, usuario)) as recorte:
            schema = descobrir_schema(recorte)
            seguro = validar_sql(consulta.sql, schema, usuario, acao, bool(dias))
            resultado = executar(recorte, seguro, parametros, schema)
        dataset = {"dataset_id": dataset_id or uuid4().hex, "consulta": consulta, "escopo": list(usuario.ufs), "atualizado_em": agora(), "parametros": parametros, **resultado}
        if validar_resultado:
            validar_resultado(dataset)
        self._datasets[dataset["dataset_id"]] = dataset
        self.eventos.append({"acao": acao, "sql": consulta.sql, "objetivo": consulta.objetivo.descricao, "dataset_id": dataset["dataset_id"], "duracao_ms": resultado["duracao_ms"]})
        return dataset

    @staticmethod
    def _publico(dataset):
        return deepcopy({k: v for k, v in dataset.items() if k != "consulta"})

    def dados(self, dataset_id):
        usuario = self.usuario()
        exigir_acesso(usuario, "ler")
        dataset = self._datasets.get(dataset_id)
        if dataset is None:
            raise BobError("ACESSO_RECURSO", "Resultado indisponível nesta sessão ou fora do seu acesso.")
        return self._publico(dataset)

    def publicar_painel(self, especificacao, permitidos=None):
        try:
            exigir_acesso(self.usuario(), "publicar")
            painel = Painel.model_validate(especificacao)
            if len({c.id for c in painel.componentes}) != len(painel.componentes):
                raise BobError("PAINEL_INVALIDO", "Cada componente precisa de um identificador diferente.")
            atualizacoes = {}
            for componente in painel.componentes:
                proteger_texto(componente.titulo)
                exigir_acesso(self.usuario(), "publicar", ufs_no_texto(componente.titulo))
                if permitidos is not None and componente.dataset_id not in permitidos:
                    raise BobError("ACESSO_RECURSO", "O componente deve usar um dos resultados enviados ao agente visual.")
                dataset = self.dados(componente.dataset_id)
                if componente.tipo == "grafico":
                    validar_grafico(componente.model_dump(), dataset)
                if componente.acao:
                    if not dataset["dados"]:
                        raise BobError("PAINEL_INVALIDO", "Ações precisam de resultados exibíveis para fundamentar a recomendação.")
                    texto = " ".join(v for v in componente.acao.model_dump().values() if v)
                    proteger_texto(texto)
                    exigir_acesso(self.usuario(), "publicar", ufs_no_texto(texto))
                colunas = dataset["colunas"]
                if any(c and c not in colunas for c in (componente.x, componente.y)):
                    raise BobError("PAINEL_INVALIDO", "O eixo informado não existe no resultado.")
                if componente.tipo in {"barras", "linhas", "mapa"} and (not componente.x or not componente.y):
                    raise BobError("PAINEL_INVALIDO", "Gráficos e mapas precisam dos campos x e y.")
                if componente.tipo == "mapa":
                    ufs = [uf_do_estado(str(linha[componente.x])) for linha in dataset["dados"]]
                    if None in ufs or len(set(ufs)) != len(ufs):
                        raise BobError("PAINEL_INVALIDO", "Mapas precisam de uma linha por UF brasileira válida.")
                    exigir_acesso(self.usuario(), "publicar", ufs)
                if componente.tipo == "indicador" and (not componente.y or len(dataset["dados"]) != 1):
                    raise BobError("PAINEL_INVALIDO", "Indicadores precisam de uma métrica e uma única linha.")
                if componente.y and any(not isinstance(linha[componente.y], (int, float)) and linha[componente.y] is not None for linha in dataset["dados"]):
                    raise BobError("PAINEL_INVALIDO", "A métrica visual deve ser numérica.")
                anterior = self._componentes.get(componente.id, {})
                igual = all(anterior.get(k) == v for k, v in componente.model_dump().items())
                novo = {**componente.model_dump(), "versao": anterior.get("versao", 0) + (0 if igual else 1)}
                if componente.acao:
                    novo["evidencia_em"] = dataset["atualizado_em"]
                atualizacoes[componente.id] = novo
            if len(set(self._componentes) | set(atualizacoes)) > 20:
                raise BobError("LIMITE_SESSAO", "A sessão permite até 20 componentes.")
            self._componentes.update(atualizacoes)
            return {"status": "publicado", "componentes": list(atualizacoes.values()), "renderizado": False}
        except ValidationError:
            return erro_contrato()
        except BobError as erro:
            return erro.resposta()

    def workspace(self):
        exigir_acesso(self.usuario(), "ler")
        return [{**c, "resultado": self.dados(c["dataset_id"])} for c in self._componentes.values()]

    def atualizar_componente(self, componente_id):
        """Não chama modelos. Reexecuta a mesma análise, com permissões atuais."""
        try:
            exigir_acesso(self.usuario(), "atualizar")
            componente = self._componentes.get(componente_id)
            if componente is None:
                raise BobError("ACESSO_RECURSO", "Componente indisponível nesta sessão ou fora do seu acesso.")
            antigo = self._datasets[componente["dataset_id"]]
            def verificar_graficos(dataset):
                for c in self._componentes.values():
                    if c["dataset_id"] == dataset["dataset_id"] and c["tipo"] == "grafico":
                        validar_grafico(c, dataset)

            novo = self._consultar(antigo["consulta"], "atualizar", antigo["dataset_id"], verificar_graficos)
            diferencas = []
            chave, metrica = componente.get("x"), componente.get("y")
            if metrica:
                serie = componente.get("serie")
                def grupo(linha):
                    valor = linha[chave] if chave else "total"
                    return (valor, linha[serie]) if serie else valor

                for dados in (antigo["dados"], novo["dados"]):
                    chaves = [grupo(linha) for linha in dados]
                    if len(set(chaves)) != len(chaves):
                        return {"status": "ok", "resultado": self._publico(novo), "mudancas": [],
                                "comparacao_indisponivel": "As coordenadas não identificam grupos únicos para comparar os resultados."}
                antes = {grupo(linha): linha[metrica] for linha in antigo["dados"]}
                for linha in novo["dados"]:
                    chave_grupo = grupo(linha)
                    valor = antes.get(chave_grupo)
                    if isinstance(valor, (int, float)) and isinstance(linha[metrica], (int, float)):
                        diferencas.append({"grupo": chave_grupo, "antes": valor, "agora": linha[metrica], "variacao": linha[metrica] - valor})
            return {"status": "ok", "resultado": self._publico(novo), "mudancas": diferencas}
        except BobError as erro:
            return erro.resposta()
