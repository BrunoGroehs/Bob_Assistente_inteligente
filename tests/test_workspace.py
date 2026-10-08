"""Regressões do mapa e da troca de sessão, sem chamadas ao provedor."""

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from bob.maps import CODIGOS, malhas, mapa_svg
from bob.schemas import BobError, Usuario
from bob.session import SessaoLocal
from test_backend import criar_banco


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.banco = Path(self.temp.name) / "teste.db"
        criar_banco(self.banco)
        self.sessao = SessaoLocal(self.banco, Usuario(id="demo", papel="analista", ufs=("SP", "RJ")))

    def publicar_mapa(self, sessao=None):
        sessao = sessao or self.sessao
        resultado = sessao.backend.consultar_dados(
            "SELECT estado, COUNT(*) AS clientes FROM clientes GROUP BY estado ORDER BY clientes DESC",
            {"descricao": "Clientes por estado"})
        if resultado["status"] != "ok":
            return resultado
        return sessao.backend.publicar_painel({"componentes": [{
            "id": "clientes_por_estado", "tipo": "mapa", "dataset_id": resultado["dataset_id"],
            "titulo": "Clientes por estado", "x": "estado", "y": "clientes"}]})

    def publicar_exemplos(self):
        self.publicar_mapa()
        resultado = self.sessao.backend.consultar_dados("SELECT COUNT(*) AS total FROM clientes", {"descricao": "Contar clientes"})
        self.sessao.backend.publicar_painel({"componentes": [
            {"id": "total", "tipo": "indicador", "dataset_id": resultado["dataset_id"], "titulo": "Total", "y": "total"},
            {"id": "tabela", "tipo": "tabela", "dataset_id": resultado["dataset_id"], "titulo": "Tabela"}]})

    def acao(self, **campos):
        resultado = self.sessao.backend.consultar_dados("SELECT COUNT(*) AS total FROM clientes", {"descricao": "Contar clientes"})
        return {"id": "relacionamento", "tipo": "acao", "dataset_id": resultado["dataset_id"], "titulo": "Revisar relacionamento",
                "acao": {"descricao": "Avaliar uma campanha para a base autorizada.", "publico": "Clientes do escopo", "canal": "A definir", **campos}}

    def test_mapa_usa_agregados_autorizados_e_refresh_sem_ia(self):
        self.assertEqual(self.publicar_mapa()["status"], "publicado")
        componente = self.sessao.backend.workspace()[0]
        self.assertEqual(componente["tipo"], "mapa")
        self.assertEqual(componente["resultado"]["dados"], [{"estado": "SP", "clientes": 12}, {"estado": "RJ", "clientes": 6}])
        self.assertEqual(self.sessao.backend.atualizar_componente(componente["id"])["status"], "ok")
        self.assertEqual(self.sessao.client.uso, [])

    def test_organizar_preserva_dados_e_recebe_novos_componentes(self):
        self.publicar_exemplos()
        antes = self.sessao.componentes()
        self.sessao.mover("tabela", -1)
        self.assertEqual([c["id"] for c in self.sessao.componentes()], ["clientes_por_estado", "tabela", "total"])
        self.sessao.mover("clientes_por_estado", -1)
        self.assertEqual([c["id"] for c in self.sessao.componentes()], ["clientes_por_estado", "tabela", "total"])
        for c in self.sessao.componentes():
            self.assertEqual(c, next(v for v in antes if v["id"] == c["id"]))
        self.sessao.backend.publicar_painel({"componentes": [self.acao()]})
        self.assertEqual(self.sessao.componentes()[-1]["id"], "relacionamento")
        with self.assertRaises(BobError):
            self.sessao.mover("outra_sessao", 1)

    def test_salvar_permissoes_limpa_todo_estado_e_isola_resultados(self):
        self.publicar_exemplos()
        id_ = self.sessao.backend.workspace()[0]["dataset_id"]
        self.sessao.mensagens.append({"role": "user", "content": "Antigo"})
        self.sessao.backend.conversas.append([{"role": "user", "content": "Antigo"}])
        self.sessao.client.uso.append({"tokens_entrada": 10})
        novo = self.sessao.reiniciar(Usuario(id="demo", papel="analista", ufs=("RJ",)))
        self.assertEqual(novo.mensagens, [])
        self.assertEqual(novo.backend.conversas, [])
        self.assertEqual(novo.backend.eventos, [])
        self.assertEqual(novo.backend.workspace(), [])
        self.assertEqual(novo.client.uso, [])
        with self.assertRaises(BobError):
            novo.backend.dados(id_)
        self.publicar_mapa(novo)
        self.assertEqual(novo.backend.workspace()[0]["resultado"]["dados"], [{"estado": "RJ", "clientes": 6}])

    def test_reset_preserva_perfil_sem_preservar_historico(self):
        self.publicar_mapa()
        novo = self.sessao.reiniciar()
        self.assertEqual(novo.perfil, self.sessao.perfil)
        self.assertEqual(novo.backend.workspace(), [])

    def test_posicao_preservada_ao_editar_cartao_e_isolada_por_sessao(self):
        self.publicar_mapa()
        self.sessao.posicionar({"clientes_por_estado": {"x": 48, "y": 72}})
        c = self.sessao.componentes()[0]
        editado = {k: v for k, v in c.items() if k not in {"resultado", "versao"}}
        editado.update(tipo="barras", titulo="Clientes por UF em barras")
        self.assertEqual(self.sessao.backend.publicar_painel({"componentes": [editado]})["status"], "publicado")
        self.assertEqual(len(self.sessao.componentes()), 1)
        self.assertEqual(self.sessao.posicoes, {"clientes_por_estado": {"x": 48, "y": 72}})
        self.assertEqual(self.sessao.reiniciar().posicoes, {})
        for ponto in [{"x": float("nan"), "y": 0}, {"x": -1, "y": 0}, {"x": 0, "y": True}]:
            with self.assertRaises(ValueError):
                self.sessao.posicionar({c["id"]: ponto})
        with self.assertRaises(BobError):
            self.sessao.posicionar({"outro": {"x": 0, "y": 0}})

    def test_mapa_rejeita_eixo_invalido_e_dimensao_nao_geografica(self):
        r = self.sessao.backend.consultar_dados("SELECT canal, COUNT(*) AS total FROM compras GROUP BY canal", {"descricao": "Compras por canal"})
        c = {"id": "mapa", "tipo": "mapa", "dataset_id": r["dataset_id"], "titulo": "Mapa", "x": "canal", "y": "total"}
        self.assertEqual(self.sessao.backend.publicar_painel({"componentes": [c]})["codigo"], "PAINEL_INVALIDO")
        c["x"] = None
        self.assertEqual(self.sessao.backend.publicar_painel({"componentes": [c]})["codigo"], "PAINEL_INVALIDO")

    def test_mapa_suprimido_nao_vira_zero(self):
        sessao = self.sessao.reiniciar(Usuario(id="demo", papel="analista", ufs=("MG",)))
        self.assertEqual(self.publicar_mapa(sessao)["status"], "publicado")
        r = sessao.backend.workspace()[0]["resultado"]
        self.assertEqual(r["dados"], [])
        self.assertGreater(r["grupos_suprimidos"], 0)
        svg = mapa_svg(("MG",), r["dados"], estado="MG")
        self.assertIn("Sem valor exibível", svg)
        self.assertNotIn("clientes: 0", svg)

    def test_svg_tem_27_ufs_e_zoom_do_estado_sem_dados_fora_do_acesso(self):
        self.assertEqual({CODIGOS[f["properties"]["codarea"]] for f in malhas()}, set(CODIGOS.values()))
        svg = mapa_svg(("SP",), [{"estado": "SP", "clientes": 12}, {"estado": "RJ", "clientes": 999}])
        raiz = ET.fromstring(svg)
        self.assertEqual(len(raiz.findall("{http://www.w3.org/2000/svg}path")), 27)
        self.assertNotIn("999", " ".join(e.text or "" for e in raiz.iter("{http://www.w3.org/2000/svg}title")))
        zoom = ET.fromstring(mapa_svg(("SP",), estado="SP"))
        self.assertEqual(len(zoom.findall("{http://www.w3.org/2000/svg}path")), 1)

    def test_papeis_sem_consulta_nao_conseguem_adicionar_mapa(self):
        for papel in ("leitor", "administrador"):
            sessao = self.sessao.reiniciar(Usuario(id="demo", papel=papel, ufs=("SP",)))
            self.assertEqual(self.publicar_mapa(sessao)["codigo"], "ACESSO_PAPEL")

    def test_acao_exige_evidencia_e_respeita_privacidade_e_escopo(self):
        acao = self.acao()
        self.assertEqual(self.sessao.backend.publicar_painel({"componentes": [acao]})["status"], "publicado")
        for campo, valor, codigo in [("mensagem", "Escreva para pessoa@example.com", "DADOS_PESSOAIS"), ("publico", "Clientes de Minas Gerais", "ACESSO_ESCOPO")]:
            invalidacao = self.acao(**{campo: valor})
            self.assertEqual(self.sessao.backend.publicar_painel({"componentes": [invalidacao]})["codigo"], codigo)
        vazia = self.sessao.backend.consultar_dados("SELECT estado, COUNT(*) AS total FROM clientes WHERE estado='SP' AND estado='RJ' GROUP BY estado", {"descricao": "Sem resultados"})
        acao["dataset_id"] = vazia["dataset_id"]
        self.assertEqual(self.sessao.backend.publicar_painel({"componentes": [acao]})["codigo"], "PAINEL_INVALIDO")
        acao["acao"] = None
        self.assertEqual(self.sessao.backend.publicar_painel({"componentes": [acao]})["codigo"], "ARGUMENTOS_INVALIDOS")

    def test_conclusao_de_acao_e_local_e_reabre_quando_ia_altera_proposta(self):
        acao = self.acao()
        self.sessao.backend.publicar_painel({"componentes": [acao]})
        self.sessao.alternar_acao(acao["id"])
        self.assertEqual(self.sessao.acoes_concluidas[acao["id"]], 1)
        acao["acao"]["descricao"] = "Revisar campanha e canal antes do contato."
        self.sessao.backend.publicar_painel({"componentes": [acao]})
        self.assertNotEqual(self.sessao.componentes()[0]["versao"], self.sessao.acoes_concluidas[acao["id"]])
        self.assertEqual(self.sessao.reiniciar().acoes_concluidas, {})


if __name__ == "__main__":
    unittest.main()
