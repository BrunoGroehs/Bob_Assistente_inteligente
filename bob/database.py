"""SQL da IA só é executado em um recorte analítico, nunca no arquivo original."""

import sqlite3
from contextlib import closing
from pathlib import Path
from time import monotonic

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from .access import exigir_acesso, uf_do_estado
from .schemas import BobError, UFS, Usuario

# Lista de colunas aprovadas, independente das instruções do modelo.
COLUNAS = {
    "clientes": ("id", "estado"),
    "compras": ("cliente_id", "data_compra", "valor", "categoria", "canal"),
    "suporte": ("cliente_id", "data_contato", "tipo_contato", "resolvido", "canal"),
    "campanhas_marketing": ("cliente_id", "data_envio", "canal", "interagiu"),
}
DIMENSOES = {"estado", "categoria", "canal", "tipo_contato", "resolvido", "interagiu"}
FUNCOES = {"COUNT", "SUM", "AVG", "MIN", "MAX", "ROUND", "NULLIF", "COALESCE", "TIME_TO_STR", "TS_OR_DS_TO_TIMESTAMP"}


def abrir_recorte(caminho: Path, usuario: Usuario) -> sqlite3.Connection:
    """Filtra todos os relacionamentos e remove identificadores pessoais na origem."""
    exigir_acesso(usuario, "ler")
    recorte = sqlite3.connect(":memory:")
    try:
        with closing(sqlite3.connect(caminho.resolve().as_uri() + "?mode=ro", uri=True)) as fonte:
            fonte.execute("BEGIN")
            estados = [r[0] for r in fonte.execute('SELECT DISTINCT estado FROM clientes') if r[0] and uf_do_estado(r[0]) in usuario.ufs]
            marcadores = ",".join("?" for _ in estados) or "NULL"
            mapa = {}
            for tabela, aprovadas in COLUNAS.items():
                existentes = {r[1]: r[2] for r in fonte.execute(f'PRAGMA table_info("{tabela}")')}
                colunas = [c for c in aprovadas if c in existentes]
                essenciais = {"id", "estado"} if tabela == "clientes" else {"cliente_id"}
                if not essenciais <= set(colunas):
                    raise BobError("BANCO_SCHEMA", "O banco não possui os relacionamentos necessários ao recorte seguro.")
                # Os tipos são determinados pelo backend, não pelo DDL do banco original.
                ddl = ",".join(f'"{c}" ' + ("REAL" if c == "valor" else "INTEGER" if c in {"id", "cliente_id", "resolvido", "interagiu"} else "TEXT") for c in colunas)
                recorte.execute(f'CREATE TABLE "{tabela}" ({ddl})')
                campos = ",".join(f't."{c}"' for c in colunas)
                join = "" if tabela == "clientes" else "JOIN clientes c ON c.id=t.cliente_id"
                estado = "t.estado" if tabela == "clientes" else "c.estado"
                linhas = fonte.execute(f'SELECT {campos} FROM "{tabela}" t {join} WHERE {estado} IN ({marcadores})', estados).fetchall()
                for linha in linhas:
                    valores = list(linha)
                    indice = colunas.index("id" if tabela == "clientes" else "cliente_id")
                    if tabela == "clientes":
                        mapa[valores[indice]] = len(mapa) + 1
                        valores[colunas.index("estado")] = uf_do_estado(valores[colunas.index("estado")])
                    valores[indice] = mapa[valores[indice]]
                    recorte.execute(f'INSERT INTO "{tabela}" VALUES ({",".join("?" for _ in colunas)})', valores)
        recorte.commit()
        recorte.execute("PRAGMA query_only=ON")
        recorte.row_factory = sqlite3.Row
        return recorte
    except sqlite3.Error:
        recorte.close()
        raise BobError("BANCO_INDISPONIVEL", "Não foi possível abrir ou preparar o banco analítico. Confira o arquivo e sua estrutura.") from None
    except Exception:
        recorte.close()
        raise


def descobrir_schema(conexao):
    return {t: {r[1]: r[2] for r in conexao.execute(f'PRAGMA table_info("{t}")')} for t in COLUNAS}


