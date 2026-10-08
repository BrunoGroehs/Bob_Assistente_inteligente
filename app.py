"""Bob Space: workspace e conversa, sobre o backend existente."""

from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
from dotenv import load_dotenv

from bob.maps import NOMES
from bob.charts import criar_grafico
from bob.chart_templates import TEMPLATES
from bob.schemas import BobError, UFS, Usuario
from bob.session import SessaoLocal
from bob.canvas import montar_canvas
from bob.browser_storage import conectar_workspace, salvar_workspace
from bob.map_view import mapa_interativo

RAIZ = Path(__file__).resolve().parent
BANCO = RAIZ / "data" / "anexo_desafio_1.db"
PAPEIS = {"analista": "Analista", "leitor": "Leitor", "administrador": "Administrador"}
METODOS_SESSAO = ("componentes", "posicionar", "alternar_acao", "conversar", "reiniciar")
SUGESTOES = (
    ("Visão de clientes", ":material/groups:", "Quantos clientes temos nos estados que posso acessar?"),
    ("Mapa do Brasil", ":material/map:", "Mostre um mapa de clientes por estado dentro do meu acesso."),
    ("Categorias de compra", ":material/bar_chart:", "Compare as compras por categoria no período disponível e crie um gráfico."),
    ("Ideias de relacionamento", ":material/lightbulb:", "Analise os canais de compra no período disponível e sugira ações de relacionamento para os segmentos."),
)


def numero(valor):
    if valor is None:
        return "—"
    return f"{valor:,.0f}".replace(",", ".") if float(valor).is_integer() else f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def reiniciar(perfil=None):
    st.session_state.sessao = st.session_state.sessao.reiniciar(perfil)
    st.session_state.geracao += 1
    st.session_state.modal_permissoes = False
    st.session_state.pop("pergunta_sugerida", None)
    st.session_state.mobile_view = "Conversa"
    st.session_state.aviso = "Permissões aplicadas. Conversa e workspace foram reiniciados." if perfil else "Nova sessão iniciada. Seu perfil foi mantido."
    salvar_workspace()
    st.rerun()


def fechar_permissoes():
    st.session_state.modal_permissoes = False


@st.dialog("Permissões da simulação", width="medium", on_dismiss=fechar_permissoes)
def permissoes():
    perfil = st.session_state.sessao.perfil
    st.caption("Ambiente local de demonstração · escolha o acesso que deseja testar.")
    with st.form("permissoes_form"):
        papel = st.selectbox("Papel", list(PAPEIS), index=list(PAPEIS).index(perfil.papel), format_func=PAPEIS.get)
        ufs = st.multiselect("Estados permitidos", sorted(UFS), default=list(perfil.ufs),
                             format_func=lambda uf: f"{uf} · {NOMES[uf]}", placeholder="Selecione os estados")
        st.caption("Analista: consultar e criar painéis. Leitor: ler e atualizar recursos da sessão. Administrador: gestão de acessos, sem acesso analítico herdado.")
        st.info("Salvar inicia uma sessão limpa: remove o histórico, os dados consultados e os painéis. A interface reinicia automaticamente.")
        salvar = st.form_submit_button("Salvar e reiniciar sessão", type="primary", width="stretch")
    if salvar:
        reiniciar(Usuario(id="simulacao_local", papel=papel, ufs=tuple(ufs)))


def informar(resultado):
    if resultado.get("status") not in {"ok", "publicado"}:
        st.error(resultado.get("mensagem", "Não foi possível concluir a operação."))


def sessao_compativel(sessao):
    """Objetos do session_state podem sobreviver à recarga do módulo da classe."""
    return isinstance(sessao, SessaoLocal) and all(callable(getattr(sessao, nome, None)) for nome in METODOS_SESSAO)


