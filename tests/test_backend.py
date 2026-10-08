"""Casos reais de autorização, privacidade, SQL, publicação e refresh."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

import httpx

from bob.access import exigir_acesso, proteger_texto, ufs_no_texto
from bob.agents import Agentes
from bob.database import abrir_recorte, descobrir_schema, executar
from bob.openrouter import OpenRouter
from bob.schemas import BobError, Usuario
from bob.tools import Backend


def criar_banco(caminho):
    with closing(sqlite3.connect(caminho)) as c:
        c.executescript("""
            CREATE TABLE clientes(id INTEGER PRIMARY KEY, nome TEXT, email TEXT, estado TEXT, nova_coluna_privada TEXT);
            CREATE TABLE compras(id INTEGER PRIMARY KEY, cliente_id INTEGER, data_compra TEXT, valor REAL, categoria TEXT, canal TEXT);
            CREATE TABLE suporte(id INTEGER PRIMARY KEY, cliente_id INTEGER, data_contato TEXT, tipo_contato TEXT, resolvido INTEGER, canal TEXT);
            CREATE TABLE campanhas_marketing(id INTEGER PRIMARY KEY, cliente_id INTEGER, data_envio TEXT, canal TEXT, interagiu INTEGER);
        """)
        for i in range(19):
            cliente = 101 + i
            estado = "São Paulo" if i < 12 else "RJ" if i < 18 else "Minas Gerais"
            c.execute("INSERT INTO clientes VALUES (?,?,?,?,?)", (cliente, "Pessoa secreta", "segredo@example.com", estado, "SEGREDO_NOVO"))
            c.execute("INSERT INTO compras VALUES (?,?,?,?,?,?)", (i * 2 + 1, cliente, "2025-05-10", 100, "Roupas", "App"))
            c.execute("INSERT INTO compras VALUES (?,?,?,?,?,?)", (i * 2 + 2, cliente, "2025-04-10", 50, "Livros", "Site"))
            c.execute("INSERT INTO suporte VALUES (?,?,?,?,?,?)", (i + 1, cliente, "2025-05-11", "Reclamação", 0, "Chat" if i % 2 == 0 else "Telefone"))
            for j in range(2):
                c.execute("INSERT INTO campanhas_marketing VALUES (?,?,?,?,?)", (i * 2 + j + 1, cliente, "2024-08-01", "WhatsApp", 1))
        c.commit()


def tool(nome, argumentos):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": nome, "arguments": json.dumps(argumentos, ensure_ascii=False)}}]}


class ModeloSimulado:
    def __init__(self, respostas):
        self.respostas = iter(respostas)
        self.chamadas = []

    def completar(self, messages, tools, *, concluir=False):
        self.chamadas.append(json.loads(json.dumps(messages)))
        resposta = next(self.respostas)
        return resposta(messages) if callable(resposta) else resposta


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.banco = Path(self.temp.name) / "teste.db"
        criar_banco(self.banco)
        self.perfil = Usuario(id="ana", papel="analista", ufs=("SP",))
        self.backend = Backend(self.banco, lambda: self.perfil, hoje=lambda: date(2025, 5, 15))

    def consultar(self, sql, **objetivo):
        return self.backend.consultar_dados(sql, {"descricao": "Análise agregada", **objetivo})

    def publicar(self, resultado, **campos):
        componente = {"id": "total", "tipo": "indicador", "dataset_id": resultado["dataset_id"], "titulo": "Clientes", "y": "total", **campos}
        return self.backend.publicar_painel({"componentes": [componente]})

    def test_recorte_remove_dados_privados_e_filtra_todos_relacionamentos(self):
        with closing(abrir_recorte(self.banco, self.perfil)) as c:
            schema = descobrir_schema(c)
            self.assertEqual(set(schema["clientes"]), {"id", "estado"})
            self.assertEqual(c.execute("SELECT COUNT(*) FROM clientes").fetchone()[0], 12)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM compras").fetchone()[0], 24)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM suporte").fetchone()[0], 12)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM campanhas_marketing").fetchone()[0], 24)
            self.assertEqual(c.execute("SELECT MAX(id) FROM clientes").fetchone()[0], 12)
            self.assertEqual(c.execute("SELECT DISTINCT estado FROM clientes").fetchone()[0], "SP")

    def test_consulta_geral_informa_escopo_e_conta_clientes_distintos(self):
        r = self.consultar("SELECT COUNT(DISTINCT cliente_id) AS total FROM campanhas_marketing WHERE canal='WhatsApp' AND interagiu=1")
        self.assertEqual(r["dados"], [{"total": 12}])
        self.assertEqual(r["escopo"], ["SP"])
        self.assertEqual(r["tipos"], {"total": "numero"})

    def test_resultado_suprimido_nao_revela_faixa_inferida_pelo_modelo(self):
        self.perfil = Usuario(id="ana", papel="analista", ufs=("MG",))
        modelo = ModeloSimulado([
            tool("consultar_dados", {"sql": "SELECT COUNT(DISTINCT id) AS clientes FROM clientes WHERE estado='MG'", "objetivo": {"descricao": "Total de clientes MG"}}),
            {"role": "assistant", "content": "Há menos de 5 clientes em MG."},
        ])
        resultado = Agentes(self.backend, modelo).conversar("Quantos clientes temos em MG?")
        self.assertEqual(resultado["status"], "ok")
        self.assertIn("protegido", resultado["resposta"])
        self.assertNotIn("5", resultado["resposta"])
        self.assertNotIn("menos", resultado["resposta"])
        self.assertEqual(len(modelo.chamadas), 2)

    def test_ufs_do_objetivo_fora_do_escopo_sao_negadas(self):
        r = self.consultar("SELECT COUNT(*) AS total FROM clientes", ufs_solicitadas=["RJ"])
        self.assertEqual(r["codigo"], "ACESSO_ESCOPO")
        self.assertNotIn("dados", r)

    def test_sql_nao_pode_solicitar_uf_proibida(self):
        for uf in ("RJ", "Rio de Janeiro"):
            with self.subTest(uf=uf):
                self.assertEqual(self.consultar(f"SELECT COUNT(*) AS total FROM clientes WHERE estado='{uf}'")["codigo"], "ACESSO_ESCOPO")

    def test_leitor_e_administrador_nao_herdam_consultas(self):
        for papel in ("leitor", "administrador"):
            self.perfil = Usuario(id="ana", papel=papel, ufs=("SP",))
            self.assertEqual(self.consultar("SELECT COUNT(*) AS total FROM clientes")["codigo"], "ACESSO_PAPEL")

    def test_administracao_nao_exige_escopo_analitico(self):
        exigir_acesso(Usuario(id="admin", papel="administrador"), "gerenciar_acessos")

    def test_alterar_resposta_nao_modifica_resultado_armazenado(self):
        r = self.consultar("SELECT COUNT(*) AS total FROM clientes")
        r["dados"][0]["total"] = 999
        self.assertEqual(self.backend.dados(r["dataset_id"])["dados"], [{"total": 12}])

    def test_sem_escopo_nao_ha_acesso(self):
        self.perfil = Usuario(id="ana", papel="analista", ufs=())
        self.assertEqual(self.consultar("SELECT COUNT(*) AS total FROM clientes")["status"], "acesso_negado")

    def test_sql_individual_e_operacoes_perigosas_sao_bloqueados(self):
        ataques = [
            "SELECT * FROM clientes", "SELECT id FROM clientes", "SELECT MIN(id) AS total FROM clientes",
            "SELECT id+COUNT(*) AS total FROM clientes", "SELECT id, COUNT(*) AS total FROM clientes GROUP BY id",
            "SELECT COUNT(*) AS total FROM clientes WHERE id=1", "SELECT COUNT(id+1) AS total FROM clientes",
            "SELECT COUNT(CASE WHEN id=1 THEN 1 END) AS total FROM clientes",
            "SELECT COUNT(*) FROM clientes; SELECT COUNT(*) FROM compras",
            "DELETE FROM clientes", "ATTACH DATABASE 'outra.db' AS privada",
            "SELECT COUNT(*), load_extension('arquivo') FROM clientes",
            "SELECT COUNT(*) FROM sqlite_master", "SELECT COUNT(*) FROM clientes UNION SELECT COUNT(*) FROM compras",
            "WITH segredo AS (SELECT id FROM clientes) SELECT COUNT(*) FROM segredo",
            "SELECT COUNT(*) FROM clientes WHERE id IN (SELECT cliente_id FROM compras)",
            "SELECT COUNT(*) FROM compras p JOIN suporte s ON p.cliente_id=s.cliente_id",
            "SELECT COUNT(*) FROM clientes c JOIN compras p ON c.id=p.cliente_id JOIN suporte s ON c.id=s.cliente_id",
            "SELECT COUNT(*) FROM clientes c JOIN compras p ON 1=1",
        ]
        for sql in ataques:
            with self.subTest(sql=sql):
                self.assertNotEqual(self.consultar(sql)["status"], "ok")

    def test_barreira_sqlite_bloqueia_leitura_externa_sem_validator(self):
        with closing(abrir_recorte(self.banco, self.perfil)) as c:
            schema = descobrir_schema(c)
            for sql in ("SELECT COUNT(*) FROM sqlite_master", "ATTACH DATABASE 'outra.db' AS privada", "DELETE FROM clientes"):
                with self.subTest(sql=sql), self.assertRaises(BobError):
                    executar(c, sql, {}, schema)

    def test_colunas_privadas_e_novas_colunas_nao_sao_expostas(self):
        for coluna in ("nome", "email", "nova_coluna_privada"):
            with self.subTest(coluna=coluna):
                r = self.consultar(f"SELECT COUNT({coluna}) AS total FROM clientes")
                self.assertEqual(r["status"], "erro")
        contexto = json.dumps(self.backend.contexto())
        self.assertNotIn("SEGREDO_NOVO", contexto)
        self.assertNotIn("nova_coluna_privada", contexto)

    def test_celulas_pequenas_sao_suprimidas(self):
        r = self.consultar("SELECT categoria, COUNT(*) AS total FROM compras WHERE valor > 90 AND cliente_id > 2 GROUP BY categoria")
        self.assertEqual(r["status"], "erro")
        self.perfil = Usuario(id="ana", papel="analista", ufs=("RJ",))
        r = self.consultar("SELECT canal, COUNT(*) AS total FROM suporte GROUP BY canal")
        self.assertEqual(r["dados"], [])
        self.assertEqual(r["grupos_suprimidos"], 2)

    def test_ausencia_de_registros_nao_e_acesso_negado(self):
        r = self.consultar("SELECT COUNT(*) AS total FROM compras WHERE data_compra >= '2030-01-01'")
        self.assertEqual(r["dados"], [{"total": 0}])
        self.assertEqual(r["status"], "ok")

    def test_sql_invalido_tem_erro_corrigivel_sem_dados_brutos(self):
        r = self.consultar("SELECT COUNT(*) AS total FROM compras WHERE campo_inexistente=0")
        self.assertEqual(r["codigo"], "SQL_INVALIDO")
        self.assertNotIn("segredo", json.dumps(r))

    def test_tendencia_mensal_e_media_por_comprador(self):
        r = self.consultar("SELECT STRFTIME('%Y-%m', data_compra) AS mes, COUNT(*) AS total FROM compras GROUP BY STRFTIME('%Y-%m', data_compra) ORDER BY mes")
        self.assertEqual(r["dados"], [{"mes": "2025-04", "total": 12}, {"mes": "2025-05", "total": 12}])
        r = self.consultar("SELECT categoria, COUNT(*) * 1.0 / COUNT(DISTINCT cliente_id) AS media FROM compras GROUP BY categoria")
        self.assertTrue(all(linha["media"] == 1.0 for linha in r["dados"]))

    def test_join_permitido_conta_clientes_por_estado(self):
        r = self.consultar("SELECT c.estado, COUNT(DISTINCT c.id) AS total FROM clientes c JOIN compras p ON p.cliente_id=c.id WHERE p.canal='App' AND p.data_compra >= '2025-05-01' AND p.data_compra < '2025-06-01' GROUP BY c.estado ORDER BY total DESC LIMIT 5")
        self.assertEqual(r["dados"], [{"estado": "SP", "total": 12}])

    def test_reclamacao_exige_filtro_e_cliente_distinto(self):
        r = self.consultar("SELECT canal, COUNT(*) AS total FROM suporte WHERE tipo_contato='Reclamação' AND resolvido=0 GROUP BY canal")
        self.assertEqual(sum(linha["total"] for linha in r["dados"]), 12)

    def test_publicacao_valida_e_idempotente(self):
        r = self.consultar("SELECT COUNT(*) AS total FROM clientes")
        self.assertEqual(self.publicar(r)["status"], "publicado")
        self.publicar(r)
        self.assertEqual(len(self.backend.workspace()), 1)
        self.assertEqual(self.backend.workspace()[0]["versao"], 1)
        self.assertEqual(self.publicar(r, titulo="Novo título")["componentes"][0]["versao"], 2)

    def test_painel_rejeita_codigo_coluna_inexistente_e_metrica_textual(self):
        r = self.consultar("SELECT estado, COUNT(*) AS total FROM clientes GROUP BY estado")
        for campos in ({"tipo": "html"}, {"y": "nao_existe"}, {"tipo": "barras", "x": "estado", "y": "estado"}, {"tipo": "linhas"}):
            with self.subTest(campos=campos):
                self.assertEqual(self.publicar(r, **campos)["status"], "erro")
        self.assertEqual(self.backend.workspace(), [])

    def test_resultado_nao_pode_ser_aberto_por_outra_sessao(self):
        r = self.consultar("SELECT COUNT(*) AS total FROM clientes")
        outra = Backend(self.banco, lambda: Usuario(id="bia", papel="analista", ufs=("RJ",)))
        with self.assertRaises(BobError):
            outra.dados(r["dataset_id"])

    def test_mudanca_de_escopo_limpa_resultados_paineis_e_historico(self):
        r = self.consultar("SELECT COUNT(*) AS total FROM clientes")
        self.publicar(r)
        self.backend.conversas.append([{"role": "assistant", "content": "Dado anterior"}])
        self.perfil = Usuario(id="ana", papel="analista", ufs=("RJ",))
        self.assertEqual(self.backend.atualizar_componente("total")["codigo"], "ACESSO_RECURSO")
        self.assertEqual(self.backend.workspace(), [])
        self.assertEqual(self.backend.conversas, [])

    def test_refresh_le_novos_dados_e_informa_diferenca(self):
        r = self.consultar("SELECT COUNT(*) AS total FROM compras")
        self.publicar(r)
        with closing(sqlite3.connect(self.banco)) as c:
            c.execute("INSERT INTO compras VALUES (99,101,'2025-05-12',200,'Roupas','App')")
            c.commit()
        novo = self.backend.atualizar_componente("total")
        self.assertEqual(novo["resultado"]["dados"], [{"total": 25}])
        self.assertEqual(novo["mudancas"][0]["variacao"], 1)
        self.assertEqual(novo["resultado"]["dataset_id"], r["dataset_id"])

    def test_periodo_relativo_recalcula_no_refresh(self):
        r = self.consultar("SELECT COUNT(*) AS total FROM compras WHERE data_compra >= :inicio AND data_compra < :fim", ultimos_dias=30)
        self.assertEqual(r["parametros"], {"inicio": "2025-04-16", "fim": "2025-05-16"})
        self.publicar(r)
        self.backend.hoje = lambda: date(2025, 6, 15)
        novo = self.backend.atualizar_componente("total")
        self.assertEqual(novo["resultado"]["dados"], [{"total": 0}])
        self.assertEqual(novo["resultado"]["parametros"]["inicio"], "2025-05-17")

    def test_periodo_relativo_nao_aceita_parametros_so_em_comentarios(self):
        for sql in ("SELECT COUNT(*) AS total FROM compras -- :inicio :fim", "SELECT COUNT(*) AS total FROM compras WHERE data_compra >= :inicio AND data_compra < :fim OR canal='App'"):
            with self.subTest(sql=sql):
                self.assertEqual(self.consultar(sql, ultimos_dias=30)["codigo"], "PERIODO_INVALIDO")

    def test_publicacao_nao_pode_inventar_regiao_ou_identificador_pessoal(self):
        r = self.consultar("SELECT COUNT(*) AS total FROM clientes")
        self.assertEqual(self.publicar(r, titulo="Clientes de RJ")["status"], "acesso_negado")
        self.assertEqual(self.publicar(r, titulo="segredo@example.com")["codigo"], "DADOS_PESSOAIS")

    def test_banco_indisponivel_devolve_erro_controlado(self):
        self.backend.banco = Path(self.temp.name) / "inexistente.db"
        self.assertEqual(self.consultar("SELECT COUNT(*) AS total FROM clientes")["codigo"], "BANCO_INDISPONIVEL")

    def test_refresh_com_erro_preserva_dados_anteriores(self):
        r = self.consultar("SELECT COUNT(*) AS total FROM compras")
        self.publicar(r)
        with closing(sqlite3.connect(self.banco)) as c:
            c.execute("ALTER TABLE compras RENAME TO compras_indisponivel")
            c.commit()
        self.assertEqual(self.backend.atualizar_componente("total")["status"], "erro")
        self.assertEqual(self.backend.dados(r["dataset_id"])["dados"], [{"total": 24}])

    def test_dados_pessoais_no_texto_sao_bloqueados_mas_canal_email_e_valido(self):
        for texto in ("Liste os nomes dos clientes", "Cliente segredo@example.com", "CPF 123.456.789-00"):
            with self.subTest(texto=texto), self.assertRaises(BobError):
                proteger_texto(texto)
        self.assertEqual(proteger_texto("Quantas campanhas via E-mail?"), "Quantas campanhas via E-mail?")

    def test_ufs_por_nome_e_sigla(self):
        self.assertEqual(ufs_no_texto("Clientes de São Paulo e RJ"), {"SP", "RJ"})
        self.assertEqual(ufs_no_texto("Clientes de Mato Grosso do Sul"), {"MS"})
        self.assertEqual(ufs_no_texto("Compare as compras para maio"), set())

    def test_pedido_proibido_nao_chama_modelo(self):
        modelo = ModeloSimulado([])
        r = Agentes(self.backend, modelo).conversar("Quantos clientes de MG compraram?")
        self.assertEqual(r["status"], "acesso_negado")
        self.assertEqual(modelo.chamadas, [])

    def test_modelo_recebe_erro_sql_e_corrige(self):
        modelo = ModeloSimulado([
            tool("consultar_dados", {"sql": "SELECT COUNT(*) FROM suporte WHERE nao_existe=1", "objetivo": {"descricao": "Contar atendimentos"}}),
            tool("consultar_dados", {"sql": "SELECT COUNT(*) AS total FROM suporte", "objetivo": {"descricao": "Contar atendimentos"}}),
            {"role": "assistant", "content": "São 12 atendimentos no seu escopo SP."},
        ])
        r = Agentes(self.backend, modelo).conversar("Quantos atendimentos há?")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(len(modelo.chamadas), 3)
        self.assertIn("SQL_INVALIDO", json.dumps(modelo.chamadas[1]))

    def test_modelo_nao_pode_contornar_bloqueio_da_tool(self):
        modelo = ModeloSimulado([tool("consultar_dados", {"sql": "SELECT COUNT(*) AS total FROM clientes WHERE estado='RJ'", "objetivo": {"descricao": "Contar clientes"}})])
        r = Agentes(self.backend, modelo).conversar("Quantos clientes há?")
        self.assertEqual(r["status"], "acesso_negado")
        self.assertEqual(len(modelo.chamadas), 1)

    def test_fluxo_dois_agentes_publica_e_refresh_nao_chama_modelo(self):
        def pedir_painel(messages):
            dataset = json.loads(messages[-1]["content"])["dataset_id"]
            return tool("criar_painel", {"dataset_ids": [dataset], "pedido": "Indicador de clientes"})

        def publicar(messages):
            dataset = json.loads(messages[-1]["content"])["dataset_ids"][0]
            return tool("publicar_painel", {"especificacao": {"componentes": [{"id": "clientes", "tipo": "indicador", "dataset_id": dataset, "titulo": "Clientes", "y": "total"}]}})

        modelo = ModeloSimulado([
            tool("consultar_dados", {"sql": "SELECT COUNT(*) AS total FROM clientes", "objetivo": {"descricao": "Contar clientes"}}),
            pedir_painel, publicar,
            {"role": "assistant", "content": "Especificação publicada."},
            {"role": "assistant", "content": "São 12 clientes de SP. Indicador publicado."},
        ])
        r = Agentes(self.backend, modelo).conversar("Crie um indicador com o total de clientes")
        self.assertEqual(len(r["workspace"]), 1)
        self.assertEqual(len(r["publicacoes"]), 1)
        self.assertEqual(len(modelo.chamadas), 5)
        self.backend.atualizar_componente("clientes")
        self.assertEqual(len(modelo.chamadas), 5)
        enviados = json.dumps(modelo.chamadas)
        self.assertNotIn("Pessoa secreta", enviados)
        self.assertNotIn("segredo@example.com", enviados)
        self.assertNotIn("SEGREDO_NOVO", enviados)

    def test_tres_falhas_sql_encerram_investigacao(self):
        chamada = tool("consultar_dados", {"sql": "SELECT * FROM clientes", "objetivo": {"descricao": "Análise"}})
        modelo = ModeloSimulado([chamada] * 3)
        r = Agentes(self.backend, modelo).conversar("Quantos clientes há?")
        self.assertEqual(r["status"], "erro")
        self.assertEqual(len(modelo.chamadas), 3)

    def test_cache_nao_ignora_uf_proibida_na_descricao_do_objetivo(self):
        sql = "SELECT COUNT(*) AS total FROM clientes"
        modelo = ModeloSimulado([
            tool("consultar_dados", {"sql": sql, "objetivo": {"descricao": "Total de clientes"}}),
            tool("consultar_dados", {"sql": sql, "objetivo": {"descricao": "Total de clientes no RJ"}}),
        ])
        r = Agentes(self.backend, modelo).conversar("Conte os clientes permitidos")
        self.assertEqual(r["status"], "acesso_negado")
        self.assertEqual(len([e for e in self.backend.eventos if e.get("dataset_id")]), 1)

    def test_permissoes_alteradas_durante_modelo_invalidam_resposta(self):
        def mudar_perfil(messages):
            self.perfil = Usuario(id="ana", papel="analista", ufs=("RJ",))
            return {"role": "assistant", "content": "Resposta antiga"}
        modelo = ModeloSimulado([mudar_perfil])
        r = Agentes(self.backend, modelo).conversar("Quantos clientes há?")
        self.assertEqual(r["codigo"], "ACESSO_ALTERADO")
        self.assertNotEqual(r["resposta"], "Resposta antiga")

    def test_visual_sem_tool_nao_e_considerado_publicado(self):
        from bob.schemas import PedidoPainel
        r = self.consultar("SELECT COUNT(*) AS total FROM clientes")
        modelo = ModeloSimulado([{"role": "assistant", "content": "Criei um painel."}])
        pedido = PedidoPainel(dataset_ids=[r["dataset_id"]], pedido="Indicador")
        resultado = Agentes(self.backend, modelo).criar_painel(pedido, lambda: None)
        self.assertEqual(resultado["codigo"], "PAINEL_NAO_PUBLICADO")
        self.assertEqual(self.backend.workspace(), [])

    def test_openrouter_sucesso_registra_tokens_e_descarta_reasoning(self):
        client = OpenRouter(api_key="CHAVE_DE_TESTE", transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "Resposta", "reasoning": "Interno"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})))
        resposta = client.completar([], [])
        self.assertEqual(resposta, {"role": "assistant", "content": "Resposta"})
        self.assertEqual(client.uso[0]["tokens_entrada"], 10)

    def test_openrouter_timeout_nao_reenvia_a_chamada(self):
        chamadas = []
        def timeout(request):
            chamadas.append(request)
            raise httpx.ReadTimeout("CHAVE_DE_TESTE")
        client = OpenRouter(api_key="CHAVE_DE_TESTE", transport=httpx.MockTransport(timeout))
        with self.assertRaises(BobError) as erro:
            client.completar([], [])
        self.assertEqual(erro.exception.codigo, "MODELO_TIMEOUT")
        self.assertEqual(len(chamadas), 1)
        self.assertNotIn("CHAVE_DE_TESTE", str(erro.exception))

    def test_openrouter_contrato_e_erro_sem_vazar_segredos(self):
        def responder(request):
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "qwen/qwen3.6-plus")
            self.assertNotIn("parallel_tool_calls", payload)
            self.assertEqual(payload["provider"]["data_collection"], "deny")
            return httpx.Response(401, json={"error": "TOKEN_SECRETO"})
        client = OpenRouter(api_key="CHAVE_DE_TESTE", transport=httpx.MockTransport(responder))
        with self.assertRaises(BobError) as erro:
            client.completar([], [])
        self.assertNotIn("TOKEN_SECRETO", str(erro.exception))
        self.assertNotIn("CHAVE_DE_TESTE", str(erro.exception))


if __name__ == "__main__":
    unittest.main()
