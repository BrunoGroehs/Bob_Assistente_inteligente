"""Catálogo e regras dos gráficos, compartilhados pelo contrato e pelos agentes."""

from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Literal

TemplateGrafico = Literal[
    "barras_horizontais", "barras_verticais", "barras_agrupadas",
    "barras_empilhadas", "composicao_percentual", "linha_temporal",
    "linhas_multiplas", "area_temporal", "area_empilhada", "pizza", "rosca",
    "dispersao", "mapa_calor",
]


@dataclass(frozen=True)
class Template:
    nome: str
    uso: str
    eixo_x: Literal["categoria", "tempo", "numero"] = "categoria"
    serie: Literal["obrigatoria", "opcional", "proibida"] = "proibida"
    partes_exclusivas: bool = False
    nao_negativo: bool = False
    percentual: bool = False


TEMPLATES = {
    "barras_horizontais": Template("Barras horizontais", "Rankings e categorias com nomes longos."),
    "barras_verticais": Template("Barras verticais", "Comparação direta entre categorias."),
    "barras_agrupadas": Template("Barras agrupadas", "Comparar séries lado a lado por categoria.", serie="obrigatoria"),
    "barras_empilhadas": Template("Barras empilhadas", "Composição aditiva por categoria; não empilhar médias ou grupos sobrepostos.", serie="obrigatoria", partes_exclusivas=True, nao_negativo=True),
    "composicao_percentual": Template("Composição percentual", "Participação de cada série no total da categoria, em 100%.", serie="obrigatoria", partes_exclusivas=True, nao_negativo=True, percentual=True),
    "linha_temporal": Template("Linha temporal", "Evolução de uma métrica no tempo.", eixo_x="tempo"),
    "linhas_multiplas": Template("Linhas por série", "Comparar tendências de diferentes séries.", eixo_x="tempo", serie="obrigatoria"),
    "area_temporal": Template("Área temporal", "Evolução de volume não negativo.", eixo_x="tempo", nao_negativo=True),
    "area_empilhada": Template("Área empilhada", "Composição aditiva de volume ao longo do tempo.", eixo_x="tempo", serie="obrigatoria", partes_exclusivas=True, nao_negativo=True),
    "pizza": Template("Pizza", "Gráfico de pizza para participação de até 8 categorias exclusivas em um total.", partes_exclusivas=True, nao_negativo=True, percentual=True),
    "rosca": Template("Rosca", "Composição de um total com até 8 categorias exclusivas; prefira barras para rankings.", partes_exclusivas=True, nao_negativo=True, percentual=True),
    "dispersao": Template("Dispersão", "Relação entre duas métricas agregadas; não prova causalidade.", eixo_x="numero", serie="opcional"),
    "mapa_calor": Template("Mapa de calor", "Intensidade de uma métrica no cruzamento de duas categorias.", serie="obrigatoria"),
}


def catalogo_para_agente():
    linhas = ["Para estes templates use tipo='grafico', template, x e y (métrica numérica)."]
    for id_, template in TEMPLATES.items():
        partes = " Exige partes_exclusivas=true, com métrica aditiva e categorias sem sobreposição." if template.partes_exclusivas else ""
        linhas.append(f"- {id_}: {template.uso} x={template.eixo_x}; serie={template.serie}.{partes}")
    linhas.append("Campos são nomes reais do dataset. serie é a categoria da legenda; no mapa_calor é a segunda dimensão. Use formato longo: uma linha por x/serie. Não agregue, preencha zeros, invente dados ou calcule novas métricas no agente visual. Datas: YYYY, YYYY-MM ou YYYY-MM-DD. Resultados parciais não servem como total de composição.")
    return "\n".join(linhas)


def data_iso(valor):
    """Padroniza granularidades ISO sem alterar o período da observação."""
    if not isinstance(valor, str) or len(valor) not in (4, 7, 10):
        raise ValueError("O eixo temporal precisa de datas ISO: YYYY, YYYY-MM ou YYYY-MM-DD.")
    completo = valor + ("-01-01" if len(valor) == 4 else "-01" if len(valor) == 7 else "")
    try:
        return date.fromisoformat(completo).isoformat()
    except ValueError:
        raise ValueError("O eixo temporal contém uma data inválida.") from None


def validar_template(componente, dataset):
    """Valida o resultado agregado, inclusive em refresh, sem consultar outro escopo."""
    template = TEMPLATES[componente["template"]]
    x, y, serie = (componente.get(c) for c in ("x", "y", "serie"))
    if not x or not y:
        raise ValueError("Templates de gráficos precisam dos campos x e y.")
    if template.serie == "obrigatoria" and not serie:
        raise ValueError("Este template precisa de serie, com uma categoria por linha.")
    if template.serie == "proibida" and serie:
        raise ValueError("Este template não usa serie. Escolha sua variante com séries.")
    campos = [x, y] + ([serie] if serie else [])
    if len(set(campos)) != len(campos) or any(c not in dataset["colunas"] for c in campos):
        raise ValueError("Os campos do template devem existir no resultado e ser diferentes.")
    if template.partes_exclusivas and not componente.get("partes_exclusivas"):
        raise ValueError("Declare partes_exclusivas=true somente para métricas aditivas e categorias sem sobreposição. Em dúvida, use barras agrupadas.")
    if template.partes_exclusivas and (dataset.get("truncado") or dataset.get("grupos_suprimidos")):
        raise ValueError("Composição exige resultados completos: grupos suprimidos ou truncamento impedem representar o total.")
    if not dataset["dados"]:
        return  # A interface apresenta um estado vazio; não inventa pontos ou zero.
    vistos, totais, periodos = set(), {}, set()
    for linha in dataset["dados"]:
        valor = linha[y]
        if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not isfinite(valor):
            raise ValueError("A métrica do gráfico precisa conter números finitos, sem nulos.")
        if template.nao_negativo and valor < 0:
            raise ValueError("Este template não admite valores negativos.")
        chave_x = linha[x]
        if chave_x is None or (serie and linha[serie] is None):
            raise ValueError("Dimensões nulas devem ser tratadas na consulta ou apresentadas em tabela.")
        if template.eixo_x == "tempo":
            periodos.add(len(chave_x) if isinstance(chave_x, str) else 0)
            chave_x = data_iso(chave_x)
        if template.eixo_x == "numero" and (isinstance(chave_x, bool) or not isinstance(chave_x, (int, float)) or not isfinite(chave_x)):
            raise ValueError("Dispersão precisa de uma métrica numérica também em x.")
        chave = (chave_x, linha[serie] if serie else None)
        if template.eixo_x != "numero" and chave in vistos:
            raise ValueError("Há mais de uma linha por x/serie. Agregue corretamente antes de publicar.")
        vistos.add(chave)
        totais[chave_x] = totais.get(chave_x, 0) + valor
    if len(periodos) > 1:
        raise ValueError("Use a mesma granularidade temporal em todas as linhas.")
    if template.partes_exclusivas and any(not isfinite(total) for total in totais.values()):
        raise ValueError("O total excedeu o intervalo numérico suportado.")
    if template.percentual:
        bases = list(totais.values()) if serie else [sum(totais.values())]
        if any(not isfinite(base) or base <= 0 for base in bases):
            raise ValueError("Uma composição precisa de total positivo; total zero não define participação.")
    if componente["template"] in {"pizza", "rosca"} and len(vistos) > 8:
        raise ValueError("Pizza e rosca aceitam até 8 categorias. Use barras para mais categorias.")