def renderizar(componente, sessao):
    id_ = componente["id"]
    resultado = componente["resultado"]
    dados, x, y = resultado["dados"], componente["x"], componente["y"]
    with st.container(border=True, key=f"card_{id_}"):
        titulo, atualizar = st.columns([8, 1])
        titulo.html(f'<div class="card-title" tabindex="0" role="button" aria-label="Mover {escape(componente["titulo"], quote=True)}" title="Arraste para posicionar · use as setas do teclado">{escape(componente["titulo"])}</div>')
        if componente["tipo"] != "acao" and atualizar.button("", icon=":material/refresh:", key=f"refresh_{id_}", help="Reconsultar sem chamar a IA"):
            resposta = sessao.backend.atualizar_componente(id_)
            if resposta["status"] == "ok":
                salvar_workspace()
                st.rerun()
            informar(resposta)
        if componente["tipo"] == "acao":
            acao = componente["acao"]
            concluida = getattr(sessao, "acoes_concluidas", {}).get(id_) == componente["versao"]
            st.caption(f"{'Concluída' if concluida else 'Ação sugerida'} · {acao['canal']}")
            st.markdown(acao["descricao"])
            st.markdown(f"**Público:** {acao['publico']}")
            if acao.get("mensagem"):
                with st.expander("Rascunho de mensagem"):
                    st.code(acao["mensagem"], language=None, wrap_lines=True)
            if componente.get("evidencia_em") != resultado["atualizado_em"]:
                st.warning("Os dados mudaram desde esta sugestão. Peça ao Bob para revisar a ação.")
            st.caption("Sugestão para revisão · o contato deve ser feito no seu sistema de relacionamento.")
            if st.button("Reabrir ação" if concluida else "Marcar como concluída", key=f"concluir_{id_}", icon=":material/check:"):
                sessao.alternar_acao(id_)
                salvar_workspace()
                st.rerun()
        elif componente["tipo"] == "mapa":
            mapa_interativo(sessao, componente, st.session_state.geracao)
            st.html('''<div class="map-legend"><span><i style="background:#2c5b70"></i>Valor disponível</span><span><i style="background:#e1e8ee"></i>Sem valor exibível</span><span><i style="background:#e5e7eb"></i>Fora do acesso</span></div>''')
        elif not dados:
            st.info("Nenhum valor exibível para esta consulta. Confira filtros e grupos suprimidos.")
        elif componente["tipo"] == "indicador":
            st.html(f'<div class="metric-value">{escape(numero(dados[0][y]))}</div><div class="metric-label">{escape(y)}</div>')
        elif componente["tipo"] == "tabela":
            st.dataframe(dados, hide_index=True, width="stretch")
        else:
            st.altair_chart(criar_grafico(componente, resultado), width="stretch")
            st.caption("Clique para destacar · clique duplo para limpar a seleção.")
            if componente.get("template"):
                template = TEMPLATES[componente["template"]]
                st.caption(template.nome)
                if template.percentual:
                    st.caption("Participação no total consultado, dentro do seu escopo.")
        with st.expander("Dados e contexto"):
            if resultado.get("grupos_suprimidos"):
                st.caption(f"{resultado['grupos_suprimidos']} grupo(s) protegido(s). Ausência de valor não significa zero.")
            if resultado.get("truncado"):
                st.caption("Resultado truncado: a consulta excedeu o limite de linhas.")
            data = datetime.fromisoformat(resultado["atualizado_em"]).astimezone(ZoneInfo("America/Sao_Paulo"))
            st.caption(f"Atualizado às {data:%H:%M} · {data:%d/%m/%Y}")
            st.caption("Escopo: " + ", ".join(resultado["escopo"]))
            if resultado.get("parametros"):
                st.write(resultado["parametros"])
            st.dataframe(dados, hide_index=True, width="stretch") if dados else st.caption("Sem linhas exibíveis.")


