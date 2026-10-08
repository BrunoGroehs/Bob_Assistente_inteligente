"""Contratos, renderização e fluxo do agente visual para o catálogo de gráficos."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from typing import get_args

from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from bob.agents import Agentes, VISUAL
from bob.chart_templates import TEMPLATES, TemplateGrafico, validar_template
from bob.charts import criar_grafico
from bob.schemas import Componente, Usuario
from bob.session import SessaoLocal
from bob.tools import Backend
from test_backend import ModeloSimulado, criar_banco, tool


CATEGORIAS = [{"categoria": "Roupas", "valor": 12}, {"categoria": "Livros", "valor": 18}]
SERIES = [{"categoria": categoria, "canal": canal, "valor": valor}
          for categoria, canal, valor in [("Roupas", "App", 12), ("Roupas", "Site", 8), ("Livros", "App", 18), ("Livros", "Site", 10)]]
TEMPO = [{"mes": "2025-04", "valor": 20}, {"mes": "2025-05", "valor": 28}]
TEMPO_SERIES = [{"mes": mes, "canal": canal, "valor": valor}
                for mes, canal, valor in [("2025-04", "App", 12), ("2025-04", "Site", 8), ("2025-05", "App", 18), ("2025-05", "Site", 10)]]
PONTOS = [{"compras": 12, "receita": 1500, "categoria": "Roupas"}, {"compras": 18, "receita": 2400, "categoria": "Livros"}]


def exemplo(template):
    if template in {"linha_temporal", "area_temporal"}:
        dados, x, y, serie = TEMPO, "mes", "valor", None
    elif template in {"linhas_multiplas", "area_empilhada"}:
        dados, x, y, serie = TEMPO_SERIES, "mes", "valor", "canal"
    elif template == "dispersao":
        dados, x, y, serie = PONTOS, "compras", "receita", "categoria"
    elif template in {"barras_agrupadas", "barras_empilhadas", "composicao_percentual", "mapa_calor"}:
        dados, x, y, serie = SERIES, "categoria", "valor", "canal"
    else:
        dados, x, y, serie = CATEGORIAS, "categoria", "valor", None
    componente = {"id": "teste", "tipo": "grafico", "template": template, "dataset_id": "dataset",
                  "titulo": "Exemplo de teste", "x": x, "y": y, "serie": serie, "partes_exclusivas": True}
    dataset = {"colunas": list(dados[0]), "dados": deepcopy(dados), "truncado": False, "grupos_suprimidos": 0}
    return componente, dataset


class TemplatesTests(unittest.TestCase):
    def test_catalogo_contrato_prompt_e_renderizadores_cobrem_os_mesmos_templates(self):
        self.assertEqual(set(get_args(TemplateGrafico)), set(TEMPLATES))
        for template in TEMPLATES:
            with self.subTest(template=template):
                self.assertIn(template, VISUAL)
                componente, dataset = exemplo(template)
                Componente.model_validate(componente)
                antes = deepcopy(dataset)
                validar_template(componente, dataset)
                spec = criar_grafico(componente, dataset).to_dict(validate=True)
                self.assertIn("tooltip", spec["encoding"])
                self.assertEqual(dataset, antes)
                self.assertNotIn("transform", spec)  # Nenhuma nova agregação escondida.

    def test_agrupamento_percentual_e_calor_usam_os_campos_corretos(self):
        c, d = exemplo("barras_agrupadas")
        spec = criar_grafico(c, d).to_dict()
        self.assertEqual(spec["encoding"]["xOffset"]["field"], "canal")
        c["template"] = "composicao_percentual"
        spec = criar_grafico(c, d).to_dict()
        self.assertEqual(spec["encoding"]["y"]["stack"], "normalize")
        c["template"] = "mapa_calor"
        spec = criar_grafico(c, d).to_dict()
        self.assertEqual(spec["encoding"]["y"]["field"], "canal")
        self.assertEqual(spec["encoding"]["color"]["field"], "valor")

    def test_pizza_sem_furo_preserva_valores_e_selecao_por_categoria(self):
        c, d = exemplo("pizza")
        spec = criar_grafico(c, d).to_dict(validate=True)
        self.assertEqual(spec["mark"]["type"], "arc")
        self.assertEqual(spec["mark"]["innerRadius"], 0)
        self.assertEqual(spec["encoding"]["theta"]["field"], "valor")
        self.assertEqual(spec["encoding"]["theta"]["stack"], "zero")
        values = spec["data"].get("values")
        if values is None:
            values = spec["datasets"][spec["data"]["name"]]
        self.assertEqual([{k: r[k] for k in d["colunas"]} for r in values], d["dados"])
        self.assertEqual([r["__participacao"] for r in values], [0.4, 0.6])
        self.assertEqual(spec["encoding"]["tooltip"][-1]["format"], ".2%")


    def test_serie_metricas_datas_e_granularidade_incompativeis_sao_rejeitadas(self):
        c, d = exemplo("linhas_multiplas")
        for defeito in ("sem_serie", "campo_ausente", "data_invalida", "granularidade", "duplicado", "metrica_nula", "nao_finito"):
            with self.subTest(defeito=defeito):
                comp, dados = deepcopy(c), deepcopy(d)
                if defeito == "sem_serie": comp["serie"] = None
                if defeito == "campo_ausente": comp["y"] = "inexistente"
                if defeito == "data_invalida": dados["dados"][0]["mes"] = "2025-13"
                if defeito == "granularidade": dados["dados"][0]["mes"] = "2025-04-01"
                if defeito == "duplicado": dados["dados"].append(dados["dados"][0])
                if defeito == "metrica_nula": dados["dados"][0]["valor"] = None
                if defeito == "nao_finito": dados["dados"][0]["valor"] = float("inf")
                with self.assertRaises(ValueError): validar_template(comp, dados)

    def test_composicao_rejeita_total_zero_parcial_negativo_e_sem_declaracao(self):
        for template in ("pizza", "rosca", "composicao_percentual"):
            for defeito in ("zero", "suprimido", "truncado", "negativo", "sem_declaracao"):
                with self.subTest(template=template, defeito=defeito):
                    c, d = exemplo(template)
                    if defeito == "zero":
                        for linha in d["dados"]: linha["valor"] = 0
                    if defeito == "suprimido": d["grupos_suprimidos"] = 1
                    if defeito == "truncado": d["truncado"] = True
                    if defeito == "negativo": d["dados"][0]["valor"] = -1
                    if defeito == "sem_declaracao": c["partes_exclusivas"] = False
                    with self.assertRaises(ValueError): validar_template(c, d)

    def test_rosca_com_muitas_categorias_e_dispersao_sem_duas_metricas(self):
        for template in ("pizza", "rosca"):
            c, d = exemplo(template)
            d["dados"] = [{"categoria": str(i), "valor": i + 1} for i in range(9)]
            with self.assertRaises(ValueError): validar_template(c, d)
        c, d = exemplo("dispersao")
        d["dados"][0]["compras"] = "doze"
        with self.assertRaises(ValueError): validar_template(c, d)

    def test_template_nao_aceita_codigo_tipo_errado_ou_nome_desconhecido(self):
        c, _ = exemplo("barras_verticais")
        for alteracao in ({"template": "javascript_livre"}, {"javascript": "alert(1)"}, {"tipo": "tabela"}, {"template": None}):
            with self.assertRaises(ValidationError): Componente.model_validate({**c, **alteracao})

    def test_compatibilidade_de_barras_e_linhas_antigas(self):
        for tipo, dados, x in (("barras", CATEGORIAS, "categoria"), ("linhas", TEMPO, "mes")):
            c = {"tipo": tipo, "x": x, "y": "valor"}
            spec = criar_grafico(c, {"dados": dados}).to_dict(validate=True)
            self.assertEqual(spec["encoding"]["tooltip"][1]["field"], "valor")


class FluxoTemplatesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.banco = Path(self.temp.name) / "teste.db"
        criar_banco(self.banco)
        self.perfil = Usuario(id="demo", papel="analista", ufs=("SP", "RJ"))
        self.backend = Backend(self.banco, lambda: self.perfil)

    def test_refresh_revalida_todos_graficos_do_dataset_e_preserva_resultado(self):
        r = self.backend.consultar_dados("SELECT categoria, COUNT(*) AS compras FROM compras GROUP BY categoria", {"descricao": "Compras por categoria"})
        base = {"tipo": "grafico", "dataset_id": r["dataset_id"], "titulo": "Compras", "x": "categoria", "y": "compras"}
        self.assertEqual(self.backend.publicar_painel({"componentes": [
            {**base, "id": "ranking", "template": "barras_horizontais"},
            {**base, "id": "composicao", "template": "rosca", "partes_exclusivas": True}]})["status"], "publicado")
        with closing(sqlite3.connect(self.banco)) as db:
            for categoria in range(7):
                for cliente in range(6):
                    db.execute("INSERT INTO compras VALUES (?,?,?,?,?,?)", (10000 + categoria * 10 + cliente, 101 + cliente, "2025-05-10", 10, f"Categoria {categoria}", "App"))
            db.commit()
        # Mesmo atualizar a barra precisa preservar a rosca que compartilha seus dados.
        self.assertEqual(self.backend.atualizar_componente("ranking")["codigo"], "PAINEL_INVALIDO")
        self.assertEqual(self.backend.dados(r["dataset_id"])["dados"], r["dados"])
        self.assertEqual(self.backend.dados(r["dataset_id"])["atualizado_em"], r["atualizado_em"])

    def modelo(self):
        referencia = {}
        def pedir(messages):
            referencia["id"] = json.loads(messages[-1]["content"])["dataset_id"]
            return tool("criar_painel", {"dataset_ids": [referencia["id"]], "pedido": "Comparar categorias e canais"})
        def publicar_invalido(messages):
            return tool("publicar_painel", {"especificacao": {"componentes": [{
                "id": "comparacao", "tipo": "grafico", "template": "barras_agrupadas", "dataset_id": referencia["id"],
                "titulo": "Compras por categoria e canal", "x": "categoria", "y": "compras"}]}})
        def corrigir(messages):
            erro = json.loads(messages[-1]["content"])
            assert erro["codigo"] == "PAINEL_INVALIDO"
            return tool("publicar_painel", {"especificacao": {"componentes": [
                {"id": template, "tipo": "grafico", "template": template, "dataset_id": referencia["id"],
                 "titulo": "Compras por categoria e canal", "x": "categoria", "y": "compras", "serie": "canal", "partes_exclusivas": True}
                for template in ("barras_agrupadas", "barras_empilhadas", "composicao_percentual", "mapa_calor")
            ]}})
        return ModeloSimulado([
            tool("consultar_dados", {"sql": "SELECT categoria, canal, COUNT(*) AS compras FROM compras GROUP BY categoria, canal", "objetivo": {"descricao": "Compras por categoria e canal"}}),
            pedir, publicar_invalido, corrigir,
            {"role": "assistant", "content": "Templates publicados."},
            {"role": "assistant", "content": "Comparação criada com os dados consultados."}])

    def test_refresh_distingue_series_na_mesma_categoria(self):
        def adicionar(inicio):
            with closing(sqlite3.connect(self.banco)) as db:
                for i in range(6):
                    db.execute("INSERT INTO compras VALUES (?,?,?,?,?,?)", (inicio + i, 101 + i, "2025-05-10", 10, "Roupas", "Site"))
                db.commit()
        adicionar(20000)
        r = self.backend.consultar_dados("SELECT categoria, canal, COUNT(*) AS compras FROM compras GROUP BY categoria, canal", {"descricao": "Compras por categoria e canal"})
        self.backend.publicar_painel({"componentes": [{"id": "series", "tipo": "grafico", "template": "barras_agrupadas", "dataset_id": r["dataset_id"], "titulo": "Comparação", "x": "categoria", "y": "compras", "serie": "canal"}]})
        adicionar(21000)
        atualizado = self.backend.atualizar_componente("series")
        mudanca = next(m for m in atualizado["mudancas"] if m["grupo"] == ("Roupas", "Site"))
        self.assertEqual((mudanca["antes"], mudanca["agora"], mudanca["variacao"]), (6, 12, 6))

    def test_dispersao_com_coordenadas_repetidas_nao_inventa_variacao(self):
        r = self.backend.consultar_dados("SELECT categoria, COUNT(*) AS compras, SUM(valor) AS receita FROM compras GROUP BY categoria", {"descricao": "Compras e receita por categoria"})
        p = self.backend.publicar_painel({"componentes": [{"id": "pontos", "tipo": "grafico", "template": "dispersao", "dataset_id": r["dataset_id"], "titulo": "Relação de métricas", "x": "compras", "y": "receita"}]})
        self.assertEqual(p["status"], "publicado")
        atualizado = self.backend.atualizar_componente("pontos")
        self.assertEqual(atualizado["status"], "ok")
        self.assertEqual(atualizado["mudancas"], [])
        self.assertIn("comparacao_indisponivel", atualizado)

    def test_agente_visual_corrige_argumentos_e_publica_templates_na_interface(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"), default_timeout=30).run()
        sessao = SessaoLocal(self.banco, self.perfil)
        modelo = self.modelo()
        sessao.agentes = Agentes(sessao.backend, modelo)
        app.session_state["sessao"] = sessao
        app.chat_input[0].set_value("Compare compras por categoria e canal com gráficos.").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(sessao.backend.workspace()), 4)
        self.assertEqual(len(app.get("vega_lite_chart")), 4)
        self.assertEqual(len(modelo.chamadas), 6)
        sessao.backend.atualizar_componente("barras_agrupadas")
        self.assertEqual(len(modelo.chamadas), 6)
        enviados = json.dumps(modelo.chamadas)
        self.assertNotIn("Pessoa secreta", enviados)
        self.assertNotIn("segredo@example.com", enviados)


if __name__ == "__main__":
    unittest.main()