def validar_sql(sql: str, schema: dict, usuario: Usuario, acao="consultar", periodo_relativo=False):
    """Subconjunto intencional: agregações, dimensões e até um JOIN com clientes."""
    try:
        consultas = parse(sql, read="sqlite")
    except ParseError:
        raise BobError("SQL_INVALIDO", "SQL inválido. Confira a sintaxe e o schema disponível.") from None
    if len(consultas) != 1 or not isinstance(consultas[0], exp.Select):
        raise BobError("SQL_BLOQUEADO", "Somente uma consulta SELECT agregada é permitida.")
    q = consultas[0]
    if len(list(q.find_all(exp.Select))) != 1 or any(q.args.get(a) for a in ("with_", "having", "offset", "distinct", "into")) or any(q.find(t) for t in (exp.Window, exp.Case, exp.If, exp.Filter)):
        raise BobError("SQL_BLOQUEADO", "Use consultas agregadas simples, sem subconsultas, CTE, HAVING ou janelas. Investigue em consultas separadas.")
    tabelas = list(q.find_all(exp.Table))
    if not 1 <= len(tabelas) <= 2 or any(t.name not in schema or t.db or t.catalog for t in tabelas):
        raise BobError("SQL_BLOQUEADO", "Consulte uma tabela analítica ou una clientes a uma única tabela de eventos.")
    aliases = {t.alias_or_name: t.name for t in tabelas}
    if len(aliases) != len(tabelas):
        raise BobError("SQL_INVALIDO", "Os aliases das tabelas devem ser diferentes.")
    for coluna in q.find_all(exp.Column):
        if coluna.name in {"nome", "email", "cpf", "telefone", "cidade", "idade", "profissao", "genero"}:
            raise BobError("COLUNA_PRIVADA", "Dados pessoais não fazem parte do banco analítico.")
    exigir_acesso(usuario, acao, {uf_do_estado(v.this) for v in q.find_all(exp.Literal) if v.is_string and uf_do_estado(v.this)})
    if periodo_relativo:
        where = q.args.get("where")
        inicio, fim = [], []
        if where:
            for tipo, parametro, destinos in ((exp.GTE, "inicio", inicio), (exp.LT, "fim", fim)):
                for filtro in where.find_all(tipo):
                    if isinstance(filtro.this, exp.Column) and filtro.this.name.startswith("data_") and isinstance(filtro.expression, exp.Placeholder) and filtro.expression.this == parametro:
                        destinos.append(filtro.this.sql())
        if not where or where.find(exp.Or) or not set(inicio) & set(fim):
            raise BobError("PERIODO_INVALIDO", "O período relativo exige a mesma data >= :inicio AND data < :fim, sem OR que contorne o intervalo.")
    for funcao in q.find_all(exp.Func):
        if not isinstance(funcao, (exp.And, exp.Or)) and funcao.sql_name() not in FUNCOES:
            raise BobError("SQL_BLOQUEADO", "Função não permitida. Use agregações e STRFTIME para ano ou mês.")
    if not q.find(exp.AggFunc):
        raise BobError("PRIVACIDADE_AGREGACAO", "Listagens individuais não são permitidas. Use COUNT, SUM ou AVG.")

    def agrupar(expressao):
        if isinstance(expressao, exp.Column):
            return expressao.name in DIMENSOES
        if isinstance(expressao, exp.TimeToStr):
            coluna = expressao.this.this if isinstance(expressao.this, exp.TsOrDsToTimestamp) else expressao.this
            return isinstance(coluna, exp.Column) and coluna.name.startswith("data_") and expressao.args["format"].this in {"%Y", "%Y-%m"}
        return False

    grupos = q.args.get("group")
    grupos = grupos.expressions if grupos else []
    if any(not agrupar(g) for g in grupos):
        raise BobError("PRIVACIDADE_GRUPO", "Agrupe por dimensões aprovadas, ano ou mês. Não agrupe por cliente, valor ou data individual.")
    for item in q.expressions:
        valor = item.this if isinstance(item, exp.Alias) else item
        if not valor.find(exp.AggFunc) and not isinstance(valor, exp.AggFunc):
            if not agrupar(valor) or valor.sql() not in {g.sql() for g in grupos}:
                raise BobError("PRIVACIDADE_AGREGACAO", "Cada coluna deve ser uma dimensão agrupada ou uma métrica agregada.")
        # Colunas fora de agregações não podem ser escondidas em expressões numéricas.
        for coluna in valor.find_all(exp.Column):
            if not coluna.find_ancestor(exp.AggFunc) and not agrupar(valor):
                raise BobError("PRIVACIDADE_AGREGACAO", "A expressão contém um detalhe individual não agregado.")
        if valor.find(exp.Star) and not valor.find(exp.Count):
            raise BobError("SQL_BLOQUEADO", "SELECT * não é permitido.")
    for coluna in q.find_all(exp.Column):
        if coluna.name in {"id", "cliente_id"}:
            contador = coluna.find_ancestor(exp.Count)
            direto = contador and (contador.this == coluna or isinstance(contador.this, exp.Distinct) and contador.this.expressions == [coluna])
            if not coluna.find_ancestor(exp.Join) and not direto:
                raise BobError("PRIVACIDADE_IDENTIFICADOR", "Referências de clientes só podem ser usadas no relacionamento e em COUNT.")

    joins = q.args.get("joins") or []
    if len(tabelas) == 2:
        if len(joins) != 1 or "clientes" not in aliases.values():
            raise BobError("SQL_BLOQUEADO", "Una clientes a somente uma tabela de eventos.")
        clientes = next(a for a, t in aliases.items() if t == "clientes")
        eventos = next((a for a, t in aliases.items() if t != "clientes"), None)
        on = joins[0].args.get("on")
        esperado = {(clientes, "id"), (eventos, "cliente_id")}
        if not isinstance(on, exp.EQ) or not all(isinstance(c, exp.Column) for c in (on.this, on.expression)) or {(c.table, c.name) for c in (on.this, on.expression)} != esperado:
            raise BobError("SQL_BLOQUEADO", "O JOIN deve relacionar clientes.id ao cliente_id da tabela de eventos.")
    if not q.args.get("from_") or not isinstance(q.args["from_"].this, exp.Table):
        raise BobError("SQL_BLOQUEADO", "Informe uma tabela analítica no FROM.")
    q = q.copy()
    limite = q.args.get("limit")
    if limite and (not isinstance(limite.expression, exp.Literal) or limite.expression.is_string or not limite.expression.this.isdigit()):
        raise BobError("SQL_BLOQUEADO", "LIMIT deve ser um inteiro positivo.")
    q.limit(min(int(limite.expression.this), 201) if limite else 201, copy=False)
    return q.sql(dialect="sqlite")


