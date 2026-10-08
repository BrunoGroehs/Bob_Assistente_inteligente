"""Restauração sem IA, isolamento e revalidação do recorte salvo."""

import secrets
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from bob.persistence import salvar, restaurar
from bob.schemas import Usuario
from bob.session import SessaoLocal
from test_backend import criar_banco


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.banco = Path(temp.name) / 'dados.db'
        self.arquivo = Path(temp.name) / 'snapshots.db'
        criar_banco(self.banco)
        self.perfil = Usuario(id='teste', papel='analista', ufs=('SP',))
        self.sessao = SessaoLocal(self.banco, self.perfil)
        r = self.sessao.backend.consultar_dados('SELECT estado, COUNT(*) AS clientes FROM clientes GROUP BY estado', {'descricao':'Clientes por estado'})
        self.sessao.backend.publicar_painel({'componentes':[{'id':'mapa','tipo':'mapa','dataset_id':r['dataset_id'],'titulo':'Clientes','x':'estado','y':'clientes'}]})
        self.sessao.posicionar({'mapa':{'x':24,'y':48}})
        self.sessao.mensagens = [{'role':'user','content':'Me mostre um mapa'}]
        self.sessao.mapas = {'mapa':'SP'}
        self.token = secrets.token_hex(32)

    def test_restaura_layout_historico_e_dados_sem_modelo(self):
        salvar(self.sessao, self.token, self.arquivo)
        novo = restaurar(self.banco, self.token, self.perfil, self.arquivo)
        self.assertEqual(novo.posicoes, self.sessao.posicoes)
        self.assertEqual(novo.posicoes_manuais, {'mapa'})
        self.assertEqual(novo.mensagens, self.sessao.mensagens)
        self.assertEqual(novo.mapas, {'mapa':'SP'})
        self.assertEqual(novo.componentes()[0]['resultado']['dados'], [{'estado':'SP','clientes':12}])
        self.assertEqual(novo.client.uso, [])
        self.assertIsNone(restaurar(self.banco,secrets.token_hex(32),arquivo=self.arquivo))

    def test_perfil_revogado_nao_restaura_dados_ou_historico(self):
        salvar(self.sessao,self.token,self.arquivo)
        novo = restaurar(self.banco,self.token,Usuario(id='teste',papel='analista',ufs=('RJ',)),self.arquivo)
        self.assertEqual(novo.componentes(),[])
        self.assertEqual(novo.mensagens,[])

    def test_workspace_antigo_restaura_apos_organizacao_do_banco(self):
        salvar(self.sessao, self.token, self.arquivo)
        banco = self.banco.parent / 'data' / self.banco.name
        banco.parent.mkdir()
        self.banco.replace(banco)
        with closing(sqlite3.connect(self.arquivo)) as db, db:
            estado = json.loads(db.execute('SELECT estado FROM workspaces').fetchone()[0])
            estado['banco'] = str(banco.parent.parent / 'Instruções' / banco.name)
            estado.pop('posicoes_manuais')
            db.execute('UPDATE workspaces SET estado=?', (json.dumps(estado),))
        novo = restaurar(banco, self.token, self.perfil, self.arquivo)
        self.assertEqual(novo.mensagens, self.sessao.mensagens)
        self.assertEqual(novo.posicoes_manuais, set())
        self.assertEqual(novo.componentes()[0]['resultado']['dados'], [{'estado':'SP','clientes':12}])

    def test_reconsulta_aplica_privacidade_atual_e_nova_sessao_esvazia_snapshot(self):
        salvar(self.sessao,self.token,self.arquivo)
        with closing(sqlite3.connect(self.banco)) as db, db:
            db.execute("DELETE FROM clientes WHERE estado='São Paulo' AND id>3")
        novo = restaurar(self.banco,self.token,self.perfil,self.arquivo)
        self.assertEqual(novo.componentes()[0]['resultado']['dados'],[])
        salvar(novo.reiniciar(),self.token,self.arquivo)
        self.assertEqual(restaurar(self.banco,self.token,self.perfil,self.arquivo).componentes(),[])

    def test_segredos_nao_sao_persistidos_e_identificador_e_validado(self):
        self.sessao.client.api_key = 'CHAVE_DE_TESTE'
        self.sessao.mensagens[0]['content'] = 'CHAVE_DE_TESTE'
        salvar(self.sessao,self.token,self.arquivo)
        with closing(sqlite3.connect(self.arquivo)) as db:
            texto = db.execute('SELECT estado FROM workspaces').fetchone()[0]
        self.assertNotIn('CHAVE_DE_TESTE',texto)
        with self.assertRaises(ValueError):
            restaurar(self.banco,'../workspace',arquivo=self.arquivo)
