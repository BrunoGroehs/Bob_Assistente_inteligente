"""Demonstração local do backend; seleção de perfil não substitui um login."""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from .access import carregar_usuario
from .agents import Agentes
from .openrouter import OpenRouter
from .schemas import BobError
from .tools import Backend

RAIZ = Path(__file__).resolve().parent.parent


def mostrar(valor):
    print(json.dumps(valor, ensure_ascii=False, indent=2))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Bob Space: CLI local de demonstração do backend.")
    parser.add_argument("--banco", type=Path, default=RAIZ / "data" / "anexo_desafio_1.db")
    parser.add_argument("--usuarios", type=Path, default=RAIZ / "usuarios.exemplo.json")
    parser.add_argument("--usuario", default="analista_sp")
    modos = parser.add_mutually_exclusive_group()
    modos.add_argument("--demo", action="store_true", help="Consulta e publica um painel sem usar IA.")
    modos.add_argument("--pergunta")
    modos.add_argument("--sql")
    parser.add_argument("--objetivo", default="Análise agregada no escopo autorizado.")
    parser.add_argument("--ufs", nargs="*", default=[])
    args = parser.parse_args()
    load_dotenv(RAIZ / ".env")
    backend = Backend(args.banco, lambda: carregar_usuario(args.usuarios, args.usuario))
    client = OpenRouter()
    agentes = Agentes(backend, client)
    try:
        if args.sql:
            mostrar(backend.consultar_dados(args.sql, {"descricao": args.objetivo, "ufs_solicitadas": args.ufs}))
        elif args.demo:
            resultado = backend.consultar_dados("SELECT canal, COUNT(*) AS reclamacoes FROM suporte WHERE tipo_contato='Reclamação' AND resolvido=0 GROUP BY canal ORDER BY reclamacoes DESC", {"descricao": "Reclamações não resolvidas por canal."})
            if resultado["status"] != "ok":
                mostrar(resultado)
                return
            backend.publicar_painel({"componentes": [{"id": "reclamacoes", "tipo": "barras", "dataset_id": resultado["dataset_id"], "titulo": "Reclamações não resolvidas por canal", "x": "canal", "y": "reclamacoes"}]})
            mostrar({"workspace": backend.workspace(), "refresh": backend.atualizar_componente("reclamacoes")})
        elif args.pergunta:
            mostrar(agentes.conversar(args.pergunta))
        else:
            print("Sessão local de demonstração. Comandos: /painel, /atualizar ID, /sair")
            while True:
                pergunta = input("Você: ").strip()
                if pergunta == "/sair":
                    break
                if pergunta == "/painel":
                    mostrar(backend.workspace())
                elif pergunta.startswith("/atualizar "):
                    mostrar(backend.atualizar_componente(pergunta.split(maxsplit=1)[1]))
                elif pergunta:
                    mostrar(agentes.conversar(pergunta))
        if client.uso:
            mostrar({"uso_modelo": client.uso})
    except BobError as erro:
        mostrar(erro.resposta())
    except (EOFError, KeyboardInterrupt):
        print("Sessão encerrada.")


if __name__ == "__main__":
    main()
