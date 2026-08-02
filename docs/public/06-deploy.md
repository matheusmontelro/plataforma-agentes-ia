# 6. Deploy no servidor

Este é um modelo de deploy em uma única máquina Linux com PostgreSQL, Redis, systemd e Nginx. Adapte usuários e caminhos; não copie nomes de serviços ou domínios de outra instalação.

## Arquitetura mínima

```text
Internet -> HTTPS/Nginx -> frontend estático
                       -> FastAPI em 127.0.0.1:8002
FastAPI/Workers -> PostgreSQL + Redis
Workers -> WAHA, SMTP e provedores opcionais
```

## 1. Usuário e diretórios

Crie um usuário sem login interativo e diretórios próprios. Execute conforme a política do seu servidor:

```bash
sudo useradd --system --create-home --home-dir /srv/sua-plataforma sua-plataforma
sudo mkdir -p /srv/sua-plataforma/shared/{media,chatmemory,logs,logos,account-profiles}
sudo mkdir -p /etc/sua-plataforma
sudo chown -R sua-plataforma:sua-plataforma /srv/sua-plataforma
```

Clone o repositório em `/srv/sua-plataforma/app` e instale as dependências com o usuário do serviço. Não execute a aplicação como `root`.

## 2. Ambiente e banco

Use `.env.production.example` como checklist e salve o arquivo real fora do repositório:

```text
/etc/sua-plataforma/backend.env
```

Proteja-o com permissão `640` ou mais restritiva. Em seguida, aplique a migration no banco vazio e crie o primeiro administrador conforme [Banco de dados](03-banco-de-dados.md).

## 3. Frontend

Copie o template rastreável e edite somente valores públicos e de branding:

```bash
cp frontend/env.production.example frontend/.env.production
```

A API deve continuar em modo same-origin:

```dotenv
VITE_PUBLIC_APP_ORIGIN=https://app.seudominio.com.br
VITE_FORCE_ABSOLUTE_API=false
VITE_APP_NAME=SUA_EMPRESA
VITE_APP_DESCRIPTION=Plataforma de agentes de IA da sua empresa
VITE_SUPPORT_NAME=Equipe da SUA_EMPRESA
VITE_SUPPORT_EMAIL=suporte@seudominio.com.br
```

Valide e gere os arquivos estáticos:

```bash
npm --prefix frontend ci
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

O Vite grava o resultado em `frontend/build`.

## 4. Serviço do backend

Crie `/etc/systemd/system/sua-plataforma-api.service`:

```ini
[Unit]
Description=API da plataforma de agentes
After=network-online.target postgresql.service redis-server.service
Wants=network-online.target postgresql.service redis-server.service

[Service]
Type=simple
User=sua-plataforma
Group=sua-plataforma
WorkingDirectory=/srv/sua-plataforma/app
Environment=PYTHONPATH=/srv/sua-plataforma/app
EnvironmentFile=/etc/sua-plataforma/backend.env
ExecStart=/srv/sua-plataforma/app/.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8002 --workers 1
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=/srv/sua-plataforma/shared

[Install]
WantedBy=multi-user.target
```

Comece com um processo. Só aumente `--workers` depois de validar pool de banco, memória, Redis Pub/Sub e WebSockets entre processos.

## 5. Worker e agendador

Sem workers, tarefas assíncronas ficam nas filas. Crie um serviço Celery consumindo as filas declaradas pelo projeto:

```ini
[Unit]
Description=Worker da plataforma de agentes
After=network-online.target redis-server.service postgresql.service
Wants=redis-server.service postgresql.service

[Service]
Type=simple
User=sua-plataforma
Group=sua-plataforma
WorkingDirectory=/srv/sua-plataforma/app
Environment=PYTHONPATH=/srv/sua-plataforma/app
EnvironmentFile=/etc/sua-plataforma/backend.env
ExecStart=/srv/sua-plataforma/app/.venv/bin/celery -A backend.worker.celery_app:app worker --loglevel=INFO --concurrency=2 -Q messages_queue,waha_messages_queue,confirmation_queue,scheduling_queue,followup_queue,noshow_queue,pos_consulta_queue,pos_venda_queue,reminders_queue,scheduled_messages_queue,nutrition_campaign_queue,agents_sdk_queue,flow_execution_queue,whatsapp_campaign_queue
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Para rotinas periódicas, crie `/etc/systemd/system/sua-plataforma-beat.service`:

```ini
[Unit]
Description=Agendador Celery da plataforma de agentes
After=network-online.target redis-server.service postgresql.service
Wants=network-online.target redis-server.service postgresql.service

[Service]
Type=simple
User=sua-plataforma
Group=sua-plataforma
WorkingDirectory=/srv/sua-plataforma/app
Environment=PYTHONPATH=/srv/sua-plataforma/app
EnvironmentFile=/etc/sua-plataforma/backend.env
ExecStart=/srv/sua-plataforma/app/.venv/bin/celery -A backend.worker.celery_app:app beat --loglevel=INFO --schedule /srv/sua-plataforma/shared/celerybeat-schedule
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=/srv/sua-plataforma/shared

[Install]
WantedBy=multi-user.target
```

Não execute dois Celery Beat para o mesmo ambiente, pois tarefas periódicas podem ser duplicadas.

## 6. Nginx

Um virtual host básico, após ajustar domínio e caminho:

```nginx
server {
    listen 80;
    server_name app.seudominio.com.br;

    root /srv/sua-plataforma/app/frontend/build;
    index index.html;
    client_max_body_size 25m;

    location /ws {
        proxy_pass http://127.0.0.1:8002;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location ~ ^/(api|auth|webhook|media-sources|health|media|agents-sdk)(/|$) {
        proxy_pass http://127.0.0.1:8002;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location ~ ^/(oauth-home|privacy-policy|terms)$ {
        default_type text/html;
        try_files $uri =404;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Valide antes de recarregar:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Em seguida configure um certificado TLS válido e redirecione HTTP para HTTPS. Só então mantenha `AUTH_COOKIE_SECURE=true`.

## 7. Ative e valide

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sua-plataforma-api sua-plataforma-worker sua-plataforma-beat
sudo systemctl status sua-plataforma-api sua-plataforma-worker sua-plataforma-beat --no-pager
```

O health de produção é protegido quando `MONITORING_TOKEN` está configurado. Faça a chamada pelo seu monitor, enviando o header `X-Monitoring-Token` sem registrar seu valor em logs.

Verifique também:

```bash
sudo journalctl -u sua-plataforma-api -n 100 --no-pager
sudo journalctl -u sua-plataforma-worker -n 100 --no-pager
sudo journalctl -u sua-plataforma-beat -n 100 --no-pager
```

## 8. Atualizações

Antes de atualizar:

1. faça backup verificável do PostgreSQL e das mídias;
2. leia as novas migrations;
3. instale dependências com lockfiles;
4. execute `alembic upgrade head` uma única vez;
5. gere o frontend novamente;
6. reinicie apenas API/workers afetados;
7. repita o checklist pós-clone.

Nunca use `git reset --hard`, apague o banco ou restaure um dump sobre produção como procedimento comum de deploy.
