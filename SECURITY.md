# Política de segurança

## Como relatar uma vulnerabilidade

Não publique credenciais, dados pessoais, provas de conceito destrutivas ou detalhes exploráveis em uma issue pública.

Use a opção **Report a vulnerability** na aba **Security** do repositório para abrir um aviso privado. Informe a versão/commit, impacto, passos mínimos de reprodução e uma sugestão de correção quando possível.

## Segredos expostos

Se um segredo real for enviado ao Git, removê-lo do arquivo não é suficiente:

1. revogue ou rotacione imediatamente no provedor;
2. verifique logs e uso indevido;
3. substitua o valor nos ambientes afetados;
4. trate a limpeza do histórico como medida complementar, nunca como revogação.

## Escopo esperado

São especialmente relevantes falhas de autenticação, isolamento entre empresas, acesso indevido a contatos/conversas, execução de webhooks, exposição de tokens e tomada de sessões de WhatsApp.

## Requisitos da instalação

- Injete segredos pelo gerenciador do ambiente ou por arquivo externo protegido; nunca por arquivo versionado.
- Mantenha tokens de acesso e renovação em cookies `HttpOnly`.
- O frontend não pode gravar `token`, `access_token`, `refresh_token` ou `api_key` em `localStorage` ou `sessionStorage`.
- Requisições mutáveis autenticadas por cookie devem preservar a proteção CSRF do cliente e do backend.
- Banco, Redis, backend e WAHA devem ficar em rede privada, com o Nginx ou equivalente como entrada pública.
- Armazene mídias, logos enviados, sessões e outros dados gerados apenas em diretórios de runtime ignorados pelo Git.

## Validação antes de contribuir

Execute pelo menos:

```bash
python tools/security_check.py
python -m compileall -q backend
node tools/check-frontend-audit.mjs
```

Não flexibilize o scanner para acomodar um valor parecido com segredo; substitua fixtures por marcadores seguros e mantenha os padrões de detecção rígidos.

O auditor frontend aceita somente a exceção documentada para o aviso de React Router restrito às APIs RSC instáveis, que este SPA não usa. Ele volta a falhar se detectar marcadores RSC ou qualquer outro aviso alto/crítico.
