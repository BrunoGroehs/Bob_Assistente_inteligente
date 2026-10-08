"""Repetições, conclusão limitada e protocolo de ferramentas em lotes."""

import json
import unittest

import httpx

from bob.agents import chave_consulta, rodar_agente
from bob.openrouter import OpenRouter
from bob.schemas import BobError
from test_backend import tool


class LoopTests(unittest.TestCase):
    def rodar(self, respostas, limite=8, executar=None, verificar=lambda: None):
        respostas = iter(respostas)
        self.enviadas, self.executadas = [], []
        class Modelo:
            def completar(_, messages, tools, *, concluir=False):
                self.enviadas.append((json.loads(json.dumps(messages)), concluir))
                return next(respostas)
        def executar_tool(nome, args):
            self.executadas.append((nome, args))
            return executar(nome, args) if executar else {"status": "ok", "dataset_id": "mesmo", "dados": [{"total": 12}]}
        self.messages = [{"role": "user", "content": "Analise os clientes"}]
        return rodar_agente(Modelo(), self.messages, [], executar_tool, verificar, limite)

    def consulta(self, sql="SELECT COUNT(*) AS total FROM clientes", descricao="Total"):
        return tool("consultar_dados", {"sql": sql, "objetivo": {"descricao": descricao}})

    def test_repeticao_nao_reexecuta_e_conclui_antes_do_limite(self):
        r = self.rodar([self.consulta(), self.consulta(descricao="Outra descrição"), self.consulta(), {"role": "assistant", "content": "Há 12 clientes."}])
        self.assertEqual(len(self.executadas), 1)
        self.assertEqual(len(self.enviadas), 4)
        self.assertTrue(self.enviadas[-1][1])
        self.assertFalse(any(m["role"] == "system" for m in self.messages))
        resultados = [json.loads(m["content"]) for m in self.messages if m["role"] == "tool"]
        self.assertEqual({r["dataset_id"] for r in resultados}, {"mesmo"})
        self.assertTrue(resultados[-1]["reutilizado"])
        self.assertEqual(r["status"], "ok")

    def test_ultima_rodada_reservada_sem_aumentar_limite(self):
        respostas = [self.consulta(f"SELECT COUNT(*) AS total{i} FROM clientes") for i in range(7)]
        r = self.rodar([*respostas, {"role": "assistant", "content": "Análise parcial concluída."}])
        self.assertEqual(len(self.enviadas), 8)
        self.assertEqual(len(self.executadas), 7)
        self.assertEqual(r["status"], "ok")
        self.assertTrue(self.enviadas[-1][1])

    def test_provedor_ignora_conclusao_nao_executa_tool_nem_corrompe_historico(self):
        r = self.rodar([self.consulta(), self.consulta()], limite=2)
        self.assertEqual(len(self.executadas), 1)
        self.assertEqual(r["status"], "erro")
        self.assertNotIn("tool_calls", self.messages[-1])

    def test_publicacao_repetida_nao_rechama_visual_e_preserva_painel(self):
        chamada = tool("criar_painel", {"dataset_ids": ["d"], "pedido": "Mapa"})
        r = self.rodar([chamada] * 4, executar=lambda *_: {"status": "publicado", "componentes": [{"id": "mapa"}]})
        self.assertEqual(len(self.executadas), 1)
        self.assertEqual(r["status"], "ok")
        self.assertTrue(r["publicacoes"])

    def test_lote_apos_tres_erros_tem_resposta_para_todas_as_tools(self):
        chamadas = [self.consulta(f"SELECT inexistente{i} FROM clientes")["tool_calls"][0] for i in range(4)]
        for i, chamada in enumerate(chamadas):
            chamada["id"] = f"call_{i}"
        r = self.rodar([{"role": "assistant", "tool_calls": chamadas}], executar=lambda *_: {"status": "erro", "mensagem": "SQL inválido"})
        self.assertEqual(r["status"], "erro")
        self.assertEqual(len(self.executadas), 3)
        self.assertEqual([m["tool_call_id"] for m in self.messages if m["role"] == "tool"], [f"call_{i}" for i in range(4)])

    def test_chave_preserva_literais_filtros_escopo_e_multiplos_comandos(self):
        def chave(sql, **objetivo):
            return chave_consulta({"sql": sql, "objetivo": {"descricao": "Teste", **objetivo}})
        sql = "SELECT estado, COUNT(*) AS total FROM clientes GROUP BY estado"
        self.assertEqual(chave(sql), chave(sql.lower().replace("select", "SELECT", 1)))
        self.assertNotEqual(chave(sql), chave(sql + "; DROP TABLE clientes"))
        self.assertNotEqual(chave(sql, ufs_solicitadas=["SP"]), chave(sql, ufs_solicitadas=["RJ"]))
        self.assertNotEqual(chave(sql + " HAVING estado='SP'"), chave(sql + " HAVING estado='RJ'"))

    def test_revogacao_impede_reutilizacao(self):
        checks = 0
        def verificar():
            nonlocal checks
            checks += 1
            if checks == 6:
                raise BobError("ACESSO_ALTERADO", "Perfil alterado")
        with self.assertRaises(BobError):
            self.rodar([self.consulta()] * 3, verificar=verificar)
        self.assertEqual(len(self.executadas), 1)

    def test_openrouter_desabilita_tools_mantendo_schema_na_conclusao(self):
        tools = [{"type": "function", "function": {"name": "teste", "parameters": {"type": "object"}}}]
        def responder(request):
            payload = json.loads(request.content)
            self.assertEqual(payload["tool_choice"], "none")
            self.assertEqual(payload["tools"], tools)
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "Concluído"}}]})
        OpenRouter(api_key="teste", transport=httpx.MockTransport(responder)).completar([], tools, concluir=True)


if __name__ == "__main__":
    unittest.main()
