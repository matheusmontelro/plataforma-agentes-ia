# 4. Variáveis de ambiente e integrações

## Arquivos de referência

- `.env.development.example`: backend local.
- `.env.production.example`: backend no servidor.
- `.env.dependencies.example`: PostgreSQL e Redis do Compose opcional.
- `.env.public.example`: somente variáveis das rotas de API pública.
- `frontend/.env.development.example`: frontend/Vite local.
- `frontend/env.production.example`: frontend/Vite para o build de produção; copie para `frontend/.env.production`.

O backend lê `backend/.env` quando executado pelo fluxo local. Em produção, um `EnvironmentFile` do systemd pode injetar as mesmas variáveis sem armazená-las no repositório.

## Backend obrigatório

| Variável | Uso |
| --- | --- |
| `ENVIRONMENT` | `development` ou `production` |
| `APP_NAME` | nome da empresa usado pelo backend em identificadores públicos neutros |
| `APP_DATA_DIR` | raiz gravável para mídias, logs, memória e dados gerados em runtime |
| `DATABASE_URL` | conexão PostgreSQL |
| `PGPASSWORD` ou mecanismo equivalente | autenticação do PostgreSQL sem senha no exemplo versionado |
| `JWT_SECRET_KEY` | assinatura dos tokens de sessão |
| `PUBLIC_API_KEY` | autenticação das rotas públicas; obrigatória em produção |
| `PUBLIC_API_SECRET` | assinatura das rotas públicas; obrigatória em produção |
| `MONITORING_TOKEN` | protege health detalhado e métricas |
| `PUBLIC_BASE_URL` | origem pública usada em URLs geradas |
| `PUBLIC_APP_URL` | origem pública do frontend usada em links enviados por e-mail |
| `REDIS_URL` | cache e broker padrão |
| `WEBSOCKET_REDIS_URL` | Pub/Sub de eventos em tempo real |
| `CELERY_BROKER_URL` | broker dos workers |
| `CELERY_RESULT_BACKEND` | resultados do Celery |
| `ALLOWED_HOSTS` | hosts aceitos pela API |
| `ADMIN_EMAILS` | contas autorizadas a funções administrativas internas |

Gere `JWT_SECRET_KEY`, `PUBLIC_API_KEY`, `PUBLIC_API_SECRET` e `MONITORING_TOKEN` separadamente. Não copie segredos entre desenvolvimento e produção.

`CLIENT_TOKEN` é opcional e existe apenas para rotas ou provedores legados que ainda o exigem. Deixe vazio quando esses recursos não forem usados; se precisar habilitá-lo, gere um segredo exclusivo para essa instalação.

Os caminhos específicos, como `MEDIA_BASE_PATH`, `CHAT_MEMORY_DIR` e `LOG_DIR`,
podem sobrescrever subdiretórios de `APP_DATA_DIR`. Em produção, conceda escrita ao
usuário do serviço somente nessa raiz; não use caminhos da máquina de origem.

## Cookies e proxy

Desenvolvimento HTTP:

```dotenv
AUTH_COOKIE_SECURE=false
AUTH_COOKIE_SAMESITE=lax
TRUST_PROXY_HEADERS=false
```

Produção HTTPS atrás de proxy confiável:

```dotenv
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=lax
TRUST_PROXY_HEADERS=true
```

Não habilite `TRUST_PROXY_HEADERS` quando o backend puder ser acessado diretamente por clientes externos.

## Frontend

Somente valores públicos podem usar o prefixo `VITE_`; o Vite incorpora essas variáveis no JavaScript entregue ao navegador. Nunca coloque tokens, senhas ou chaves privadas no frontend.

O frontend deve usar API no mesmo domínio. Em desenvolvimento, configure:

```dotenv
VITE_DEV_HOST=127.0.0.1
VITE_DEV_PORT=3004
VITE_DEV_PROXY_TARGET=http://127.0.0.1:8002
VITE_PUBLIC_APP_ORIGIN=http://localhost:3004
VITE_FORCE_ABSOLUTE_API=false
```

Em produção, o Nginx deve encaminhar as rotas de backend. Não aponte o navegador para `127.0.0.1` nem exponha a porta 8002.

