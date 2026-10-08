"""Renderizadores fixos Altair; o agente seleciona campos e templates, nunca código."""

import altair as alt

from .chart_templates import TEMPLATES, data_iso, validar_template

COR = "#3f6679"
PALETA = ["#3f6679", "#88abb8", "#536c5e", "#9ab6a4", "#80738e", "#b6abc1", "#bc966b", "#d3b899"]


def campo(nome):
    # Evita interpretar pontos e colchetes de um alias SQL como caminhos em objetos.
    return nome.replace("\\", "\\\\").replace(".", "\\.").replace("[", "\\[").replace("]", "\\]")


def criar_grafico(componente, dataset):
    """Desenha valores já agregados; empilhamento e normalização são visuais."""
    legado = componente["tipo"] != "grafico"
    template_id = componente.get("template") or ("barras_horizontais" if componente["tipo"] == "barras" else "linha_temporal")
    template = TEMPLATES[template_id]
    if not legado:
        validar_template(componente, dataset)
    x, y, serie = componente["x"], componente["y"], componente.get("serie")
    dados = [dict(linha) for linha in dataset["dados"]]
    if template.eixo_x == "tempo" and not legado:
        for linha in dados:
            linha[x] = data_iso(linha[x])
    base = alt.Chart(alt.Data(values=dados))
    tipo_x = "ordinal" if legado and componente["tipo"] == "linhas" else {"categoria": "nominal", "tempo": "temporal", "numero": "quantitative"}[template.eixo_x]
    eixo_x = alt.X(field=campo(x), type=tipo_x, title=x)
    eixo_y = alt.Y(field=campo(y), type="quantitative", title=y, stack=None)
    tooltip = [alt.Tooltip(field=campo(x), type=tipo_x, title=x), alt.Tooltip(field=campo(y), type="quantitative", title=y)]
    if template_id in {"pizza", "rosca"} and dados:
        participacao = "__participacao"
        while participacao in dados[0]:
            participacao += "_"
        total = sum(linha[y] for linha in dados)
        for linha in dados:
            linha[participacao] = linha[y] / total
        tooltip.append(alt.Tooltip(field=campo(participacao), type="quantitative", title="Participação", format=".2%"))
    if serie:
        tooltip.append(alt.Tooltip(field=campo(serie), type="nominal", title=serie))
    cores = alt.Color(field=campo(serie or x), type="nominal", title=serie or x, scale=alt.Scale(range=PALETA), legend=alt.Legend(orient="bottom"))
    if template_id == "barras_horizontais":
        grafico = base.mark_bar(color=COR, cornerRadiusEnd=4).encode(
            x=alt.X(field=campo(y), type="quantitative", title=y),
            y=alt.Y(field=campo(x), type="nominal", title=None, sort="-x"))
    elif template_id == "barras_verticais":
        grafico = base.mark_bar(color=COR, cornerRadiusEnd=4).encode(x=eixo_x, y=eixo_y)
    elif template_id == "barras_agrupadas":
        grafico = base.mark_bar(cornerRadiusEnd=3).encode(x=eixo_x, y=eixo_y, color=cores,
            xOffset=alt.XOffset(field=campo(serie), type="nominal"))
    elif template_id in {"barras_empilhadas", "composicao_percentual"}:
        eixo_y.stack = "normalize" if template.percentual else "zero"
        if template.percentual:
            eixo_y.title, eixo_y.axis = "Participação", alt.Axis(format="%")
        grafico = base.mark_bar().encode(x=eixo_x, y=eixo_y, color=cores)
    elif template_id in {"linha_temporal", "linhas_multiplas"}:
        grafico = base.mark_line(color=COR, point=True).encode(x=eixo_x, y=eixo_y)
        if serie:
            grafico = grafico.encode(color=cores)
    elif template_id in {"area_temporal", "area_empilhada"}:
        eixo_y.stack = "zero" if serie else None
        grafico = base.mark_area(color=COR, opacity=.65).encode(x=eixo_x, y=eixo_y)
        if serie:
            grafico = grafico.encode(color=cores)
    elif template_id in {"pizza", "rosca"}:
        grafico = base.mark_arc(innerRadius=65 if template_id == "rosca" else 0, outerRadius=110, stroke="#fff", strokeWidth=2).encode(
            theta=alt.Theta(field=campo(y), type="quantitative", stack="zero"), color=cores)
    elif template_id == "dispersao":
        grafico = base.mark_circle(color=COR, size=100, opacity=.8).encode(x=eixo_x, y=eixo_y)
        if serie:
            grafico = grafico.encode(color=cores)
    elif template_id == "mapa_calor":
        grafico = base.mark_rect(cornerRadius=2).encode(x=eixo_x,
            y=alt.Y(field=campo(serie), type="nominal", title=serie),
            color=alt.Color(field=campo(y), type="quantitative", title=y,
                            scale=alt.Scale(range=["#edf3f5", "#2c5b70"]), legend=alt.Legend(orient="bottom")))
    else:
        raise ValueError("Template sem renderizador.")
    destaque = alt.selection_point(name="destaque", fields=[x], on="click", clear="dblclick")
    grafico = grafico.add_params(destaque).encode(opacity=alt.condition(destaque, alt.value(1), alt.value(.25)))
    if template.eixo_x in {"tempo", "numero"} and not legado:
        grafico = grafico.interactive()
    return grafico.encode(tooltip=tooltip).properties(height=260).configure_view(stroke=None).configure_axis(
        labelColor="#71717a", titleColor="#71717a", gridColor="#f1f1f3", domain=False, tickSize=0,
    )
