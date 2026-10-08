# Bob Space

Assistente de análise de dados com conversa em linguagem natural e um workspace para indicadores, tabelas, gráficos e mapas. Usa Python, Streamlit, SQLite e dois agentes pelo OpenRouter.

## Executar

Requisitos: Python 3.11 ou superior e uma chave do OpenRouter para conversar com os agentes.

No PowerShell, dentro da pasta do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Preencha `OPENROUTER_API_KEY` no `.env` e inicie a interface:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Abra `http://localhost:8501`. O modelo padrão é `qwen/qwen3.6-plus` e pode ser alterado por `OPENROUTER_MODEL`.

No Linux/macOS, use `python3 -m venv .venv`, `.venv/bin/python` no lugar de `.\.venv\Scripts\python.exe` e `cp .env.example .env` para copiar a configuração.

Para experimentar o backend sem chave e sem chamadas ao modelo:

```powershell
.\.venv\Scripts\python.exe -m bob --demo --usuario diretoria
```

Também é possível usar a conversa pela CLI:

```powershell
.\.venv\Scripts\python.exe -m bob --usuario diretoria --pergunta "Quantos clientes interagiram com campanhas de WhatsApp em 2024?"
```

## Uso

Faça uma pergunta no chat e peça uma visualização quando necessário. O workspace recebe os componentes criados durante a conversa; cartões podem ser movidos, atualizados e editados por novos pedidos ao Bob.

O encaixe automático acompanha a largura disponível. Cartões arrastados mantêm suas posições; **Encaixar cartões** reorganiza todos em colunas.

Em **Ver passos do Bob**, cada resposta mostra as consultas, chamadas de ferramentas, erros e publicações daquele turno. O botão de atualização reexecuta a consulta do componente sem chamar os agentes.

A engrenagem permite simular papéis e UFs. O perfil inicial é analista com acesso às 27 UFs. Conversa e workspace são salvos localmente por até 30 dias sem uso, em `.bob/workspaces.sqlite3`. **Nova sessão** limpa o estado atual.

Exemplos:

- Liste os 5 estados com mais clientes que compraram via App em maio de 2025.
- Quantos clientes interagiram com campanhas de WhatsApp em 2024?
- Quais categorias tiveram mais compras em média por cliente comprador?
- Mostre as reclamações não resolvidas por canal em um gráfico de barras.
- Mostre a participação do valor de vendas por canal em um gráfico de pizza.
- Mostre a tendência mensal de reclamações por canal entre julho de 2024 e julho de 2025.

## Arquitetura

O fluxo dos agentes usa funções Python e HTTP direto, sem um framework de orquestração:

1. O agente principal recebe o schema autorizado, interpreta a pergunta e propõe uma consulta SQL.
2. O backend valida acesso e SQL, executa a consulta em um recorte SQLite em memória e guarda o resultado com um `dataset_id`. Erros de consulta retornam ao agente para correção.
3. Quando há um pedido visual, o agente principal encaminha os resultados ao agente visual.
4. O agente visual propõe uma configuração declarativa. O backend valida os campos e a interface renderiza o componente com código fixo da aplicação.

Os agentes não executam HTML, JavaScript ou Python gerados. O arquivo original é aberto somente para leitura; as consultas do modelo usam apenas tabelas e colunas aprovadas do recorte.

```text
app.py                  Interface Streamlit
bob/                    Agentes, ferramentas, acesso, SQL e visualizações
assets/                 Estilos, scripts da interface e malhas do Brasil
data/anexo_desafio_1.db  Banco fornecido no desafio
tests/                  Testes do backend, interface e integrações
usuarios.exemplo.json   Perfis usados na demonstração pela CLI
```

Os pontos principais são `bob/agents.py` (fluxo e ferramentas dos agentes), `bob/database.py` (recorte e validação SQL), `bob/tools.py` (consultas, publicação e refresh) e `bob/schemas.py` (contratos).

O controle de acesso combina papel e UFs. Dados pessoais não entram no recorte; identificadores internos são remapeados. Consultas retornam agregações com até 200 linhas e suprimem grupos com menos de cinco clientes. Mudanças de permissões invalidam os resultados da sessão.

Gráficos usam Altair com templates fixos de barras, linhas, áreas, pizza, rosca, dispersão e mapa de calor. Mapas usam as [malhas públicas do IBGE](https://servicodados.ibge.gov.br/api/docs/malhas?versao=3), armazenadas em `assets/brasil-ufs.geojson`.

## Testes

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

A suíte cobre acesso por UF, privacidade, validação SQL, cálculos, publicação, atualização, persistência e fluxos da interface. Cinco casos comparam os resultados com o banco fornecido e conferem que o arquivo permanece intacto.

As chamadas ao modelo são simuladas nos testes automatizados, que não precisam de chave nem consomem a API. Para os testes opcionais de navegador, instale `requirements-dev.txt` e defina `BOB_TEST_BROWSER=1`; eles usam Chrome local no Windows.

## Limitações e melhorias

- A seleção de perfil é uma simulação, sem autenticação. Por isso, o servidor está configurado para acesso local. Uma implantação compartilhada precisa de autenticação e identidade fornecida pelo servidor.
- A base cobre aproximadamente julho de 2024 a julho de 2025. Consultas de períodos mais recentes podem retornar zero por falta de dados. A supressão de grupos pequenos também pode reduzir rankings ou deixar séries vazias.
- O SQL aceita agregações sobre uma tabela ou um JOIN entre clientes e uma tabela de eventos. Subconsultas, CTEs, janelas e cruzamentos entre várias tabelas de eventos ficam fora deste escopo.
- O backend garante o recorte das UFs permitidas, mas filtros mais específicos dependem do SQL gerado. A validação de períodos relativos precisa ser reforçada para expressões negadas.
- Percentuais calculados no texto podem apresentar erros do modelo. Uma melhoria é calcular essas métricas no backend e validar sua apresentação na resposta. Sugestões de relacionamento também exigem revisão e não representam efeitos comprovados ou envios realizados.
