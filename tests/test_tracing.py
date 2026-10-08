"""Rastreia chamadas reais das funções com respostas do modelo simuladas."""

import json
import tempfile
import unittest
from pathlib import Path

from bob.agents import Agentes
from bob.schemas import BobError, Usuario
from bob.session import SessaoLocal
from test_backend import ModeloSimulado, criar_banco, tool


class TracingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        banco = Path(self.temp.name) / "teste.db"
        criar_banco(banco)
        self.sessao = SessaoLocal(banco, Usuario(id="teste", papel="analista", ufs=("SP",)))

    def test_erro_correcao_visual_publicacao_e_resposta_na_ordem(self):
        def visual(messages):
            dataset = json.loads(messages[-1]["content"])["dataset_id"]
            return tool("criar_painel", {"dataset_ids": [dataset], "pedido": "Indicador de clientes"})

        def publicar(messages):
            dataset = json.loads(messages[-1]["content"])["dataset_ids"][0]
            return tool("publicar_painel", {"especificacao": {"componentes": [{"id": "clientes", "tipo": "indicador", "dataset_id": dataset, "titulo": "Clientes", "y": "total"}]}})

        invalida = "SELECT COUNT(*) AS total FROM clientes WHERE nao_existe=1"
        valida = "SELECT COUNT(*) AS total FROM clientes"
        modelo = ModeloSimulado([
            tool("consultar_dados", {"sql": invalida, "objetivo": {"descricao": "Contar clientes"}}),
            tool("consultar_dados", {"sql": valida, "objetivo": {"descricao": "Contar clientes"}}),
            visual, publicar,
            {"role": "assistant", "content": "Publicação concluída."},
            {"role": "assistant", "content": "Indicador publicado com 12 clientes de SP."},
        ])
        self.sessao.agentes.client = modelo
        resultado = self.sessao.conversar("Crie um indicador de clientes")
        etapas = resultado["rastreamento"]["etapas"]
        self.assertEqual([e["numero"] for e in etapas], list(range(1, len(etapas) + 1)))
        chamadas = [e for e in etapas if e["tipo"] == "tool_chamada"]
        self.assertEqual([e["ferramenta"] for e in chamadas], ["consultar_dados", "consultar_dados", "criar_painel", "publicar_painel"])
        self.assertEqual([e["entrada"]["sql"] for e in chamadas[:2]], [invalida, valida])
        retornos = [e for e in etapas if e["tipo"] == "tool_retorno"]
        self.assertEqual(retornos[0]["saida"]["codigo"], "SQL_INVALIDO")
        self.assertEqual(retornos[1]["saida"]["status"], "ok")
        self.assertEqual(retornos[1]["saida"]["quantidade_linhas"], 1)
        self.assertEqual(retornos[2]["agente"], "visual")  # publicação interna termina antes do criar_painel
        self.assertEqual(retornos[2]["saida"]["status"], "publicado")
        for retorno in retornos:
            chamada = next(e for e in chamadas if e["numero"] == retorno["chamada"])
            self.assertEqual(retorno["ferramenta"], chamada["ferramenta"])
            self.assertIn("duracao_ms", retorno)
        transferencias = [e for e in etapas if e["tipo"] == "transferencia"]
        self.assertEqual([(e["agente"], e["destino"]) for e in transferencias], [("principal", "visual"), ("visual", "principal")])
        self.assertEqual(etapas[-1]["tipo"], "resposta_final")
        self.assertEqual(etapas[-1]["resposta"], resultado["resposta"])
        self.assertEqual(self.sessao.mensagens[-1]["rastreamento"], resultado["rastreamento"])
        self.assertNotIn("Pessoa secreta", json.dumps(etapas))
        self.assertNotIn("dados", retornos[1]["saida"])
        self.assertEqual(self.sessao.reiniciar().mensagens, [])

    def test_json_invalido_e_volta_ao_agente_sem_perder_tentativa(self):
        chamada = tool("consultar_dados", {})
        chamada["tool_calls"][0]["function"]["arguments"] = "{json invalido"
        modelo = ModeloSimulado([chamada, {"role": "assistant", "content": "Não consegui executar a consulta."}])
        self.sessao.agentes.client = modelo
        etapas = self.sessao.conversar("Consultar clientes")["rastreamento"]["etapas"]
        entrada = next(e for e in etapas if e["tipo"] == "tool_chamada")
        self.assertIn("json_invalido", entrada["entrada"])
        retorno = next(e for e in etapas if e["tipo"] == "tool_retorno")
        self.assertEqual(retorno["saida"]["codigo"], "ARGUMENTOS_INVALIDOS")
        self.assertTrue(any(e["tipo"] == "agente_chamada" and e["numero"] > retorno["numero"] for e in etapas))

    def test_timeout_registrado_e_dados_sensiveis_omitidos(self):
        class ModeloComErro:
            api_key = "CHAVE_SECRETA_TESTE"
            def completar(self, messages, tools):
                raise BobError("MODELO_TIMEOUT", "Timeout do modelo")

        self.sessao.agentes.client = ModeloComErro()
        resultado = self.sessao.conversar("Analisar clientes CHAVE_SECRETA_TESTE")
        self.assertEqual(resultado["status"], "erro")
        self.assertNotIn("CHAVE_SECRETA_TESTE", json.dumps(resultado["rastreamento"]))
        self.assertTrue(any(e["tipo"] == "agente_retorno" and e.get("codigo") == "MODELO_TIMEOUT" for e in resultado["rastreamento"]["etapas"]))
        proibido = self.sessao.conversar("Escreva para segredo@example.com")
        self.assertNotIn("segredo@example.com", json.dumps(proibido["rastreamento"]))
        self.assertEqual(proibido["rastreamento"]["etapas"][-1]["status"], "erro")

    def test_turnos_isolados_e_revogacao_descarta_evidencias_anteriores(self):
        modelo = ModeloSimulado([{"role": "assistant", "content": "Primeira"}, {"role": "assistant", "content": "Segunda"}])
        self.sessao.agentes.client = modelo
        primeira = self.sessao.conversar("Primeira pergunta")["rastreamento"]
        segunda = self.sessao.conversar("Segunda pergunta")["rastreamento"]
        self.assertNotEqual(primeira["id"], segunda["id"])
        self.assertNotIn("Primeira pergunta", json.dumps(segunda))

        def revogar(messages):
            self.sessao.perfil = Usuario(id="teste", papel="analista", ufs=("RJ",))
            return {"role": "assistant", "content": "Resposta que não deve aparecer"}

        self.sessao.agentes.client = ModeloSimulado([revogar])
        resultado = self.sessao.agentes.conversar("Consultar clientes")
        self.assertEqual(resultado["codigo"], "ACESSO_ALTERADO")
        self.assertEqual(len(resultado["rastreamento"]["etapas"]), 1)
        self.assertNotIn("schema", json.dumps(resultado["rastreamento"]))


if __name__ == "__main__":
    unittest.main()
