# 🧳 Divisão de Despesas da Viagem

Aplicação em Streamlit para gerenciar despesas compartilhadas de viagem entre
4 participantes (expansível), com cálculo automático de saldos e um
algoritmo de simplificação de dívidas (Minimum Cash Flow) que gera o menor
número possível de transferências para fechar as contas.

## Estrutura do projeto

```
viagem-app/
├── app.py              # Interface Streamlit (5 abas)
├── database.py         # Camada de persistência (SQLAlchemy: SQLite/Postgres)
├── settlement.py       # Cálculo de balanços e algoritmo de acerto de contas
├── requirements.txt    # Dependências
├── .env.example        # Exemplo de configuração de banco de dados
└── README.md
```

## Funcionalidades

- Cadastro/renomeação dos participantes (padrão 4, mas dá para adicionar mais).
- Lançamento de despesas com data, categoria, valor, pagador e divisão
  **igualitária** ou **customizada** (por peso, apenas entre quem participou).
- Painel com Total Pago, Cota-parte Consumida e Saldo Líquido de cada pessoa.
- Algoritmo guloso de dois ponteiros que gera as transações mínimas
  ("Fulano deve pagar R$ X para Ciclano via Pix").
- Registro de liquidações (pagamentos já feitos), com recálculo automático
  do saldo restante.
- Exportação do extrato em CSV e de um relatório completo (extrato + balanço
  + acerto de contas) em Excel.

---

## 1. Rodando localmente

### Pré-requisitos
- Python 3.9 ou superior instalado.

### Passo a passo

```bash
# 1. Entre na pasta do projeto
cd viagem-app

# 2. (Recomendado) crie um ambiente virtual
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Rode a aplicação
streamlit run app.py
```

O Streamlit abrirá automaticamente no navegador, normalmente em
`http://localhost:8501`. Por padrão os dados ficam salvos em um arquivo
local `viagem.db` (SQLite) na mesma pasta — não é necessário instalar
nenhum banco de dados separado para uso local.

### Trocando para PostgreSQL / Supabase (opcional)

A aplicação já está pronta para produção com Postgres, bastando apontar a
variável de ambiente `DATABASE_URL`:

1. Copie `.env.example` para `.env`.
2. No Supabase, vá em **Project Settings → Database → Connection string**
   (modo *Session*) e copie a string de conexão.
3. Edite o `.env`:
   ```
   DATABASE_URL=postgresql+psycopg2://usuario:senha@host:5432/nomedobanco
   ```
4. Instale o driver do Postgres (já incluso no `requirements.txt`):
   ```
   pip install psycopg2-binary
   ```
5. Rode normalmente com `streamlit run app.py` — as tabelas são criadas
   automaticamente na primeira execução.

> **Integração com Google Sheets:** para usar uma planilha do Google como
> fonte de dados em vez de um banco relacional, o Streamlit oferece
> `st.connection("gsheets", type=GSheetsConnection)` (pacote
> `st-gsheets-connection`). Isso exigiria adaptar as funções de
> `database.py` para ler/escrever DataFrames na planilha em vez de usar o
> SQLAlchemy — uma opção viável caso prefira não manter nenhum banco de
> dados, mas com menos garantias de integridade transacional que o SQL.

---

## 2. Deploy gratuito no Streamlit Community Cloud

1. **Suba o projeto para o GitHub**
   - Crie um repositório (pode ser privado) e envie todos os arquivos
     (`app.py`, `database.py`, `settlement.py`, `requirements.txt`).
   - **Não** suba o arquivo `viagem.db` nem o `.env` com senhas reais.

2. **Crie a conta / acesse o Streamlit Community Cloud**
   - Acesse [share.streamlit.io](https://share.streamlit.io) e faça login
     com sua conta do GitHub.

3. **Crie um novo app**
   - Clique em **"New app"**.
   - Selecione o repositório, a branch (geralmente `main`) e o arquivo
     principal: `app.py`.

4. **Configure o banco de dados**
   - **Opção simples (SQLite):** não precisa configurar nada — porém
     lembre-se que o Streamlit Community Cloud reinicia o container
     periodicamente, então o `viagem.db` **pode ser perdido** entre
     deploys/reinícios. Ideal apenas para testes rápidos.
   - **Opção recomendada para uso real (Postgres/Supabase):** no painel do
     app, vá em **"Settings" → "Secrets"** e adicione:
     ```toml
     DATABASE_URL = "postgresql+psycopg2://usuario:senha@host:5432/nomedobanco"
     ```
     Isso garante que os dados persistam de verdade, independente de
     reinícios do container.

5. **Deploy**
   - Clique em **"Deploy"**. Em alguns minutos o app estará no ar em uma
     URL do tipo `https://seu-app.streamlit.app`.
   - Compartilhe o link com os demais participantes da viagem — todos
     acessam pelo navegador, inclusive pelo celular.

6. **Atualizações**
   - Qualquer novo `git push` para a branch configurada dispara um
     redeploy automático.

---

## 3. Notas sobre o algoritmo de acerto de contas

O `settlement.py` implementa o algoritmo de **Minimum Cash Flow** via
dois ponteiros:

1. Separa participantes em credores (saldo positivo) e devedores (saldo
   negativo).
2. Ordena cada grupo do maior para o menor saldo em módulo.
3. A cada iteração, casa o maior devedor com o maior credor e transfere
   `min(dívida, crédito)`.
4. Sempre que uma das pontas zera, avança para o próximo da fila.

Isso garante o menor número de transações possível para fechar as contas
(no pior caso, N-1 transações para N participantes), em vez de cada pessoa
acertar individualmente com todas as outras.
