# 1. Pré-requisitos

## Versões compatíveis

- Git 2.40 ou superior.
- ripgrep (`rg`) para os validadores e conferências do repositório.
- Python 3.12.
- PostgreSQL 15 ou superior.
- Redis 6 ou superior.
- Node.js `20.19+` ou `22.12+`.
- npm compatível com a versão do Node.
- `ffmpeg` para recursos de áudio.
- Nginx ou outro proxy reverso para produção.
- Docker Engine com Compose v2, somente se usar o arquivo opcional de dependências.

O requisito de Node vem do Vite 7 registrado em `frontend/package-lock.json`. Use a versão exata do lockfile com `npm ci`; não atualize dependências durante a primeira instalação.

## Capacidade inicial sugerida

Para estudo e poucos usuários, comece com 2 vCPU, 4 GB de RAM e espaço separado para PostgreSQL e mídias. Recursos de transcrição, modelos locais e múltiplos workers podem exigir mais memória. Monitore o consumo antes de aumentar concorrência.

## Portas

| Serviço | Porta local sugerida | Exposição pública |
| --- | ---: | --- |
| PostgreSQL | 5432 | não |
| Redis | 6379 | não |
| Backend FastAPI | 8002 | não; somente via proxy |
| Frontend Vite (desenvolvimento) | 3004 | apenas rede de desenvolvimento |
| WAHA, se instalado | 3000 | não; somente backend |
| Nginx | 80/443 | sim |

Não publique PostgreSQL, Redis, o backend cru ou o painel administrativo do WAHA na internet.

## Verifique o ambiente

```bash
git --version
python3.12 --version
psql --version
redis-server --version
node --version
npm --version
ffmpeg -version
```

## Ubuntu 24.04

Um ponto de partida possível é:

```bash
sudo apt update
sudo apt install -y \
  git ripgrep python3.12 python3.12-venv python3-dev build-essential libpq-dev \
  postgresql redis-server ffmpeg nginx
```

Instale uma versão compatível do Node pelo método recomendado para seu servidor. Confirme a versão antes de executar `npm ci`.

## Serviços locais

Em distribuições com systemd:

```bash
sudo systemctl enable --now postgresql redis-server
sudo systemctl is-active postgresql redis-server
```

Os dois serviços devem retornar `active` antes de iniciar o backend.

## Alternativa com Docker para as dependências

Se preferir não instalar PostgreSQL e Redis no host, o repositório inclui `compose.dependencies.yml`. Ele inicia somente PostgreSQL 15 e Redis 7; não containeriza backend, frontend nem WAHA.

Crie o arquivo local das dependências e defina uma senha forte em `POSTGRES_PASSWORD`. Opcionalmente, altere banco, usuário e portas. A cópia é ignorada pelo Git:

```bash
cp .env.dependencies.example .env.dependencies
```

Edite `.env.dependencies`, preencha a senha e só então inicie:

```bash
docker compose --env-file .env.dependencies -f compose.dependencies.yml up -d
docker compose --env-file .env.dependencies -f compose.dependencies.yml ps
```

Espere os dois containers ficarem `healthy`. Use no `backend/.env` o mesmo banco, usuário e senha definidos para o Compose.

`docker compose --env-file .env.dependencies -f compose.dependencies.yml down` preserva os volumes nomeados. Não use `down -v` em uma instalação com dados que você queira manter.
