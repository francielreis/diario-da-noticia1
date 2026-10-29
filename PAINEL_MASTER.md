# Reis Tech e Software — Painel Master (MVP)

**Branch:** feat/reis-tech-painel-master

O módulo novo registra portais de clientes sem alterar o Diário da Notícia
atual nem as tabelas legadas de notícias/patrocinadores. O portal principal
continua em / e /admin; os sites de clientes usam /p/<slug>/.

## Rotas disponíveis

- /master — login master
- /master/painel — cadastro e gestão de portais
- /p/<slug>/ — site público do cliente
- /p/<slug>/admin — login da redação do cliente
- /p/<slug>/admin/painel — notícias do cliente
- /p/<slug>/admin/noticias/nova — publicar notícia
- /p/<slug>/admin/configuracoes — personalizar logo, cor e slogan
- /p/<slug>/admin/anuncios — administrar patrocinadores
- /master/mensalidades — registro manual de mensalidades

## Recursos deste MVP

- Cadastro de portais com nome, slug, responsável, login e senha própria.
- Planos simbólicos: básico R$ 99; profissional R$ 150; premium R$ 249.
- Suspensão e reativação do acesso editorial, sem remover notícias públicas.
- Troca da senha do cliente pelo master, armazenada como hash, não em texto claro.
- Publicação, edição e exclusão de matérias com imagem via Cloudinary.
- Logotipo, cor da marca e slogan personalizados por cliente.
- Patrocinadores e banners independentes, com pausa e exclusão.
- Controle manual de mensalidades por competência (mês), com registro de pago ou pendente.
- Isolamento por portal_id em TODAS as leituras e alterações de matérias novas.
- CSRF em todos os formulários que alteram dados.
- Compatibilidade com SQLite (desenvolvimento) e PostgreSQL (Render).

A **receita exibida é apenas previsão de mensalidades de portais ativos**;
não representa pagamentos recebidos.

## Configuração para testar em um Render separado

**Não conectar a branch ao serviço de produção do Diário da Notícia.**
Crie um serviço de testes a partir da branch e use um banco PostgreSQL de testes,
distinto do banco de produção. Certifique-se de ter backup do conteúdo atual.

Variáveis de ambiente:

- SECRET_KEY — valor aleatório e exclusivo do ambiente.
- DATABASE_URL — URL do PostgreSQL de testes.
- MASTER_USER — usuário do proprietário da plataforma.
- MASTER_PASSWORD_HASH — hash da senha master, gerado pelo comando abaixo.
- CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY e CLOUDINARY_API_SECRET — para imagens;
  sem elas é possível publicar texto, mas uploads falham.

Gere o hash localmente (sem colocar a senha no repositório):

    python -c "from werkzeug.security import generate_password_hash; from getpass import getpass; print(generate_password_hash(getpass('Senha master: ')))"

Comando de inicialização:

    gunicorn app:app

O banco terá tabelas adicionais saas_portais, saas_noticias,
saas_marcas, saas_anuncios e saas_mensalidades. O registro
dessas tabelas é aditivo, mas **nunca use o banco de produção para testar**.

## Testes

    pip install -r requirements.txt
    python -m unittest discover -s tests -v

GitHub Actions executa esses testes na branch e nos pull requests para main.

## Limitações e próximos passos

Esta etapa **não implementa** domínio próprio ativo, checkout/cobrança PIX,
perfis de vários redatores por portal, analytics, nem migração das notícias
existentes do Diário. O registro de mensalidades não movimenta dinheiro e não
autentica transações; o administrador informa manualmente o status.
Essas funcionalidades devem ser desenvolvidas e testadas antes da venda
comercial, com backups, verificação de imagens persistentes e política de
privacidade/LGPD. Não divulgue como disponíveis recursos ainda não entregues.

## Situação da hospedagem em 29/10/2026

A conta Render tem 21 serviços web + 4 instâncias de Postgres,
atingindo o limite de 25 serviços do plano Hobby. A tentativa de criar
`reis-portais-staging-db` foi recusada pelo Render com HTTP 400 e
`Hobby Tier is limited to 25 services`.

Para publicar o MVP em ambiente independente, precisam existir ao menos
dois slots: **um para o serviço web e outro para um PostgreSQL**.
Não remover nem reaproveitar serviços/bancos existentes sem conferir
uso, backup e autorização explícita.

**Atenção:** o Render reportou para `diario-noticia-db` (o banco atual
com tabelas `noticias` e `patrocinadores`) expiração do plano grátis
em 29/10/2026 às 15:59 UTC. Inspecione imediatamente a instância, o backup
e as opções para evitar indisponibilidade/perda de dados do Diário atual.
