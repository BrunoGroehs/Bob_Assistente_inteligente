"""Fluxos da interface simulados pelo Streamlit, sem consumir chamadas de IA."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
import bob.session
from bob.schemas import Usuario
from test_backend import ModeloSimulado, tool


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.app = AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"), default_timeout=30).run()
        self.assertEqual(len(self.app.exception), 0)

    def botao(self, label):
        return next(b for b in self.app.button if b.label == label)

    def publicar_com_ia(self):
        def pedir_painel(messages):
            dataset = json.loads(messages[-1]["content"])["dataset_id"]
            return tool("criar_painel", {"dataset_ids": [dataset], "pedido": "Mapa, tabela e ação"})

        def publicar(messages):
            dataset = json.loads(messages[-1]["content"])["dataset_ids"][0]
            return tool("publicar_painel", {"especificacao": {"componentes": [
                {"id": "mapa", "tipo": "mapa", "dataset_id": dataset, "titulo": "Clientes por estado", "x": "estado", "y": "clientes"},
                {"id": "tabela", "tipo": "tabela", "dataset_id": dataset, "titulo": "Distribuição de clientes"},
                {"id": "acao", "tipo": "acao", "dataset_id": dataset, "titulo": "Planejar relacionamento", "acao": {
                    "descricao": "Avaliar uma campanha com base no escopo consultado.", "publico": "Segmentos por estado", "canal": "A definir",
                    "mensagem": "Olá! Gostaria de conhecer as novidades?"}}
            ]}})

        modelo = ModeloSimulado([
            tool("consultar_dados", {"sql": "SELECT estado, COUNT(*) AS clientes FROM clientes GROUP BY estado", "objetivo": {"descricao": "Clientes por estado"}}),
            pedir_painel, publicar,
            {"role": "assistant", "content": "Mapa, tabela e sugestão publicados."},
            {"role": "assistant", "content": "Organizei os resultados no workspace."},
        ])
        self.app.session_state["sessao"].agentes.client = modelo
        self.app.chat_input[0].set_value("Crie um mapa, tabela e sugestões de relacionamento.").run()
        self.assertEqual(len(self.app.exception), 0)
        return modelo

    def test_workspace_comeca_vazio_sem_consultas_ou_atalhos(self):
        sessao = self.app.session_state["sessao"]
        self.assertEqual(sessao.backend.workspace(), [])
        self.assertEqual(sessao.backend.eventos, [])
        self.assertFalse(any(b.label == "Explorar base" for b in self.app.button))
        self.assertEqual(len([b for b in self.app.button if b.key and b.key.startswith("sugestao_")]), 4)
        self.assertEqual(len(self.app.chat_input), 1)
        # Há um único compositor no painel; apenas o histórico tem rolagem.
        self.assertEqual(len(self.app.main.chat_input), 1)
        self.assertEqual(len(self.app.selectbox), 0)

    def test_ia_cria_componentes_e_nova_sessao_limpa(self):
        modelo = self.publicar_com_ia()
        self.assertEqual(len(self.app.exception), 0)
        sessao = self.app.session_state["sessao"]
        self.assertEqual(len(sessao.backend.workspace()), 3)
        self.assertEqual(sessao.client.uso, [])
        self.assertEqual(len(modelo.chamadas), 5)
        self.botao("Nova sessão").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(self.app.session_state["sessao"].backend.workspace(), [])

    def test_engrenagem_salva_restricao_e_limpa_conversa_e_workspace(self):
        self.publicar_com_ia()
        sessao = self.app.session_state["sessao"]
        sessao.mensagens.append({"role": "user", "content": "Mensagem antiga"})
        next(b for b in self.app.button if b.proto.icon == ":material/settings:").click().run()
        self.app.multiselect[0].set_value(["SP"])
        self.botao("Salvar e reiniciar sessão").click().run()
        self.assertEqual(len(self.app.exception), 0)
        novo = self.app.session_state["sessao"]
        self.assertEqual(novo.perfil.ufs, ("SP",))
        self.assertEqual(novo.mensagens, [])
        self.assertEqual(novo.backend.conversas, [])
        self.assertEqual(novo.backend.workspace(), [])
        self.publicar_com_ia()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(novo.backend.workspace()[0]["resultado"]["escopo"], ["SP"])

    def test_leitor_desabilita_consulta_sem_excecao(self):
        next(b for b in self.app.button if b.proto.icon == ":material/settings:").click().run()
        next(s for s in self.app.selectbox if s.label == "Papel").set_value("leitor")
        self.botao("Salvar e reiniciar sessão").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertTrue(self.app.chat_input[0].disabled)
        self.assertEqual(self.app.session_state["sessao"].backend.workspace(), [])

    def test_organizar_cartoes_e_concluir_acao_sem_chamar_modelo(self):
        modelo = self.publicar_com_ia()
        sessao = self.app.session_state["sessao"]
        sessao.posicionar({"acao": {"x": 50, "y": 100}})
        self.app.run()
        self.assertEqual(sessao.posicoes, {"acao": {"x": 50, "y": 100}})
        self.assertEqual(len(self.app.selectbox), 0)
        self.assertEqual(len(self.app.toggle), 0)
        self.botao("Marcar como concluída").click().run()
        self.assertEqual(sessao.acoes_concluidas, {"acao": 1})
        self.assertEqual(len(modelo.chamadas), 5)
        self.assertEqual(len(self.app.exception), 0)

    def test_encaixar_preserva_cartoes_dados_e_conversa_sem_chamar_modelo(self):
        modelo = self.publicar_com_ia()
        sessao = self.app.session_state['sessao']
        sessao.posicionar({'mapa': {'x': 130, 'y': 200}, 'tabela': {'x': 130, 'y': 200}})
        componentes, mensagens = sessao.componentes(), list(sessao.mensagens)
        self.app.button(key='encaixar_cartoes').click().run()
        self.assertEqual(sessao.posicoes, {})
        self.assertEqual(sessao.posicoes_manuais, set())
        self.assertEqual(sessao.componentes(), componentes)
        self.assertEqual(sessao.mensagens, mensagens)
        self.assertEqual(len(modelo.chamadas), 5)
        self.assertEqual(len(self.app.exception), 0)

    def test_sessao_antiga_e_migrada_mesmo_com_revision_atual(self):
        # Reproduz um objeto retido antes de componentes() existir na classe.
        antiga = type("SessaoLocal", (), {})()
        antiga.perfil = Usuario(id="simulacao_local", papel="analista", ufs=("SP",))
        self.app.session_state["sessao"] = antiga
        self.app.session_state["workspace_revision"] = 2
        geracao = self.app.session_state["geracao"]
        self.app.run()
        self.assertEqual(len(self.app.exception), 0)
        atual = self.app.session_state["sessao"]
        self.assertIsNot(atual, antiga)
        self.assertEqual(atual.perfil, antiga.perfil)
        self.assertEqual(atual.componentes(), [])
        self.assertEqual(self.app.session_state["geracao"], geracao + 1)

    def test_sessao_compativel_preserva_conversa_e_componentes_no_rerun(self):
        self.publicar_com_ia()
        sessao = self.app.session_state["sessao"]
        componentes = sessao.componentes()
        mensagens = list(sessao.mensagens)
        self.app.run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertIs(self.app.session_state["sessao"], sessao)
        self.assertEqual(sessao.componentes(), componentes)
        self.assertEqual(sessao.mensagens, mensagens)

    def test_classe_antiga_no_import_pede_reinicio_sem_recriar_sessao(self):
        class SessaoLocalAntiga:
            def __init__(self, banco, usuario):
                raise AssertionError("Não se deve construir outra sessão com a classe antiga")

        sessao = self.app.session_state["sessao"]
        geracao = self.app.session_state["geracao"]
        with patch.object(bob.session, "SessaoLocal", SessaoLocalAntiga):
            self.app.run()
            self.assertEqual(len(self.app.exception), 0)
            self.assertIn("Ctrl+C", self.app.error[0].value)
            self.assertIn("streamlit run app.py", self.app.code[0].value)
            self.assertIs(self.app.session_state["sessao"], sessao)
            self.assertEqual(self.app.session_state["geracao"], geracao)
        self.app.run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(len(self.app.error), 0)

    def test_pergunta_sugerida_envia_uma_vez_e_some_apos_conversa(self):
        sessao = self.app.session_state["sessao"]
        modelo = ModeloSimulado([{"role": "assistant", "content": "Vamos analisar os clientes do seu escopo."}])
        sessao.agentes.client = modelo
        self.botao("Visão de clientes").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(len(modelo.chamadas), 1)
        self.assertEqual(sessao.mensagens[0]["content"], "Quantos clientes temos nos estados que posso acessar?")
        self.assertFalse(any(b.key and b.key.startswith("sugestao_") for b in self.app.button))
        self.app.run()
        self.assertEqual(len(modelo.chamadas), 1)
        self.assertEqual(len(self.app.chat_input), 1)

    def test_trocar_area_mobile_preserva_sessao_e_historico(self):
        self.publicar_com_ia()
        sessao = self.app.session_state["sessao"]
        mensagens = list(sessao.mensagens)
        self.app.button_group(key="mobile_view").set_value("Workspace").run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertIs(self.app.session_state["sessao"], sessao)
        self.assertEqual(sessao.mensagens, mensagens)
        self.app.button_group(key="mobile_view").set_value("Conversa").run()
        self.assertEqual(len(self.app.exception), 0)

    def test_rastreamento_aparece_em_cada_resposta_e_preserva_turnos(self):
        self.publicar_com_ia()
        sessao = self.app.session_state["sessao"]
        primeiro = sessao.mensagens[-1]["rastreamento"]
        self.assertTrue(any("consultar_dados → Agente principal" in e.label for e in self.app.expander))
        self.assertTrue(any("publicar_painel → Agente visual" in e.label for e in self.app.expander))
        self.assertFalse(any("consulta ao modelo" in e.label for e in self.app.expander))
        self.assertEqual(len([e for e in self.app.expander if "consultar_dados →" in e.label]), 1)
        sessao.agentes.client = ModeloSimulado([{"role": "assistant", "content": "Segunda resposta."}])
        self.app.chat_input[0].set_value("Explique a análise anterior").run()
        self.assertEqual(len(self.app.exception), 0)
        trilhas = [m["rastreamento"] for m in sessao.mensagens if "rastreamento" in m]
        self.assertEqual(len(trilhas), 2)
        self.assertEqual(trilhas[0], primeiro)
        self.assertNotEqual(trilhas[0]["id"], trilhas[1]["id"])
        self.assertEqual(len([e for e in self.app.expander if e.label.startswith("Ver passos do Bob")]), 2)

    def test_pergunta_no_rastreamento_e_texto_livre_nao_documento_json(self):
        pergunta = 'agr me de um gráfico com "compras"\ne os clientes?'
        sessao = self.app.session_state['sessao']
        sessao.agentes.client = ModeloSimulado([{'role': 'assistant', 'content': 'Preciso confirmar o período.'}])
        self.app.chat_input[0].set_value(pergunta).run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertTrue(any(c.value == pergunta for c in self.app.code))
        self.assertFalse(any(j.value == pergunta for j in self.app.json))


if __name__ == "__main__":
    unittest.main()
