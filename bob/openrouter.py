"""Cliente HTTP pequeno. Não imprime chave nem respostas de erro do provedor."""

import os
from time import monotonic

import httpx

from .schemas import BobError


class OpenRouter:
    def __init__(self, api_key=None, model=None, transport=None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.model = model or os.getenv("OPENROUTER_MODEL", "qwen/qwen3.6-plus")
        self.transport = transport
        self.uso = []

    def completar(self, messages, tools, *, concluir=False):
        if not self.api_key:
            raise BobError("MODELO_CONFIGURACAO", "Configure OPENROUTER_API_KEY no .env para usar os agentes.")
        inicio = monotonic()
        try:
            with httpx.Client(timeout=60, transport=self.transport) as client:
                resposta = client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "X-OpenRouter-Title": "Bob"},
                    json={"model": self.model, "messages": messages, "tools": tools,
                          "tool_choice": "none" if concluir else "auto",
                          "temperature": 0.3, "max_tokens": 2500,
                          "provider": {"require_parameters": True, "data_collection": "deny"}},
                )
                if resposta.status_code >= 400:
                    raise BobError("MODELO_HTTP", f"OpenRouter retornou HTTP {resposta.status_code}. Verifique configuração, saldo e disponibilidade de um provedor compatível.")
                dados = resposta.json()
                escolha = dados["choices"][0]
                if escolha.get("finish_reason") == "length":
                    raise BobError("MODELO_LIMITE", "A resposta do modelo atingiu o limite de saída. Simplifique a solicitação.")
                mensagem = escolha["message"]
                if mensagem.get("role") != "assistant" or not (mensagem.get("content") or mensagem.get("tool_calls")):
                    raise ValueError("Resposta sem mensagem utilizável.")
                self.uso.append({"duracao_ms": round((monotonic() - inicio) * 1000), "tokens_entrada": dados.get("usage", {}).get("prompt_tokens", 0), "tokens_saida": dados.get("usage", {}).get("completion_tokens", 0)})
                # Não persiste nem exibe reasoning interno retornado pelo provedor.
                return {k: mensagem[k] for k in ("role", "content", "tool_calls") if k in mensagem}
        except httpx.TimeoutException:
            raise BobError("MODELO_TIMEOUT", "O modelo não respondeu no prazo. A chamada não foi repetida automaticamente.") from None
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            raise BobError("MODELO_RESPOSTA", "Não foi possível obter uma resposta válida do OpenRouter.") from None
