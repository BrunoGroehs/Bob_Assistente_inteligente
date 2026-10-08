"""Compara as cinco análises com referências independentes no banco fornecido."""

import hashlib
import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path

from bob.access import uf_do_estado
from bob.schemas import UFS, Usuario
from bob.tools import Backend

BANCO = Path(__file__).resolve().parents[1] / "data" / "anexo_desafio_1.db"


@unittest.skipUnless(BANCO.exists(), "Banco do desafio não encontrado.")
class BancoFornecidoTests(unittest.TestCase):
    def comparar(self, sql, referencia_cliente="cliente_id"):
        assinatura = hashlib.sha256(BANCO.read_bytes()).digest()
        usuario = Usuario(id="avaliacao", papel="analista", ufs=tuple(UFS))
        backend = Backend(BANCO, lambda: usuario)
        resultado = backend.consultar_dados(sql, {"descricao": "Avaliação de análise agregada."})
        self.assertEqual(resultado["status"], "ok", resultado)
        # SQL de referência pertence só à avaliação, não ao agente em execução.
        referencia = sql.replace(" FROM ", f", COUNT(DISTINCT {referencia_cliente}) AS _participantes FROM ", 1)
        with closing(sqlite3.connect(BANCO.resolve().as_uri() + "?mode=ro", uri=True)) as fonte:
            fonte.row_factory = sqlite3.Row
            esperado = []
            for linha in fonte.execute(referencia):
                if 0 < linha["_participantes"] < 5:
                    continue
                dados = {k: linha[k] for k in linha.keys() if k != "_participantes"}
                if "estado" in dados:
                    dados["estado"] = uf_do_estado(dados["estado"])
                esperado.append(dados)
        self.assertEqual(sorted(json.dumps(r, sort_keys=True) for r in resultado["dados"]), sorted(json.dumps(r, sort_keys=True) for r in esperado))
        self.assertEqual(hashlib.sha256(BANCO.read_bytes()).digest(), assinatura)

    def test_clientes_app_maio_2025_por_estado(self):
        self.comparar("SELECT c.estado, COUNT(DISTINCT c.id) AS clientes FROM clientes c JOIN compras p ON p.cliente_id=c.id WHERE p.canal='App' AND p.data_compra >= '2025-05-01' AND p.data_compra < '2025-06-01' GROUP BY c.estado ORDER BY clientes DESC LIMIT 5", "c.id")

    def test_clientes_whatsapp_2024(self):
        self.comparar("SELECT COUNT(DISTINCT cliente_id) AS clientes FROM campanhas_marketing WHERE canal='WhatsApp' AND interagiu=1 AND data_envio >= '2024-01-01' AND data_envio < '2025-01-01'")

    def test_media_compras_por_comprador_e_categoria(self):
        self.comparar("SELECT categoria, COUNT(*) * 1.0 / COUNT(DISTINCT cliente_id) AS media FROM compras GROUP BY categoria ORDER BY media DESC")

    def test_reclamacoes_nao_resolvidas_por_canal(self):
        self.comparar("SELECT canal, COUNT(*) AS reclamacoes FROM suporte WHERE tipo_contato='Reclamação' AND resolvido=0 GROUP BY canal ORDER BY reclamacoes DESC")

    def test_tendencia_reclamacoes_com_periodo_explicito(self):
        self.comparar("SELECT STRFTIME('%Y-%m', data_contato) AS mes, canal, COUNT(*) AS reclamacoes FROM suporte WHERE tipo_contato='Reclamação' AND data_contato >= '2024-07-01' AND data_contato < '2025-08-01' GROUP BY STRFTIME('%Y-%m', data_contato), canal ORDER BY mes, canal")