## Redis e Celery

Redis é requisito de inicialização: o gerenciador WebSocket testa a conexão durante o startup. Celery pode ficar desligado apenas durante uma inspeção limitada do painel; follow-ups, campanhas, mensagens agendadas e fluxos assíncronos não serão processados.

Use namespaces diferentes quando mais de um ambiente compartilhar o Redis:

```dotenv
WEBSOCKET_CHANNEL_NAMESPACE=sua-plataforma:development
```

Em produção use outro sufixo, por exemplo `sua-plataforma:production`.

## WAHA/WhatsApp

WAHA é necessário apenas para conectar e operar WhatsApp. Enquanto a integração não estiver pronta:

```dotenv
WAHA_ENABLED=false
WAHA_BASE_URL=http://127.0.0.1:3000
WAHA_API_KEY=
```

`WAHA_API_KEY` é obrigatória somente quando `WAHA_ENABLED=true`. Ao habilitar, use a mesma chave configurada no serviço e mantenha sua porta restrita à rede privada.

Uma sessão do WhatsApp é dado operacional. Nunca copie a pasta de sessão de outra empresa nem a envie ao Git.

## IA e BYOK

`AI_PROVIDER_TOKEN_ENCRYPTION_KEY` protege credenciais cadastradas por empresa. Gere uma chave Fernet exclusiva e mantenha backup seguro; trocar ou perder essa chave torna os tokens já armazenados inutilizáveis.

`OPENAI_API_KEY` aparece apenas por compatibilidade com módulos legados. Deixe vazia se sua instalação usa somente credenciais BYOK configuradas pela interface.

A instalação padrão não inclui CUDA, Torch nem Whisper local. A transcrição de
áudio existente usa a API do provedor configurado e, portanto, não exige GPU no
servidor. Adicione uma pilha local de ML somente se também implementar e validar
esse modo de execução para o hardware dos alunos.

## E-mail transacional por SMTP

O backend usa SMTP genérico para recuperação de senha e, quando aplicável, envio do acesso inicial de um novo workspace. Nenhum provedor comercial específico é necessário.

```dotenv
PUBLIC_APP_URL=http://localhost:3004
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=
SMTP_FROM_NAME=SUA_EMPRESA
SMTP_STARTTLS=true
```

O envio é habilitado somente quando `SMTP_HOST` e `SMTP_FROM_EMAIL` estão preenchidos. `SMTP_USERNAME` e `SMTP_PASSWORD` são opcionais, mas devem ser configurados juntos quando o servidor exigir autenticação. Use `SMTP_STARTTLS=true` com a porta STARTTLS indicada pelo servidor, normalmente 587. Valores inválidos mantêm TLS ligado; autenticação é recusada quando TLS está desligado. Defina `SMTP_STARTTLS=false` somente para SMTP sem autenticação em uma rede interna confiável; a implementação não suporta SMTPS/SSL implícito.

`PUBLIC_APP_URL` deve apontar para a origem do frontend, sem caminho adicional, para que os links de recuperação de senha abram a instalação correta. Nunca coloque a senha SMTP em variáveis `VITE_*`.

Quando um novo workspace exigir definição de senha e o SMTP não entregar a mensagem, a interface mostra ao administrador autorizado um link temporário somente na confirmação atual. Copie-o e envie por um canal seguro; não registre esse link em logs, tickets ou documentação.

## Integrações opcionais

Configure apenas as integrações que usar:

- Google OAuth/Calendar: conexão de calendários.
- Serviços de voz: chaves e vozes do provedor escolhido.

Uma integração desabilitada não deve receber valores fictícios parecidos com credenciais reais. Prefira campo vazio e valide no ambiente de homologação antes de produção.

A edição pública não contém checkout externo nem autocadastro. Crie o primeiro administrador com `backend.scripts.bootstrap_admin`; depois, use uma conta autorizada para administrar outras contas e workspaces.

## Permissões de arquivos

Em servidor Linux:

```bash
sudo chown root:sua-plataforma /etc/sua-plataforma/backend.env
sudo chmod 640 /etc/sua-plataforma/backend.env
```

O usuário do serviço pode ler o grupo; usuários comuns não podem ler o arquivo.