def workspace(sessao):
    with st.container(key="work_heading"):
        st.html('<div class="eyebrow">WORKSPACE</div><div class="panel-heading">Seu espaço de trabalho.</div><div class="panel-copy">As descobertas da conversa ganham espaço aqui.</div>')
    componentes = sessao.componentes() if sessao.perfil.papel != "administrador" and sessao.perfil.ufs else []
    filtro = "Tudo"
    if componentes:
        with st.container(key="work_toolbar"):
            filtros, encaixar = st.columns([3, 2], vertical_alignment="center")
            filtro = filtros.segmented_control("Conteúdo", ["Tudo", "Gráficos", "Dados", "Ações"], default="Tudo", key=f"filtro_{st.session_state.geracao}", label_visibility="collapsed") or "Tudo"
            if encaixar.button("Encaixar cartões", icon=":material/grid_view:", key="encaixar_cartoes", help="Organizar os cartões em colunas, sem sobreposição"):
                sessao.posicoes = {}
                sessao.posicoes_manuais = set()
                st.session_state.canvas_revision = st.session_state.get('canvas_revision', 0) + 1
                salvar_workspace()
                st.rerun()
        st.caption("Arraste pelo título para mover sem sobrepor. Peça ao Bob para editar.")
    with st.container(height=420, border=False, key="work_scroll"):
        if not componentes:
            st.html('''<div class="empty-work"><div class="empty-work-symbol">＋</div><div class="empty-work-title">Tudo começa com uma pergunta.</div><div class="empty-work-copy">Os gráficos, mapas, dados e ações criados pelo Bob aparecerão aqui.<br>Depois, organize do seu jeito.</div></div>''')
        else:
            tipos = {"Gráficos": {"indicador", "barras", "linhas", "mapa", "grafico"}, "Dados": {"tabela"}, "Ações": {"acao"}}
            visiveis = [c for c in componentes if filtro == "Tudo" or c["tipo"] in tipos[filtro]]
            if not visiveis:
                st.caption("Ainda não há cartões nesta categoria. Peça ao Bob no chat.")
            with st.container(key="work_canvas"):
                for componente in visiveis:
                    renderizar(componente, sessao)
            montar_canvas(sessao, visiveis, st.session_state.geracao)
        if sessao.backend.eventos:
            with st.expander("Consultas da sessão"):
                for evento in sessao.backend.eventos:
                    if evento.get("sql"):
                        st.caption(evento["objetivo"])
                        st.code(evento["sql"], language="sql")


def sugerir(pergunta):
    st.session_state.pergunta_sugerida = pergunta
    st.session_state.mobile_view = "Conversa"


def mostrar_rastreamento(rastreamento):
    def mostrar_valor(valor):
        # st.json interpreta strings como documentos JSON; perguntas são texto livre.
        if isinstance(valor, str):
            st.code(valor, language=None, wrap_lines=True)
        else:
            st.json(valor, expanded=True)

    agentes = {"principal": "Agente principal", "visual": "Agente visual", "sistema": "Sistema"}
    status = {"ok": "OK", "erro": "Erro", "publicado": "Publicado", "acesso_negado": "Acesso negado"}
    etapas = rastreamento["etapas"]
    chamadas = {e["numero"]: e for e in etapas if e["tipo"] == "tool_chamada"}
    visiveis = []
    for etapa in etapas:
        if etapa["tipo"] in {"pergunta", "contexto", "resposta_final", "tool_retorno"}:
            entrada = chamadas.get(etapa.get("chamada"), {}).get("entrada")
            visiveis.append({**etapa, **({"entrada": entrada} if entrada is not None else {})})
    consultas = [e for e in etapas if e["tipo"] == "tool_retorno" and e.get("ferramenta") == "consultar_dados"]
    reutilizadas = sum(bool(e.get("reutilizado")) for e in consultas)
    total_consultas = len(consultas) - reutilizadas
    with st.expander(f"Ver passos do Bob · {total_consultas} {'consulta' if total_consultas == 1 else 'consultas'}"):
        st.caption(f"{rastreamento['duracao_ms'] / 1000:.2f} s · {sum(e['tipo'] == 'agente_chamada' for e in etapas)} chamadas ao modelo · {reutilizadas} consultas reutilizadas")
        with st.container(height=300, border=False):
            for numero_etapa, etapa in enumerate(visiveis, 1):
                agente = agentes.get(etapa["agente"], etapa["agente"])
                tipo, estado = etapa["tipo"], status.get(etapa.get("status"), "")
                titulos = {"pergunta": "Pergunta recebida", "contexto": "Acesso e schema verificados",
                           "tool_retorno": f"{etapa.get('ferramenta', '')} → {agente}",
                           "resposta_final": "Resposta final"}
                with st.expander(f"{numero_etapa}. {titulos.get(tipo, tipo)}" + (f" · {estado}" if estado else "") + (" · Reutilizado" if etapa.get("reutilizado") else "")):
                    horario = datetime.fromisoformat(etapa["horario"]).astimezone(ZoneInfo("America/Sao_Paulo"))
                    st.caption(f"{horario:%H:%M:%S}" + (f" · {etapa['duracao_ms']} ms" if "duracao_ms" in etapa else ""))
                    if "entrada" in etapa:
                        st.caption("Entrada enviada")
                        mostrar_valor(etapa["entrada"])
                    if "saida" in etapa:
                        st.caption("Retorno da ferramenta")
                        mostrar_valor(etapa["saida"])
                    detalhes = {k: v for k, v in etapa.items() if k not in {"numero", "tipo", "agente", "horario", "duracao_ms", "entrada", "saida"}}
                    if detalhes:
                        st.json(detalhes, expanded=False)