def executar(conexao, sql: str, parametros: dict, schema: dict):
    """Segunda barreira no próprio SQLite, além da validação da árvore SQL."""
    inicio = monotonic()

    def autorizar(acao, arg1, arg2, *_):
        if acao == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if acao == sqlite3.SQLITE_READ and arg1 in schema and (not arg2 or arg2 in schema[arg1]):
            return sqlite3.SQLITE_OK
        if acao == sqlite3.SQLITE_FUNCTION and arg2 in {"count", "sum", "avg", "min", "max", "round", "nullif", "coalesce", "strftime"}:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    conexao.set_authorizer(autorizar)
    conexao.set_progress_handler(lambda: int(monotonic() - inicio > 2), 1000)
    try:
        cursor = conexao.execute(sql, parametros)
        colunas = [c[0] for c in cursor.description]
        if len(set(colunas)) != len(colunas):
            raise BobError("SQL_INVALIDO", "Use nomes únicos para as métricas e dimensões.")
        linhas = cursor.fetchmany(201)
        dados = [dict(linha) for linha in linhas[:200]]
        tipos = {c: next(("numero" if isinstance(l[c], (int, float)) else "texto" for l in linhas if l[c] is not None), "desconhecido") for c in colunas}
        # Campo mantido no contrato dos datasets; não há supressão por quantidade.
        return {"dados": dados, "colunas": colunas, "tipos": tipos, "quantidade_linhas": len(dados), "truncado": len(linhas) > 200, "grupos_suprimidos": 0, "duracao_ms": round((monotonic() - inicio) * 1000)}
    except sqlite3.Error as erro:
        codigo = "SQL_TIMEOUT" if "interrupted" in str(erro) else "SQL_INVALIDO"
        raise BobError(codigo, "A consulta falhou. Confira o schema e simplifique o SQL; nomes de colunas devem existir no recorte.") from None
    finally:
        conexao.set_authorizer(None)
        conexao.set_progress_handler(None, 0)
