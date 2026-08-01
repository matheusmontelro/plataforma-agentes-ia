# Como contribuir

Obrigado por ajudar a melhorar o projeto.

## Antes de começar

1. Abra uma issue descrevendo o problema ou a melhoria quando a mudança for ampla.
2. Crie uma branch curta a partir de `main`.
3. Preserve compatibilidade com PostgreSQL e não adicione dados de clientes, credenciais ou marcas privadas.
4. Não altere contratos da API ou migrações já publicadas sem explicar o impacto.

## Validação mínima

Com o ambiente configurado:

```bash
python tools/security_check.py
python -m pytest backend/tests
node tools/check-frontend-audit.mjs
npm --prefix frontend run typecheck
```

Para mudanças de banco, valide também em um PostgreSQL vazio:

```bash
cd backend
alembic upgrade head
alembic check
```

Não inclua builds, bancos, mídias, `.env` ou dependências geradas no commit.

## Pull request

Explique:

- o problema resolvido;
- os arquivos e contratos afetados;
- como a mudança foi validada;
- riscos de migração, segurança ou compatibilidade;
- capturas de tela para mudanças visuais, sem dados reais.
