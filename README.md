# Bob Space

O Bob consulta o banco do desafio a partir de perguntas em português. Ele responde no chat e mostra tabelas e gráficos quando faz sentido ou quando o usuário pede.

Usei Python, SQLite, Streamlit e OpenRouter, com dois agentes: um para analisar os dados e outro para montar as visualizações.

## Como rodar

Você precisa de Python 3.11 ou superior e uma chave do OpenRouter.

No PowerShell, dentro da pasta do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Coloque sua chave em `OPENROUTER_API_KEY`, no arquivo `.env`. Depois rode:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Abra `http://localhost:8501`. O banco já está em `data/anexo_desafio_1.db`. O modelo padrão é `qwen/qwen3.6-plus`; para trocar, altere `OPENROUTER_MODEL` no `.env`.

No Linux ou macOS, use `python3 -m venv .venv`, `.venv/bin/python` nos comandos e `cp .env.example .env` para copiar o arquivo.

Para testar o backend sem chave e sem usar a IA:

```powershell
.\.venv\Scripts\python.exe -m bob --demo --usuario diretoria
```

## Como usar

Escreva uma pergunta no chat. Os resultados aparecem no workspace, onde você pode mover os cartões ou pedir alterações ao Bob.

Em **Ver passos do Bob**, dá para conferir as consultas, os erros e as etapas usadas para chegar à resposta. O botão de atualizar de cada cartão consulta os dados novamente, sem chamar a IA.

A conversa e os cartões ficam salvos localmente. **Nova sessão** limpa a sessão atual. A engrenagem permite simular perfis e estados permitidos.

## Como funciona

Separei o trabalho em dois agentes:

1. O agente principal recebe a pergunta e a estrutura do banco, gera o SQL e consulta os dados. Pode fazer várias consultas e corrigir erros de SQL, com um limite de três falhas por turno.
2. O agente visual recebe os resultados e escolhe como mostrá-los: indicador, tabela, gráfico ou mapa. A interface monta a visualização a partir dessa configuração.

Separei análise e visualização para cada agente ter uma tarefa clara. O fluxo usa funções Python e chamadas HTTP.

O backend lê a estrutura das tabelas permitidas e valida o SQL antes de executar. As consultas do chat são geradas pelo agente; apenas a demonstração sem IA e os testes usam consultas prontas.

O banco original é aberto somente para leitura. As consultas rodam em uma cópia em memória, com os estados e as colunas autorizados. Nomes e e-mails ficam de fora. Não existe quantidade mínima de clientes para mostrar um grupo.

Os arquivos principais são `app.py` (interface), `bob/agents.py` (agentes), `bob/database.py` (banco e validação) e `bob/tools.py` (consultas e painéis).

## Exemplos testados

- Liste os 5 estados com mais clientes que compraram via App em maio de 2025.
- Quantos clientes interagiram com campanhas de WhatsApp em 2024?
- Quais categorias tiveram mais compras em média por cliente comprador?
- Mostre as reclamações não resolvidas por canal em um gráfico de barras.
- Mostre a tendência mensal de reclamações por canal entre julho de 2024 e julho de 2025.

As consultas desses exemplos são comparadas com o banco fornecido nos testes. A média considera os compradores de cada categoria. Usei datas explícitas porque a base vai de julho de 2024 a julho de 2025; períodos mais recentes podem retornar zero.

Para rodar os testes:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Os testes cobrem consultas, acesso por estado, correção de SQL, visualizações e sessões. As respostas da IA são simuladas, sem custo de API; a qualidade do modelo real precisa de uma avaliação separada.

Os testes opcionais de navegador usam Chrome no Windows. Para ativá-los, instale `requirements-dev.txt` e defina `BOB_TEST_BROWSER=1`.

## Limitações e próximos passos

- Adicionar login antes de disponibilizar o sistema para outros usuários. Hoje ele roda apenas localmente.
- Ampliar os tipos de consulta aceitos. Por enquanto, o SQL permite agregações sobre uma tabela ou um JOIN entre clientes e uma tabela de eventos.
- Reforçar a validação de filtros de datas, incluindo expressões negadas.
- Calcular percentuais e outras métricas no backend para reduzir erros nos números apresentados no texto.
- Avaliar as respostas do modelo real com mais perguntas e combinações de filtros.

As sugestões de relacionamento precisam de revisão. Não há envio de mensagens pelo Bob.
