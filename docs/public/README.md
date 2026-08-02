# Guia público de instalação

Este guia foi escrito para uma clonagem nova, sem banco de dados herdado e sem acesso à infraestrutura de quem publicou o código. Siga os documentos na ordem abaixo.

| Etapa | Documento | Resultado esperado |
| --- | --- | --- |
| 1 | [Pré-requisitos](01-pre-requisitos.md) | versões compatíveis instaladas |
| 2 | [Instalação local](02-instalacao-local.md) | dependências e arquivos locais configurados |
| 3 | [Banco e primeiro administrador](03-banco-de-dados.md) | schema no único `head` e login próprio |
| 4 | [Configuração](04-configuracao.md) | variáveis obrigatórias e opcionais entendidas |
| 5 | [Personalização](05-personalizacao.md) | nome, suporte e logos substituídos |
| 6 | [Deploy](06-deploy.md) | aplicação servida com HTTPS e serviços isolados |
| 7 | [Troubleshooting](07-troubleshooting.md) | diagnóstico dos erros mais comuns |
| 8 | [Checklist pós-clone](08-checklist-pos-clone.md) | evidências de que a instalação está íntegra |

## Contratos importantes

- PostgreSQL é obrigatório; SQLite não representa o schema real.
- O histórico público começa em uma única migration: `backend/alembic/versions/0001_initial_public_schema.py`.
- Use `alembic upgrade head` em um banco vazio. Não use `Base.metadata.create_all()` como substituto.
- Redis é obrigatório para o startup do backend e para eventos em tempo real; Celery é necessário para filas e automações assíncronas.
- WAHA é uma integração separada. O painel e o banco podem ser preparados antes de conectar uma sessão do WhatsApp.
- Não existe usuário nem senha padrão. O primeiro administrador é criado com um comando interativo e senha oculta.
- Não existe autocadastro público. Novas contas e workspaces são criados por usuários autorizados.
- O frontend usa rotas de API no mesmo domínio. Em desenvolvimento, o Vite faz o proxy; em produção, o proxy é responsabilidade do Nginx ou equivalente.

## O que não acompanha o clone

O repositório não deve conter bancos preenchidos, sessões de WhatsApp, mídias de clientes, arquivos `.env`, credenciais OAuth, chaves de IA nem dados de produção. Você deverá criar e proteger esses recursos na sua própria infraestrutura.

## Licença

A licença MIT permite uso, modificação, distribuição e operação comercial, desde que o aviso de copyright e a licença acompanhem as cópias ou partes substanciais do software. Consulte o arquivo [`LICENSE`](../../LICENSE).
