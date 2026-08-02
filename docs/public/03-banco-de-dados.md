# 3. Banco de dados e primeiro administrador

## Por que PostgreSQL é obrigatório

O modelo usa tipos e operações próprios do PostgreSQL, incluindo `JSONB` e `ARRAY`. Um banco SQLite pode servir a testes unitários isolados, mas não é uma instalação compatível da plataforma.

## 1. Crie um usuário e um banco vazios

O modo interativo evita gravar a senha no histórico do shell:

```bash
sudo -u postgres createuser --pwprompt sua_plataforma_app
sudo -u postgres createdb \
  --owner=sua_plataforma_app \
  --encoding=UTF8 \
  sua_plataforma
```

Como alternativa, `compose.dependencies.yml` cria PostgreSQL e Redis com volumes persistentes. Copie o exemplo e defina `POSTGRES_PASSWORD` sem versionar a cópia:

```bash
cp .env.dependencies.example .env.dependencies
```

Edite `.env.dependencies`, preencha a senha e execute:

```bash
docker compose --env-file .env.dependencies -f compose.dependencies.yml up -d
docker compose --env-file .env.dependencies -f compose.dependencies.yml ps
```

Os valores padrão são banco e usuário `plataforma_agentes`; ajuste `DATABASE_URL` e `PGPASSWORD` para os valores que você definiu. O Compose cuida apenas das dependências, não da aplicação nem do WAHA.

Configure em `backend/.env`:

```dotenv
DATABASE_URL=postgresql+psycopg2://sua_plataforma_app@127.0.0.1:5432/sua_plataforma
PGPASSWORD=
```

Preencha `PGPASSWORD` apenas no arquivo local protegido. Em produção, prefira um gerenciador de segredos ou um arquivo de ambiente com permissão `600`.

Teste se o Alembic consegue abrir a conexão sem imprimir a senha:

```bash
cd backend
alembic current
cd ..
```

O arquivo `.env` não é um script de shell. Não use `source backend/.env`: valores válidos podem conter caracteres que o shell interpreta de outra forma.

## 2. Confirme a baseline única

Na edição pública, o histórico começa em:

```text
backend/alembic/versions/0001_initial_public_schema.py
```

Essa baseline foi consolidada antes da primeira distribuição estável aos alunos. Se você chegou a criar um banco a partir de uma cópia preliminar anterior, não reutilize esse banco: crie um banco vazio e aplique a `0001` atual. Depois da primeira instalação estável, preserve os dados, faça backup e use somente migrations incrementais.

Liste os heads:

```bash
cd backend
alembic heads
```

O resultado deve conter exatamente um head. Se houver mais de um, pare: você está usando um clone incorreto, uma branch incompleta ou adicionou migrations conflitantes.

## 3. Aplique o schema

Ainda dentro de `backend/` e com o ambiente virtual ativo:

```bash
alembic upgrade head
alembic current
```

`alembic current` deve indicar a mesma revisão marcada como `head`. Executar novamente deve ser seguro e não criar estruturas duplicadas:

```bash
alembic upgrade head
```

Não execute `Base.metadata.create_all()` e não importe dumps de outra instalação. A migration é o contrato reproduzível do banco público.

## 4. Verifique drift do schema

```bash
alembic check
```

O resultado esperado é a ausência de novas operações de upgrade. Se o comando sugerir alterações logo após o clone, não gere outra migration automaticamente; confira sua branch e reporte a divergência.

## 5. Crie o primeiro administrador

Volte à raiz do repositório:

```bash
cd ..
python -m backend.scripts.bootstrap_admin \
  --email admin@exemplo.com \
  --company-name "Sua Empresa" \
  --document 00000000000000
```

Troque `00000000000000` pelo CPF ou CNPJ da empresa, usando somente dígitos. O comando solicita a senha via `getpass`, sem exibi-la no terminal. Não existe senha padrão. Use o mesmo e-mail configurado em `ADMIN_EMAILS` se essa conta precisar das funções administrativas internas.

Para automação, injete a senha por uma variável temporária, nunca por argumento de linha de comando:

```bash
read -r -s BOOTSTRAP_ADMIN_PASSWORD
export BOOTSTRAP_ADMIN_PASSWORD
python -m backend.scripts.bootstrap_admin \
  --email admin@exemplo.com \
  --company-name "Sua Empresa" \
  --document 00000000000000 \
  --password-env BOOTSTRAP_ADMIN_PASSWORD
unset BOOTSTRAP_ADMIN_PASSWORD
```

Execute o bootstrap somente para a primeira conta. Se o e-mail ou a empresa já existirem, investigue o estado em vez de apagar tabelas ou rodar o comando repetidamente.

## 6. Backup antes de atualizações futuras

Uma rotina mínima antes de migrations posteriores é:

```bash
pg_dump \
  --host=127.0.0.1 \
  --port=5432 \
  --username=sua_plataforma_app \
  --dbname=sua_plataforma \
  --format=custom \
  --file=/caminho/seguro/sua_plataforma.dump
cd backend
alembic upgrade head
```

O `pg_dump` solicitará a senha se ela não estiver disponível por `PGPASSWORD`, `.pgpass` ou um gerenciador de segredos. Guarde o dump fora do diretório publicado e teste periodicamente a restauração em outro banco. Nunca valide um backup apagando o banco em uso.
