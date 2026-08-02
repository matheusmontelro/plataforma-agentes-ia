# 5. Nome, logo e identidade visual

A distribuição pública usa placeholders para evitar herdar a marca de outra empresa. Faça esta etapa antes de publicar a URL para usuários.

## Nome e textos públicos

Em `frontend/.env.local` no desenvolvimento, ou em `frontend/.env.production` durante o build de produção:

```dotenv
VITE_APP_NAME=SUA_EMPRESA
VITE_APP_DESCRIPTION=Plataforma de agentes de IA da sua empresa
VITE_SUPPORT_NAME=Equipe da SUA_EMPRESA
VITE_SUPPORT_EMAIL=suporte@seudominio.com.br
```

Esses valores são públicos e aparecerão no bundle. O e-mail deve ser uma caixa de suporte real, sem credenciais na URL.

## Arquivos de marca

Substitua os SVGs em:

```text
frontend/public/branding/logo-light.svg
frontend/public/branding/logo-dark.svg
frontend/public/branding/icon.svg
frontend/public/branding/icon-white.svg
```

Orientação:

- `logo-light.svg`: logo para fundos claros.
- `logo-dark.svg`: logo para fundos escuros.
- `icon.svg`: ícone colorido, aproximadamente quadrado.
- `icon-white.svg`: versão monocromática clara.

Mantenha os nomes e caminhos para não alterar componentes. Os SVGs distribuídos são placeholders editáveis; não deixe `SUA_EMPRESA` visível na versão final.

Não adicione arquivos com dados de clientes, assinaturas pessoais, metadados sensíveis ou URLs de armazenamento privado.

## Páginas e metadados estáticos

As variáveis `VITE_*` são aplicadas ao JavaScript, mas não reescrevem automaticamente os arquivos estáticos. Antes de publicar, edite também:

```text
frontend/index.html
frontend/public/manifest.json
frontend/public/oauth-home
frontend/public/privacy-policy
frontend/public/terms
```

- substitua `SUA_EMPRESA`, descrições e e-mails de exemplo;
- informe a data real da última atualização dos termos e da política;
- revise o texto jurídico de acordo com sua operação e jurisdição;
- preserve os nomes `oauth-home`, `privacy-policy` e `terms`, pois são URLs públicas sem extensão.

Faça uma conferência antes do build:

```bash
rg -n 'SUA_EMPRESA|seu-dominio|seudominio|Ultima atualizacao' \
  frontend/index.html \
  frontend/public/manifest.json \
  frontend/public/oauth-home \
  frontend/public/privacy-policy \
  frontend/public/terms
```

O comando deve listar somente valores que você revisou conscientemente; não publique os placeholders como se fossem dados finais.

## Marca global e marca de cada workspace

As variáveis `VITE_*` e os arquivos acima definem a marca global da plataforma instalada. Já `name_company` e `logo_url` são dados de cada workspace e continuam sendo configuráveis na aplicação. Não substitua a personalização por empresa por um valor fixo no código.

## Aplicar e conferir

Alterações de `VITE_*` exigem reiniciar o servidor de desenvolvimento:

```bash
npm --prefix frontend start
```

Em produção, faça um novo build e publique o diretório `frontend/build`:

```bash
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Confira pelo menos:

- título da aba e manifesto/PWA;
- páginas estáticas de OAuth, privacidade e termos;
- login e recuperação de senha;
- sidebar desktop e navegação mobile;
- dashboards e páginas vazias;
- temas claro e escuro;
- logo específico de um workspace;
- visualização em celular.

Se a marca antiga continuar aparecendo, veja [Troubleshooting](07-troubleshooting.md#o-logo-ou-o-nome-antigo-continua-aparecendo).
