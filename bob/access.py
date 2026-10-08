"""O contexto vem do backend, nunca dos argumentos que a IA inventar."""

import json
import re
import unicodedata
from pathlib import Path

from .schemas import BobError, UFS, Usuario

# Nomes completos evitam confundir a preposição "para" com o estado Pará.
ESTADOS = dict(zip(
    ["Acre", "Alagoas", "Amapá", "Amazonas", "Bahia", "Ceará", "Distrito Federal",
     "Espírito Santo", "Goiás", "Maranhão", "Mato Grosso", "Mato Grosso do Sul",
     "Minas Gerais", "Pará", "Paraíba", "Paraná", "Pernambuco", "Piauí",
     "Rio de Janeiro", "Rio Grande do Norte", "Rio Grande do Sul", "Rondônia",
     "Roraima", "Santa Catarina", "São Paulo", "Sergipe", "Tocantins"],
    "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split(),
))


def uf_do_estado(valor: str) -> str | None:
    def normalizar(texto):
        return "".join(c for c in unicodedata.normalize("NFD", texto.strip()) if not unicodedata.combining(c)).upper()
    nome = normalizar(valor)
    if nome in UFS:
        return nome
    return next((uf for estado, uf in ESTADOS.items() if normalizar(estado) == nome), None)


def ufs_no_texto(texto: str) -> set[str]:
    ufs = set(re.findall(r"\b[A-Z]{2}\b", texto)) & UFS
    for nome in sorted(ESTADOS, key=len, reverse=True):
        pattern = rf"\b{re.escape(nome)}\b"
        if re.search(pattern, texto, re.IGNORECASE):
            ufs.add(ESTADOS[nome])
            texto = re.sub(pattern, "", texto, flags=re.IGNORECASE)
    ufs.update(re.findall(r"\b(?:em|no|na|estado de)\s+([a-z]{2})\b", texto, re.IGNORECASE))
    return {uf.upper() for uf in ufs if uf.upper() in UFS}


def exigir_acesso(usuario: Usuario, acao: str, ufs=()):
    permissoes = {
        "leitor": {"ler", "atualizar"},
        "analista": {"ler", "atualizar", "consultar", "publicar"},
        "administrador": {"gerenciar_acessos"},
    }
    if acao not in permissoes[usuario.papel] or (acao != "gerenciar_acessos" and not usuario.ufs):
        raise BobError("ACESSO_PAPEL", "Seu perfil não permite esta operação de análise.")
    if not set(ufs) <= set(usuario.ufs):
        raise BobError("ACESSO_ESCOPO", f"Seu acesso às análises está limitado a {', '.join(usuario.ufs)}. A solicitação está fora desse escopo.")


def carregar_usuario(arquivo: Path, usuario_id: str) -> Usuario:
    """Arquivo local confiável; a futura interface deverá usar identidade autenticada."""
    try:
        registros = json.loads(arquivo.read_text(encoding="utf-8"))
        return Usuario.model_validate(registros[usuario_id])
    except (KeyError, ValueError, OSError):
        raise BobError("ACESSO_USUARIO", "Usuário ausente ou configuração de acesso inválida.") from None


def proteger_texto(texto: str) -> str:
    """Bloqueia identificadores comuns; não é uma solução completa de DLP."""
    if re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b\d{3}[. ]?\d{3}[. ]?\d{3}[- ]?\d{2}\b", texto):
        raise BobError("DADOS_PESSOAIS", "Não envie e-mails ou documentos pessoais. Reformule a pergunta como uma análise agregada.")
    if re.search(r"\b(cpf|(?:e-?mails?|telefones?|endereços?|nomes?) (?:dos?|das?) clientes?|listar clientes)\b", texto, re.IGNORECASE):
        raise BobError("DADOS_PESSOAIS", "Este assistente trabalha com análises agregadas, sem listar dados pessoais dos clientes.")
    return texto

