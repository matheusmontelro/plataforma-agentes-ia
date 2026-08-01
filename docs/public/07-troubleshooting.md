# 7. Solução de problemas

## `DATABASE_URL environment variable is required`

- Confirme que `backend/.env` existe.
- Execute o backend pela raiz com `python -m uvicorn backend.main:app --env-file backend/.env ...` para carregar as variáveis antes do import da aplicação.
- Se usar outro nome, defina `ENV_FILE` com o nome relativo a `backend/`.
- Em systemd, confira `EnvironmentFile` e as permissões do arquivo.

Não corrija colocando credenciais no código.

## Falha de autenticação do PostgreSQL

Teste pelo carregamento nativo da aplicação:

```bash
cd backend
alembic current
```

Revise usuário, banco, `pg_hba.conf` e a variável `PGPASSWORD`. Não use `source backend/.env` e não publique a saída de variáveis de ambiente.

## `alembic upgrade head` informa múltiplos heads

A edição pública deve ter apenas `0001_initial_public_schema.py` como baseline. Confira:

```bash
cd backend
alembic heads
git status --short
```

Não escolha um head arbitrário e não crie merge migration. Volte para uma branch íntegra ou reporte o problema com a lista de nomes das migrations, sem credenciais.

## `alembic check` encontra alterações após a migration

Confirme que:

- a migration terminou sem erro;
- todos os modelos públicos estão registrados no metadata do Alembic;
- você está no commit correto;
- não reutilizou um banco antigo.

Reproduza em outro banco vazio antes de alterar a baseline.

## Backend encerra ao iniciar e o log cita Redis

O manager WebSocket exige Redis no startup:

```bash
redis-cli -u redis://127.0.0.1:6379/0 ping
```

O resultado esperado é `PONG`. Confirme também `REDIS_URL` e `WEBSOCKET_REDIS_URL`.

## Backend exige `WAHA_API_KEY`

Confirme `WAHA_ENABLED`. A chave é obrigatória quando a integração está `true`; com WAHA desabilitado, deixe-a vazia. Ao habilitar, configure no backend a mesma chave do serviço, sem imprimi-la em logs ou comandos compartilhados.

## O frontend abre, mas API retorna 404 ou erro de rede

Em desenvolvimento:

- confira `VITE_DEV_PROXY_TARGET=http://127.0.0.1:8002`;
- reinicie o Vite depois de editar `.env.local`;
- teste o backend diretamente pelo health local.

Em produção:

- mantenha `VITE_FORCE_ABSOLUTE_API=false`;
- confirme os blocos de proxy do Nginx;
- teste uma rota sob o domínio público, não a porta 8002 no navegador;
- valide os headers de upgrade em `/ws`.

## Login funciona em HTTP local, mas não em produção

- Produção deve usar HTTPS com `AUTH_COOKIE_SECURE=true`.
- Confira se o proxy envia `X-Forwarded-Proto` e se `TRUST_PROXY_HEADERS=true` está restrito ao proxy.
- Confirme `ALLOWED_HOSTS` e o domínio exato.
- Não use uma mistura de IP, HTTP e domínio HTTPS para a mesma sessão.

## O logo ou o nome antigo continua aparecendo

1. confira `frontend/.env.local` ou `frontend/.env.production`;
2. confirme os quatro SVGs em `frontend/public/branding/`;
3. reinicie o Vite, ou refaça o build de produção;
4. publique todo o novo diretório `frontend/build`;
5. limpe cache do navegador, proxy ou CDN;
6. diferencie a marca global do `name_company`/`logo_url` do workspace.

## `npm ci` informa versão de Node incompatível

Use Node `20.19+` ou `22.12+`. Não altere o lockfile nem faça downgrade de Vite apenas para contornar o requisito.

## Tarefas ficam pendentes

- confirme que Redis responde;
- confira o status do worker;
- valide se ele consome a fila roteada para a tarefa;
- veja os logs sem imprimir payloads sensíveis;
- confirme que existe somente um Beat por ambiente.

## WhatsApp não conecta

- confirme `WAHA_ENABLED=true` somente depois de instalar o WAHA;
- valide `WAHA_BASE_URL` pela rede interna do backend;
- confirme que as chaves coincidem sem exibi-las;
- não reutilize sessões de outra instalação;
- preserve o volume da sessão em reinícios do container/serviço.

## Onde coletar evidências

```bash
git rev-parse --short HEAD
git status --short
cd backend && alembic current && alembic heads
sudo systemctl status sua-plataforma-api sua-plataforma-worker --no-pager
sudo journalctl -u sua-plataforma-api -n 100 --no-pager
```

Antes de compartilhar a saída, remova e-mails, telefones, tokens, URLs assinadas, payloads de webhook e dados de clientes.