def mensagem_chat(papel, texto, rastreamento=None):
    with st.chat_message(papel, avatar=":material/person:" if papel == "user" else ":material/blur_on:"):
        st.markdown(texto)
        if rastreamento:
            mostrar_rastreamento(rastreamento)


def chat(sessao, pode_analisar):
    escopo = "Brasil · 27 UFs" if len(sessao.perfil.ufs) == 27 else ", ".join(sessao.perfil.ufs) or "Sem escopo analítico"
    with st.container(key="chat_heading"):
        st.html(f'<div class="chat-heading">Bob <span class="scope">{escape(PAPEIS[sessao.perfil.papel])} · {escape(escopo)}</span></div>')
    with st.container(height=420, border=False, key="chat_log", autoscroll=True):
        historico = st.empty()
        with historico.container():
            if not sessao.mensagens:
                st.html('''<div class="welcome"><div class="welcome-icon">b</div><div class="welcome-title">O que vamos descobrir?</div><div class="welcome-copy">Explore seus dados. Gráficos, mapas e ideias de ações ganham espaço no workspace.</div></div>''')
                with st.container(key="suggestions"):
                    for inicio in (0, 2):
                        for coluna, (titulo, icone, pergunta) in zip(st.columns(2, gap="small", wrap=False), SUGESTOES[inicio:inicio + 2]):
                            coluna.button(titulo, icon=icone, key=f"sugestao_{inicio}_{titulo}", help=pergunta, width="stretch", wrap=True,
                                          disabled=not pode_analisar, on_click=sugerir, args=(pergunta,))
            for mensagem in sessao.mensagens:
                mensagem_chat(mensagem["role"], mensagem["content"], mensagem.get("rastreamento"))
    return historico


def composer(sessao, pode_analisar, historico):
    # Irmão do histórico rolável: a entrada fica sempre na base do painel.
    with st.container(key="composer"):
        chave = f"chat_{st.session_state.geracao}"
        # Capture antes de desabilitar: o widget desabilitado limpa seu valor submetido.
        submetida = st.session_state.get(chave)
        enviando = bool(submetida or st.session_state.get("pergunta_sugerida"))
        digitada = st.chat_input("Pergunte ao Bob…", max_chars=4000,
                                disabled=not pode_analisar or enviando, key=chave)
        pergunta = st.session_state.pop("pergunta_sugerida", None) or submetida or digitada
        if pergunta and pode_analisar:
            # Substitui a tela inicial antes da chamada bloqueante ao agente.
            # A pergunta é desenhada aqui; conversar a registra uma única vez.
            with historico.container():
                for mensagem in sessao.mensagens:
                    mensagem_chat(mensagem["role"], mensagem["content"], mensagem.get("rastreamento"))
                mensagem_chat("user", pergunta)
            # Fora da área rolável: a espera permanece visível mesmo com histórico longo.
            with st.spinner("Bob está analisando sua pergunta…", show_time=True):
                sessao.conversar(pergunta)
            salvar_workspace()
            st.rerun()
        if not pode_analisar:
            st.caption("Seu perfil não permite consultas. Ajuste a engrenagem.")
        elif not sessao.client.api_key:
            st.caption("Configure a chave do OpenRouter no .env para conversar.")
        else:
            st.html('<div class="composer-hint">Enter envia · Shift + Enter cria uma nova linha</div>')


