"""Verificação opcional do layout em Chrome isolado, com respostas locais simuladas."""

import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.request import urlopen

RAIZ = Path(__file__).resolve().parents[1]
CHROME = Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe"


@unittest.skipUnless(os.environ.get("BOB_TEST_BROWSER") == "1", "Ative BOB_TEST_BROWSER=1 para testar o navegador.")
class ResponsiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        if not CHROME.exists():
            raise unittest.SkipTest("Chrome local não encontrado.")
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        fixture = Path(cls.temp.name) / "layout_fixture.py"
        fixture.write_text(
            f"import sys\nsys.path.insert(0, {str(RAIZ)!r})\nsys.path.insert(0, {str(RAIZ / 'tests')!r})\n" + '''
from types import SimpleNamespace
import json
import time
import streamlit as st
from app import BANCO, main
from bob.agents import Agentes
from bob.schemas import UFS, Usuario
from bob.session import SessaoLocal
from test_backend import ModeloSimulado, tool

def pedir_visual(messages):
    dataset = json.loads(messages[-1]["content"])["dataset_id"]
    return tool("criar_painel", {"dataset_ids": [dataset], "pedido": "Indicador de teste"})

def publicar(messages):
    dataset = json.loads(messages[-1]["content"])["dataset_ids"][0]
    return tool("publicar_painel", {"especificacao": {"componentes": [{"id": "indicador", "tipo": "indicador", "dataset_id": dataset, "titulo": "Indicador de teste", "y": "total"}]}})

class AgenteLocal:
    def conversar(self, pergunta):
        if st.query_params.get("slow"):
            time.sleep(2)
        return {"resposta": "Resposta de teste local, sem chamada ao provedor."}

if "sessao" not in st.session_state:
    sessao = SessaoLocal(BANCO, Usuario(id="teste_layout", papel="analista", ufs=tuple(UFS)))
    sessao.agentes = AgenteLocal()
    if st.query_params.get("trace"):
        modelo = ModeloSimulado([
            tool("consultar_dados", {"sql": "SELECT COUNT(*) AS total FROM clientes WHERE coluna_errada=1", "objetivo": {"descricao": "Contar clientes"}}),
            tool("consultar_dados", {"sql": "SELECT COUNT(*) AS total FROM clientes", "objetivo": {"descricao": "Contar clientes"}}),
            pedir_visual, publicar,
            {"role": "assistant", "content": "Painel publicado."},
            {"role": "assistant", "content": "Indicador de teste publicado com rastreamento."},
        ])
        sessao.agentes = Agentes(sessao.backend, modelo)
    sessao.client = SimpleNamespace(api_key="teste_local")
    if st.query_params.get("charts"):
        for id_, sql, titulo, x, y, template in [
            ("categorias", "SELECT categoria,SUM(valor) AS valor_total FROM compras GROUP BY categoria", "Compras por categoria", "categoria", "valor_total", "barras_verticais"),
            ("campanhas", "SELECT canal,COUNT(*) AS envios FROM campanhas_marketing GROUP BY canal", "Campanhas por canal", "canal", "envios", "barras_verticais"),
            ("pizza", "SELECT canal,SUM(valor) AS valor_total FROM compras GROUP BY canal", "Vendas por canal", "canal", "valor_total", "pizza"),
        ]:
            resultado = sessao.backend.consultar_dados(sql, {"descricao": "Fixture de layout"})
            sessao.backend.publicar_painel({"componentes": [{"id": id_, "tipo": "grafico", "template": template,
                "dataset_id": resultado["dataset_id"], "titulo": titulo, "x": x, "y": y, "partes_exclusivas": template == "pizza"}]})
        # Coordenadas antigas que não correspondem às colunas na largura atual.
        sessao.posicoes = {"categorias": {"x": 0, "y": 0}, "campanhas": {"x": 407, "y": 470}, "pizza": {"x": 814, "y": 0}}
    if st.query_params.get("long"):
        sessao.mensagens = [{"role": "user" if i % 2 == 0 else "assistant", "content": "Mensagem simulada para testar rolagem. " * 16} for i in range(24)]
        resultado = sessao.backend.consultar_dados("SELECT estado, COUNT(*) AS clientes FROM clientes GROUP BY estado", {"descricao": "Fixture local de layout"})
        sessao.backend.publicar_painel({"componentes": [
            {"id": "mapa", "tipo": "mapa", "dataset_id": resultado["dataset_id"], "titulo": "Mapa de teste", "x": "estado", "y": "clientes"},
            {"id": "dados", "tipo": "tabela", "dataset_id": resultado["dataset_id"], "titulo": "Dados de teste"},
        ]})
        if st.query_params.get("overlap"):
            sessao.backend.publicar_painel({"componentes": [{"id": "barras", "tipo": "barras", "dataset_id": resultado["dataset_id"], "titulo": "Clientes por estado", "x": "estado", "y": "clientes"}]})
            sessao.posicoes = {id_: {"x": 0, "y": 0} for id_ in ("mapa", "dados", "barras")}
        if st.query_params.get("edit"):
            dataset = resultado["dataset_id"]
            sessao.agentes = Agentes(sessao.backend, ModeloSimulado([
                tool("criar_painel", {"dataset_ids": [dataset], "pedido": "Transforme o mapa existente em barras e mantenha seu id"}),
                tool("publicar_painel", {"especificacao": {"componentes": [{"id": "mapa", "tipo": "barras", "dataset_id": dataset, "titulo": "Clientes em barras", "x": "estado", "y": "clientes"}]}}),
                {"role": "assistant", "content": "Cartão editado."},
                {"role": "assistant", "content": "Transformei o mapa em barras no mesmo cartão."},
            ]))
    st.session_state.update(sessao=sessao, workspace_revision=2, geracao=0)
main()
''', encoding="utf-8")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            porta = sock.getsockname()[1]
        cls.url = f"http://127.0.0.1:{porta}"
        cls.server = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", str(fixture), "--server.port", str(porta),
             "--server.address", "127.0.0.1", "--server.headless", "true", "--server.fileWatcherType", "none"],
            cwd=RAIZ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, 'BOB_WORKSPACE_STORE': str(Path(cls.temp.name) / 'workspaces.sqlite3')},
        )
        cls.addClassCleanup(cls.encerrar_servidor)
        limite = time.monotonic() + 20
        while True:
            try:
                with urlopen(cls.url + "/_stcore/health", timeout=1) as resposta:
                    if resposta.status == 200:
                        break
            except OSError:
                if time.monotonic() >= limite or cls.server.poll() is not None:
                    raise RuntimeError("Servidor de teste não iniciou.")
                time.sleep(.1)
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(executable_path=str(CHROME), headless=True)
        cls.addClassCleanup(cls.browser.close)

    @classmethod
    def encerrar_servidor(cls):
        cls.server.terminate()
        cls.server.wait(timeout=10)

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 1440, "height": 900})
        self.page.set_default_timeout(10000)
        self.addCleanup(self.page.close)

    def abrir(self, longa=False):
        self.page.goto(self.url + ("/?long=1" if longa else "/"))
        self.page.locator(".st-key-composer textarea").wait_for(timeout=20000)

    def conferir_entrada(self):
        self.page.wait_for_function("Math.abs(document.querySelector('.st-key-space_shell').getBoundingClientRect().height - (visualViewport?.height ?? innerHeight)) < 1")
        self.assertEqual(self.page.locator("[data-testid=stException]").count(), 0)
        caixa = self.page.locator(".st-key-composer textarea").bounding_box()
        self.assertIsNotNone(caixa)
        self.assertGreater(caixa["height"], 20)
        self.assertGreaterEqual(caixa["x"], 0)
        self.assertLessEqual(caixa["x"] + caixa["width"], self.page.viewport_size["width"] + 1)
        self.assertLessEqual(caixa["y"] + caixa["height"], self.page.viewport_size["height"])
        self.assertTrue(self.page.evaluate('''() => {
            const main = document.querySelector('[data-testid=stMain]');
            return main.scrollHeight <= main.clientHeight + 1 && document.documentElement.scrollWidth <= innerWidth;
        }'''))

    def test_tela_vazia_sem_rolagem_externa_e_entrada_visivel(self):
        self.abrir()
        for largura, altura in [(1440, 900), (1366, 768), (1024, 768), (900, 700), (390, 844), (320, 667)]:
            with self.subTest(largura=largura, altura=altura):
                self.page.set_viewport_size({"width": largura, "height": altura})
                self.conferir_entrada()
                self.assertTrue(self.page.locator(".st-key-chat_log").evaluate("e=>e.scrollHeight <= e.clientHeight + 1"))
                marca = self.page.locator(".brand").bounding_box()
                nova = self.page.get_by_role("button", name="Nova sessão").bounding_box()
                self.assertLessEqual(marca["x"] + marca["width"], nova["x"])
                self.assertEqual(self.page.locator(".st-key-suggestions [data-testid=stButton]").count(), 4)

    def test_mapa_visivel_arraste_persistente_e_edicao_pelo_chat(self):
        self.page.set_viewport_size({"width": 1780, "height": 1000})
        self.page.goto(self.url + "/?long=1&edit=1")
        handle = self.page.locator('.st-key-card_mapa .card-title')
        handle.wait_for()
        image = self.page.locator('.st-key-card_mapa .bob-map svg')
        image.wait_for()
        self.assertGreater(image.bounding_box()["height"], 200)
        self.assertEqual(image.locator('path').count(), 27)
        self.assertEqual(self.page.get_by_text("Visualização", exact=True).count(), 0)
        self.assertEqual(self.page.get_by_text("Organizar", exact=True).count(), 0)
        self.page.wait_for_function("document.querySelector('.st-key-card_mapa').parentElement.style.position === 'absolute'")
        before = self.page.locator('.st-key-card_mapa').bounding_box()
        h = handle.bounding_box()
        self.page.mouse.move(h['x'] + 40, h['y'] + 10)
        self.page.mouse.down()
        self.page.mouse.move(h['x'] + 140, h['y'] + 82, steps=12)
        self.page.mouse.up()
        self.page.wait_for_function("parseFloat(document.querySelector('.st-key-card_mapa').parentElement.style.top) >= 70")
        self.page.locator('.st-key-card_mapa [data-testid=stButton] button').first.click()
        self.page.wait_for_function("parseFloat(document.querySelector('.st-key-card_mapa').parentElement.style.top) >= 70")
        after = self.page.locator('.st-key-card_mapa').bounding_box()
        self.assertGreater(after['y'], before['y'] + 60)
        self.assertGreater(after['x'], before['x'] + 50)
        self.page.screenshot(path=str(Path(self.temp.name) / 'workspace-mapa.png'))
        self.assertGreater(self.page.locator('.st-key-work_canvas').bounding_box()['height'], 600)
        entrada = self.page.locator('.st-key-composer textarea')
        entrada.fill('Edite o mapa existente para um gráfico de barras.')
        entrada.press('Enter')
        self.page.get_by_text('Transformei o mapa em barras no mesmo cartão.', exact=True).wait_for()
        self.page.locator('.st-key-card_mapa [data-testid=stVegaLiteChart]').wait_for()
        self.page.wait_for_function("document.querySelector('.st-key-card_mapa canvas') || document.querySelector('.st-key-card_mapa svg.marks')")
        self.assertEqual(self.page.locator('.st-key-card_mapa').count(), 1)
        self.assertEqual(self.page.locator('.st-key-card_mapa .bob-map').count(), 0)
        edited = self.page.locator('.st-key-card_mapa').bounding_box()
        self.assertAlmostEqual(edited['x'], after['x'], delta=2)
        self.assertAlmostEqual(edited['y'], after['y'], delta=2)
        self.page.screenshot(path=str(Path(self.temp.name) / 'workspace-editado.png'))

    def test_historico_longo_rola_sem_mover_entrada_e_envio_chega_ao_fim(self):
        self.abrir(longa=True)
        for largura, altura in [(1366, 768), (390, 844), (390, 420), (844, 390)]:
            self.page.set_viewport_size({"width": largura, "height": altura})
            self.conferir_entrada()
            self.assertTrue(self.page.locator(".st-key-chat_log").evaluate("e=>e.scrollHeight > e.clientHeight"))
        self.page.locator(".st-key-composer textarea").fill("Teste local de envio")
        self.page.locator(".st-key-composer textarea").press("Enter")
        self.page.get_by_text("Resposta de teste local, sem chamada ao provedor.", exact=True).wait_for()
        self.conferir_entrada()
        self.page.wait_for_function("(()=>{let e=document.querySelector('.st-key-chat_log');return e.scrollHeight-e.scrollTop-e.clientHeight<5})()")

    def test_mobile_alterna_workspace_preserva_conversa_e_abre_permissoes(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.abrir(longa=True)
        quantidade = self.page.locator("[data-testid=stChatMessage]").count()
        self.page.locator(".st-key-mobile_nav").get_by_text("Workspace", exact=True).click()
        self.page.locator(".st-key-view_workspace .st-key-work_panel").wait_for(state="visible")
        self.assertFalse(self.page.locator(".st-key-chat_panel").is_visible())
        self.assertTrue(self.page.get_by_text("Mapa de teste", exact=True).is_visible())
        self.page.locator(".st-key-mobile_nav").get_by_text("Conversa", exact=True).click()
        self.page.locator(".st-key-view_conversa .st-key-chat_panel").wait_for(state="visible")
        self.assertEqual(self.page.locator("[data-testid=stChatMessage]").count(), quantidade)
        self.conferir_entrada()
        self.page.locator(".st-key-space_header [data-testid=stColumn]").last.get_by_role("button").click()
        self.page.get_by_role("dialog").wait_for()
        self.page.get_by_role("button", name="Salvar e reiniciar sessão").wait_for(state="visible")
        self.assertTrue(self.page.get_by_role("button", name="Salvar e reiniciar sessão").is_visible())

    def test_sugestao_gera_conversa_local_e_desaparece(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.abrir()
        self.page.get_by_role("button", name="Visão de clientes").click()
        self.page.get_by_text("Resposta de teste local, sem chamada ao provedor.", exact=True).wait_for()
        self.assertEqual(self.page.locator("[data-testid=stChatMessage]").count(), 2)
        self.assertEqual(self.page.locator(".st-key-suggestions").count(), 0)
        self.conferir_entrada()

    def test_viewport_visual_reduzido_mantem_entrada_acima_do_teclado(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.abrir(longa=True)
        self.page.wait_for_function("typeof window.bobSpaceAtualizarViewport === 'function'")
        # Simula um teclado que reduz a área visual, sem mudar o layout viewport.
        self.page.evaluate('''() => {
            Object.defineProperty(visualViewport, 'height', {configurable:true, get:()=>420});
            visualViewport.dispatchEvent(new Event('resize'));
        }''')
        self.assertEqual(self.page.locator(".st-key-space_shell").bounding_box()["height"], 420)
        caixa = self.page.locator(".st-key-composer textarea").bounding_box()
        self.assertLessEqual(caixa["y"] + caixa["height"], 420)
        self.assertEqual(self.page.viewport_size["height"], 844)
        self.page.evaluate("delete visualViewport.height; visualViewport.dispatchEvent(new Event('resize'))")
        self.assertEqual(self.page.locator(".st-key-space_shell").bounding_box()["height"], 844)
        self.conferir_entrada()

    def test_mensagem_aparece_antes_da_resposta_sem_duplicar(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.goto(self.url + "/?slow=1")
        entrada = self.page.locator(".st-key-composer textarea")
        entrada.wait_for()
        entrada.fill("Teste de envio imediato")
        entrada.press("Enter")
        historico = self.page.locator(".st-key-chat_log")
        historico.get_by_text("Teste de envio imediato", exact=True).wait_for(timeout=1500)
        self.page.locator('.st-key-composer').get_by_text("Bob está analisando sua pergunta…", exact=False).wait_for(timeout=1500)
        self.assertTrue(entrada.is_disabled())
        self.assertEqual(historico.get_by_text("Resposta de teste local, sem chamada ao provedor.", exact=True).count(), 0)
        self.conferir_entrada()
        historico.get_by_text("Resposta de teste local, sem chamada ao provedor.", exact=True).wait_for()
        self.assertEqual(historico.get_by_text("Teste de envio imediato", exact=True).count(), 1)
        self.assertEqual(self.page.locator("[data-testid=stChatMessage]").count(), 2)
        self.assertEqual(self.page.locator(".st-key-suggestions").count(), 0)

    def test_segunda_pergunta_com_workspace_mantem_espera_visivel_e_responde(self):
        self.page.goto(self.url + '/?long=1&slow=1')
        entrada = self.page.locator('.st-key-composer textarea')
        entrada.wait_for()
        entrada.fill('agr me de um grafico separando os clientes que ja pagaram dos que nao pagaram')
        entrada.press('Enter')
        espera = self.page.locator('.st-key-composer').get_by_text('Bob está analisando sua pergunta…', exact=False)
        espera.wait_for(timeout=1500)
        self.assertTrue(entrada.is_disabled())
        caixa = espera.bounding_box()
        self.assertGreaterEqual(caixa['y'], 0)
        self.assertLessEqual(caixa['y'] + caixa['height'], 900)
        self.page.get_by_text('Resposta de teste local, sem chamada ao provedor.', exact=True).wait_for()
        self.assertFalse(entrada.is_disabled())
        self.assertTrue(self.page.locator('.st-key-card_mapa').is_visible())

    def test_reload_restaura_workspace_posicao_conversa_e_mapa_clicavel(self):
        self.page.set_viewport_size({'width':1780, 'height':1000})
        self.abrir(longa=True)
        handle = self.page.locator('.st-key-card_mapa .card-title')
        handle.wait_for()
        self.page.wait_for_function("document.querySelector('.st-key-card_mapa').parentElement.style.position === 'absolute'")
        handle.focus()
        handle.press('ArrowDown')
        self.page.wait_for_function("parseFloat(document.querySelector('.st-key-card_mapa').parentElement.style.top) >= 24")
        quantidade = self.page.locator('[data-testid=stChatMessage]').count()
        self.page.locator('.st-key-card_mapa .bob-map path[data-uf=SP]').hover()
        self.page.locator('.st-key-card_mapa .map-tooltip').get_by_text('São Paulo',exact=False).wait_for()
        self.page.locator('.st-key-card_mapa .bob-map path[data-uf=SP]').click()
        self.page.get_by_role('button', name='Voltar ao Brasil').wait_for()
        self.assertEqual(self.page.locator('.st-key-card_mapa .bob-map path').count(), 1)
        self.page.reload()
        self.page.get_by_role('button', name='Voltar ao Brasil').wait_for()
        self.page.wait_for_function("parseFloat(document.querySelector('.st-key-card_mapa').parentElement.style.top) >= 24")
        self.assertEqual(self.page.locator('[data-testid=stChatMessage]').count(), quantidade)
        self.assertEqual(self.page.locator('.st-key-card_mapa .bob-map path').count(), 1)
        self.page.screenshot(path=str(Path(self.temp.name) / 'workspace-persistente.png'))
        self.page.get_by_role('button', name='Voltar ao Brasil').click()
        self.page.locator('.st-key-card_mapa .bob-map path').nth(26).wait_for()
        self.page.get_by_role('button', name='Nova sessão').click()
        self.page.locator('.empty-work').wait_for()
        self.page.reload()
        self.page.locator('.empty-work').wait_for()
        self.assertEqual(self.page.locator('.st-key-card_mapa').count(), 0)

    def test_rastreamento_mobile_mostra_entrada_erro_correcao_e_visual(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.goto(self.url + "/?trace=1")
        entrada = self.page.locator(".st-key-composer textarea")
        entrada.wait_for()
        entrada.fill("Crie um indicador de teste")
        entrada.press("Enter")
        self.page.get_by_text("Indicador de teste publicado com rastreamento.", exact=True).wait_for()
        self.page.get_by_text("Ver passos do Bob", exact=False).click()
        historico = self.page.locator(".st-key-chat_log")
        historico.get_by_text('1. Pergunta recebida', exact=True).click()
        historico.locator('[data-testid=stCode]').get_by_text('Crie um indicador de teste', exact=True).wait_for()
        self.assertEqual(historico.get_by_text('Json Parse Error:', exact=False).count(), 0)
        historico.get_by_text("consultar_dados → Agente principal · Erro", exact=False).click()
        historico.get_by_text("SQL_INVALIDO", exact=False).wait_for()
        historico.get_by_text("SELECT COUNT(*) AS total FROM clientes WHERE coluna_errada=1", exact=False).wait_for()
        self.assertEqual(historico.get_by_text("consulta ao modelo", exact=False).count(), 0)
        self.assertEqual(historico.get_by_text("publicar_painel → Agente visual", exact=False).count(), 1)
        self.conferir_entrada()

    def test_encaixe_colisoes_redimensionamento_e_persistencia(self):
        self.page.set_viewport_size({"width": 1920, "height": 1000})
        self.page.goto(self.url + "/?long=1&overlap=1")
        self.page.locator('.st-key-card_barras [data-testid=stVegaLiteChart]').wait_for()
        sem_colisao = """() => {
          const board = document.querySelector('.st-key-work_canvas').getBoundingClientRect();
          const cards = ['mapa','dados','barras'].map(id => document.querySelector('.st-key-card_'+id).getBoundingClientRect());
          return ['mapa','dados','barras'].every(id => document.querySelector('.st-key-card_'+id).parentElement.style.position === 'absolute') && cards.every((a,i) => a.width > 100 && a.left >= board.left-1 && a.right <= board.right+1 && cards.every((b,j) => i===j || a.right <= b.left+1 || b.right <= a.left+1 || a.bottom <= b.top+1 || b.bottom <= a.top+1));
        }"""
        self.page.wait_for_function(sem_colisao)
        shell = self.page.locator('.st-key-space_shell').bounding_box()
        self.assertGreater(shell['width'], 1900)
        self.page.get_by_role('button', name='Encaixar cartões').click()
        self.page.wait_for_function("Math.abs(document.querySelector('.st-key-card_mapa').getBoundingClientRect().top-document.querySelector('.st-key-card_dados').getBoundingClientRect().top)<2")
        self.page.wait_for_function(sem_colisao)
        self.page.locator('.st-key-card_dados .card-title').press('ArrowLeft')
        self.page.wait_for_function(sem_colisao)
        handle = self.page.locator('.st-key-card_mapa .card-title').bounding_box()
        self.page.mouse.move(handle['x']+20, handle['y']+10)
        self.page.mouse.down()
        self.page.mouse.move(handle['x']+400, handle['y']+100, steps=12)
        self.assertTrue(self.page.evaluate(sem_colisao))
        self.page.mouse.up()
        self.page.wait_for_function(sem_colisao)
        self.page.get_by_role('button', name='Encaixar cartões').click()
        self.page.wait_for_function(sem_colisao)
        self.page.locator('.st-key-card_mapa').get_by_text('Dados e contexto', exact=True).click()
        self.page.wait_for_function(sem_colisao)
        self.page.set_viewport_size({"width": 1100, "height": 900})
        self.page.wait_for_function(sem_colisao)
        self.page.reload()
        self.page.locator('.st-key-card_barras [data-testid=stVegaLiteChart]').wait_for()
        self.page.wait_for_function(sem_colisao)
        self.assertEqual(self.page.locator('[data-testid=stException]').count(), 0)
        self.page.set_viewport_size({"width": 1920, "height": 1000})
        self.page.get_by_role('button', name='Encaixar cartões').click()
        self.page.wait_for_function("['mapa','dados','barras'].every(id => document.querySelector('.st-key-card_'+id).parentElement.style.top==='0px')")
        self.page.wait_for_function(sem_colisao)
        self.page.locator('.st-key-work_scroll').evaluate('(el) => el.scrollTop=0')
        self.page.mouse.move(1900, 50)
        self.page.screenshot(path=str(Path(self.temp.name) / 'workspace-encaixado.png'))

    def test_graficos_automaticos_alinham_apos_resize_e_reload_com_pizza(self):
        self.page.set_viewport_size({"width": 1920, "height": 1000})
        self.page.goto(self.url + "/?charts=1")
        self.page.locator('.st-key-card_pizza [data-testid=stVegaLiteChart]').wait_for()
        alinhados = """() => {
            const board = document.querySelector('.st-key-work_canvas');
            const columns = Math.max(1, Math.floor((board.clientWidth+16)/396));
            const width = (board.clientWidth-16*(columns-1))/columns;
            const cards = ['categorias','campanhas','pizza'].map(id => document.querySelector('.st-key-card_'+id));
            const top = Math.min(...cards.map(c => parseFloat(c.parentElement.style.top)));
            return cards.every((c,i) => c.parentElement.style.position==='absolute' &&
                Math.abs(parseFloat(c.parentElement.style.left) - (i%columns)*(width+16))<1 &&
                (i>=columns || Math.abs(parseFloat(c.parentElement.style.top)-top)<1));
        }"""
        self.page.wait_for_function(alinhados)
        self.assertTrue(self.page.locator('.st-key-card_pizza canvas, .st-key-card_pizza svg.marks').count())
        self.page.set_viewport_size({"width": 1100, "height": 900})
        self.page.wait_for_function(alinhados)
        self.page.set_viewport_size({"width": 1920, "height": 1000})
        self.page.wait_for_function(alinhados)
        self.page.reload()
        self.page.locator('.st-key-card_pizza [data-testid=stVegaLiteChart]').wait_for()
        self.page.wait_for_function(alinhados)
        self.assertEqual(self.page.locator('[data-testid=stException]').count(), 0)
        self.page.screenshot(path=str(Path(self.temp.name) / 'workspace-pizza.png'))


if __name__ == "__main__":
    unittest.main()
