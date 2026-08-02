# 8. Checklist pós-clone

Use esta lista antes de considerar a instalação concluída.

## Repositório

- [ ] `git status --short` está vazio antes das configurações locais.
- [ ] `.env`, bancos, sessões, mídias e logs não estão rastreados.
- [ ] `python tools/security_check.py` termina com sucesso.
- [ ] O clone não contém domínios, IPs, IDs ou credenciais de outra empresa.

## Dependências

- [ ] Python 3.12 está ativo no `.venv`.
- [ ] `python -m pip install -r backend/requirements.txt` terminou sem erro.
- [ ] Node atende `20.19+` ou `22.12+`.
- [ ] `npm --prefix frontend ci` terminou sem alterar o lockfile.
- [ ] `node tools/check-frontend-audit.mjs` passou sem aviso novo alto/crítico.
- [ ] `npm --prefix frontend run typecheck` passa.

## Configuração

- [ ] `backend/.env` veio do exemplo e contém segredos novos.
- [ ] `frontend/.env.local` contém somente valores públicos.
- [ ] Nenhum placeholder obrigatório ficou vazio.
- [ ] `ALLOWED_HOSTS`, origens públicas, cookies e proxy combinam com o ambiente.
- [ ] `PUBLIC_APP_URL` aponta para o frontend correto.
- [ ] Se e-mail estiver habilitado, `SMTP_HOST` e `SMTP_FROM_EMAIL` estão preenchidos; usuário e senha foram configurados juntos quando necessários.
- [ ] Os diretórios de runtime existem e pertencem ao usuário do serviço.

## Banco

- [ ] O banco PostgreSQL começou vazio e tem proprietário próprio.
- [ ] `alembic heads` mostra exatamente um head.
- [ ] `alembic upgrade head` conclui e pode ser repetido sem mudança.
- [ ] `alembic current` coincide com o head.
- [ ] `alembic check` não encontra drift.
- [ ] O bootstrap criou uma conta com senha própria e sem senha padrão.
- [ ] Não há rota ou link de autocadastro público.

## Runtime

- [ ] PostgreSQL e Redis estão ativos.
- [ ] Se `compose.dependencies.yml` foi usado, os dois containers estão `healthy` e os volumes são persistentes.
- [ ] O backend responde ao health de banco.
- [ ] O frontend acessa a API pelo mesmo domínio/proxy.
- [ ] Login, logout e renovação de sessão funcionam.
- [ ] Worker consome as filas usadas pela instalação.
- [ ] Existe no máximo um Celery Beat por ambiente.
- [ ] Logs não contêm segredos ou payloads pessoais.

## Marca

- [ ] `VITE_APP_NAME` e descrição foram alterados.
- [ ] Nome e e-mail de suporte foram alterados.
- [ ] Os quatro SVGs em `frontend/public/branding/` foram substituídos.
- [ ] Não aparece nome, logo, domínio ou suporte de outra empresa.
- [ ] A personalização `name_company`/`logo_url` continua funcionando por workspace.

## Produção

- [ ] O backend escuta somente em interface privada/local.
- [ ] PostgreSQL, Redis e WAHA não estão públicos.
- [ ] Nginx passa WebSocket e todas as rotas da API.
- [ ] HTTPS está ativo e `AUTH_COOKIE_SECURE=true`.
- [ ] Arquivo de ambiente tem permissões restritas.
- [ ] Backup e restauração foram testados fora de produção.
- [ ] Monitoramento usa token e não registra seu valor.
- [ ] WAHA só foi habilitado depois de uma sessão própria e teste controlado.

## Smoke test funcional

- [ ] Entrar com o primeiro administrador.
- [ ] Criar ou editar um workspace de teste.
- [ ] Criar um contato de teste e removê-lo ao final.
- [ ] Navegar por CRM, planos, contratos, faturas e pagamento manual.
- [ ] Confirmar estados vazio, carregando e erro no desktop e celular.
- [ ] Se habilitado, testar uma mensagem WAHA com número de teste.
- [ ] Se habilitado, testar recuperação de senha e acesso inicial de workspace pelo SMTP em homologação.
- [ ] Com SMTP indisponível em homologação, confirmar que o link temporário de definição de senha aparece somente ao administrador e pode ser copiado.
- [ ] Se habilitado, testar calendário e provedor de IA em homologação.

Guarde data, commit e resultados do checklist no seu registro de deploy, sem copiar segredos ou dados pessoais.