def main():
    st.set_page_config(page_title="Bob Space", page_icon="◼", layout="wide", initial_sidebar_state="collapsed")
    load_dotenv(RAIZ / ".env")
    st.html(RAIZ / "assets" / "space.css")
    # Script local fixo; nunca recebe texto ou código produzido pelo agente.
    st.html(RAIZ / "assets" / "viewport.html", unsafe_allow_javascript=True)
    # Uma classe antiga no cache de imports não é corrigida recriando a sessão.
    if not all(callable(getattr(SessaoLocal, nome, None)) for nome in METODOS_SESSAO):
        st.error("O servidor está com uma versão antiga de SessaoLocal carregada. No terminal, pressione Ctrl+C e execute novamente o comando abaixo; depois atualize esta página.")
        st.code(r".\.venv\Scripts\python.exe -m streamlit run app.py", language="powershell")
        st.stop()
    anterior = st.session_state.get("sessao")
    if not sessao_compativel(anterior) or st.session_state.get("workspace_revision") != 2:
        perfil = anterior.perfil if anterior else Usuario(id="simulacao_local", papel="analista", ufs=tuple(sorted(UFS)))
        st.session_state.sessao = SessaoLocal(BANCO, perfil)
        st.session_state.geracao = st.session_state.get("geracao", -1) + 1
        st.session_state.workspace_revision = 2
        st.session_state.modal_permissoes = False
        if anterior:
            st.session_state.aviso = "A sessão foi atualizada. Seu perfil e suas permissões foram mantidos; conversa e workspace foram reiniciados."
    conectar_workspace(BANCO)
    sessao = st.session_state.sessao
    if st.session_state.get("modal_permissoes", False):
        permissoes()
    if aviso := st.session_state.pop("aviso", None):
        st.toast(aviso, icon=":material/check_circle:")
    pode_analisar = sessao.perfil.papel == "analista" and bool(sessao.perfil.ufs)
    try:
        with st.container(key="space_shell"):
            with st.container(key="space_header"):
                marca, nova, config = st.columns([9, 2, .6], vertical_alignment="center", wrap=False)
                marca.html('<div class="brand"><div class="brand-mark">b</div><div class="brand-name">bob <span>space</span></div><span class="brand-note">UM ESPAÇO PARA DESCOBRIR</span></div>')
                if nova.button("Nova sessão", icon=":material/add:", width="stretch", help="Limpa conversa, resultados e painéis"):
                    reiniciar()
                if config.button("", icon=":material/settings:", help="Customizar permissões da simulação", width="stretch"):
                    st.session_state.modal_permissoes = True
                    st.rerun()
            with st.container(key="mobile_nav"):
                st.session_state.setdefault("mobile_view", "Conversa")
                area = st.segmented_control("Área", ["Conversa", "Workspace"], required=True,
                                            key="mobile_view", label_visibility="collapsed", width="stretch")
            with st.container(key=f"view_{'workspace' if area == 'Workspace' else 'conversa'}"):
                with st.container(key="space_body"):
                    work, conversa = st.columns([2, 1], gap="medium", wrap=False)
                    with work, st.container(key="work_panel"):
                        workspace(sessao)
                    with conversa, st.container(key="chat_panel"):
                        historico = chat(sessao, pode_analisar)
                        composer(sessao, pode_analisar, historico)
        salvar_workspace()
    except BobError as erro:
        st.error(str(erro))


if __name__ == "__main__":
    main()
