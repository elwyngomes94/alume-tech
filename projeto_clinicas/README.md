# Alume Tech

Sistema Integrado de Gestao para Clinicas — plataforma SaaS multiclinicas
construida com **Python + Django**.

Atende clinicas medicas, de fisioterapia, odontologicas, de psicologia, de
nutricao, de estetica, de dermatologia, de exames, multidisciplinares,
veterinarias (quando habilitado) e outros tipos configuraveis — sem exigir
alteracao de codigo para adicionar um novo tipo de clinica.

## Sumario

- [Arquitetura](#arquitetura)
- [Requisitos](#requisitos)
- [Instalacao local](#instalacao-local)
- [Variaveis de ambiente](#variaveis-de-ambiente)
- [Banco de dados e migracoes](#banco-de-dados-e-migracoes)
- [Superusuario e dados de demonstracao](#superusuario-e-dados-de-demonstracao)
- [Execucao local](#execucao-local)
- [Docker](#docker)
- [Testes](#testes)
- [Seguranca e LGPD](#seguranca-e-lgpd)
- [Backup](#backup)
- [Estrutura do projeto](#estrutura-do-projeto)
- [API](#api)
- [Deploy em producao](#deploy-em-producao)

## Arquitetura

```
ALUME TECH
│
├── SUPERADMIN (/platform/)      Administracao global da plataforma
├── CLINICA (/app/)              Painel operacional de cada clinica (tenant)
└── PACIENTE (/patient/)         Portal do paciente
```

Multitenancy real: toda tabela operacional (`patients.Patient`,
`scheduling.Appointment`, `medical_records.*`, `documents.Document` etc.)
possui uma FK obrigatoria `clinic`. O isolamento e garantido em profundidade:

1. **Middleware de tenant** (`apps/tenants/middleware.py`) resolve a clinica
   ativa a partir do vinculo do usuario no banco — nunca confia apenas na URL
   ou na sessao sem reconferir.
2. **Manager com filtro automatico** (`apps/core/managers.py`): sem tenant
   ativo no contexto, qualquer consulta retorna vazio (falha fechada).
3. **Validacao no `save()`**: um objeto nao pode ser gravado em uma clinica
   diferente da clinica ativa (`apps/core/models.py::TenantModel.save`).
4. **Views** (`apps/core/mixins.py::ClinicViewMixin`) reforcam o filtro por
   clinica e devolvem `404` (nao `403`) para objetos de outra clinica, para
   nao revelar a existencia do registro.
5. **API REST** aplica as mesmas regras via `apps/api/permissions.py`.

Veja `tests/test_multitenancy.py` para os testes automatizados que provam o
isolamento nos dois sentidos (Clinica A não acessa Clinica B e vice-versa).

## Requisitos

- Python 3.11+
- PostgreSQL 14+ (producao/homologacao) — SQLite funciona para desenvolvimento
  rapido sem instalar nada
- Redis (cache e broker do Celery)
- Docker e Docker Compose (opcional, recomendado para subir tudo de uma vez)

## Instalacao local

```powershell
cd projeto_clinicas
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements/dev.txt
copy .env.example .env
```

Edite o `.env` gerado com seus valores (nunca comite esse arquivo).

## Variaveis de ambiente

Todas as credenciais e chaves ficam em variaveis de ambiente — nunca no
codigo-fonte. Consulte `.env.example` para a lista completa comentada:
banco de dados, Redis/Celery, e-mail, armazenamento privado, sessao,
protecao de login e identidade da plataforma.

Sem `DATABASE_URL` definido, o projeto usa SQLite automaticamente (apenas
para desenvolvimento).

## Banco de dados e migracoes

```powershell
python manage.py migrate
```

O settings padrao para desenvolvimento e `config.settings.dev`
(`DJANGO_SETTINGS_MODULE=config.settings.dev`, ja definido em
`manage.py`). Para producao use `config.settings.prod` (HTTPS obrigatorio,
HSTS, cookies seguros).

## Superusuario e dados de demonstracao

```powershell
python manage.py createsuperuser
```

Para gerar rapidamente um ambiente de demonstracao completo (superadmin,
duas clinicas de tipos diferentes, administrador, recepcionista,
profissional e paciente em cada uma — todos com dados **ficticios**):

```powershell
python manage.py seed_demo
```

A senha padrao de todos os usuarios criados pelo `seed_demo` e impressa no
final do comando. **Nao use este comando em producao.**

## Execucao local

```powershell
python manage.py runserver
```

Acesse:

- `/` — redireciona conforme o perfil autenticado
- `/accounts/login/` — login
- `/app/` — painel da clinica
- `/platform/` — administracao da plataforma (SUPERADMIN)
- `/patient/` — portal do paciente
- `/api/v1/` — API REST
- `/django-admin/` — Django Admin (uso tecnico/manutencao)
- `/healthz/` — health check

Para processar tarefas assincronas (lembretes, backup) em desenvolvimento,
`CELERY_TASK_ALWAYS_EAGER=True` (padrao do `.env.example`) executa as
tarefas de forma sincrona, sem precisar subir um worker separado. Para rodar
o worker de verdade:

```powershell
celery -A config worker -l info
celery -A config beat -l info
```

## Docker

Sobe banco (PostgreSQL), Redis, aplicacao web, worker Celery, Celery Beat e
Nginx:

```powershell
copy .env.example .env
docker compose up --build
```

A aplicacao roda migracoes e `collectstatic` automaticamente antes de subir
o Gunicorn. Acesse via `http://localhost/`.

## Testes

```powershell
$env:DJANGO_SETTINGS_MODULE="config.settings.test"
python manage.py test tests
```

A suite cobre, entre outros pontos:

- **Multitenancy** (`test_multitenancy.py`): isolamento no ORM, em views
  HTTP, protecao contra adulteracao de sessao/URL, e acesso assistencial do
  profissional (so ve pacientes com vinculo real de atendimento).
- **Permissoes/RBAC** (`test_permissions.py`): perfis, permissao negada via
  URL manipulada devolvendo `403`, e restricao do painel do SUPERADMIN.
- **Seguranca** (`test_security.py`): validacao de upload (extensao, MIME,
  assinatura binaria), imutabilidade da auditoria, protecao contra forca
  bruta no login.
- **Agenda** (`test_scheduling.py`): conflitos de horario, bloqueios,
  encaixe (overbooking), maquina de estados dos agendamentos.
- **Prontuario** (`test_medical_records.py`): assinatura, retificacao com
  historico de versoes, isolamento por clinica.

## Seguranca e LGPD

Implementado nesta versao:

- Custom User Model com hashing seguro (PBKDF2), MFA (TOTP) opcional,
  bloqueio por tentativas de login, expiracao de sessao por inatividade e
  controle de sessoes por dispositivo.
- CSRF, XSS (CSP configurado), protecao contra SQL Injection via ORM
  parametrizado, cabecalhos de seguranca (`X-Content-Type-Options`,
  `Referrer-Policy`, `Permissions-Policy`).
- Uploads validados por extensao, tipo MIME **e assinatura binaria do
  arquivo** — nao apenas o nome enviado pelo navegador.
- Documentos clinicos ficam em armazenamento privado
  (`PRIVATE_MEDIA_ROOT`), fora de qualquer diretorio publico, servidos
  apenas por view autenticada com verificacao de permissao e auditoria.
- Trilha de auditoria **imutavel** (`apps/audit`), com encadeamento de
  checksum, registrando login/logout, CRUD, visualizacao de dado sensivel,
  download, upload, alteracao de permissoes e acesso administrativo do
  SUPERADMIN.
- Exclusao logica (soft delete) em todos os modelos de dominio, preservando
  historico clinico.
- UUID como identificador publico de todos os objetos sensiveis (nunca IDs
  sequenciais nas URLs).
- Estrutura LGPD (`apps/lgpd`): tipos de consentimento com base legal
  explicita, registro/revogacao de consentimento, solicitacoes do titular
  (art. 18), anonimizacao preservando o historico assistencial estatistico,
  registro de incidentes de seguranca.

**Regra de ouro aplicada em todas as camadas**: nenhuma permissao e decidida
apenas no frontend. Toda view, toda API e toda query reconferem tenant e
permissao no backend.

## Backup

`apps/core/tasks.py::executar_backup` roda diariamente via Celery Beat,
gerando dump do PostgreSQL (`pg_dump`) e arquivo compactado dos documentos
privados em `BACKUP_ROOT`, com expurgo automatico apos
`BACKUP_RETENTION_DAYS`. Os backups nunca sao expostos a usuarios das
clinicas — apenas acessiveis via infraestrutura/operacao.

## Estrutura do projeto

```
projeto_clinicas/
├── config/                 settings (base/dev/prod/test), urls, celery, wsgi/asgi
├── apps/
│   ├── core/                tenancy, managers/models base, storage, validators, mixins
│   ├── accounts/             usuario custom, MFA, RBAC, sessoes, tokens de API
│   ├── tenants/               organizacao e vinculo usuario-clinica
│   ├── clinics/                clinica, configuracoes, cadastros auxiliares
│   ├── professionals/            profissionais
│   ├── patients/                   pacientes
│   ├── scheduling/                    agenda, disponibilidade, bloqueios
│   ├── medical_records/                  prontuario configuravel por tipo de clinica
│   ├── examinations/                        solicitacao/resultado de exames
│   ├── documents/                              documentos com storage privado
│   ├── notifications/                             notificacoes internas + fila de envio
│   ├── audit/                                        trilha de auditoria imutavel
│   ├── billing/                                         planos/assinaturas/faturas
│   ├── reports/                                            relatorios (CSV/Excel/PDF)
│   ├── dashboard/                                            paineis e busca global
│   ├── platform_admin/                                          painel do SUPERADMIN
│   ├── portal/                                                     portal do paciente
│   ├── lgpd/                                                          consentimento/LGPD
│   └── api/                                                              API REST v1
├── templates/                Bootstrap 5, layouts por area (app/platform/portal/auth)
├── static/                    CSS/JS proprios (identidade visual do Alume Tech)
├── tests/                      testes automatizados (multitenancy, RBAC, seguranca...)
├── requirements/                base/dev/prod
├── deploy/nginx.conf
├── Dockerfile / docker-compose.yml
└── manage.py
```

## API

Versionada em `/api/v1/`, construida com Django REST Framework:

- Autenticacao por sessao (uso pelo proprio frontend) ou token
  (`Authorization: Bearer <token>`, gerado em `/accounts/seguranca/`).
- Um token pode ser restrito a uma clinica especifica.
- Paginacao, filtros (`django-filter`), `SearchFilter`/`OrderingFilter`.
- Rate limiting por usuario/anonimo.
- Todo endpoint de recurso de clinica aplica `HasClinicContext` +
  `ClinicPermission`, reforcando o mesmo isolamento por tenant do painel
  web.
- `GET /api/v1/eu/` retorna identidade, clinica ativa e permissoes efetivas
  do usuario autenticado — util para integracoes e para o futuro aplicativo
  mobile.

## Deploy em producao

1. Defina `DJANGO_SETTINGS_MODULE=config.settings.prod`.
2. Configure `DATABASE_URL` apontando para PostgreSQL gerenciado/dedicado.
3. Configure HTTPS na borda (`SECURE_SSL_REDIRECT=True` por padrao no
   settings de producao) e ajuste `DJANGO_ALLOWED_HOSTS` /
   `DJANGO_CSRF_TRUSTED_ORIGINS`.
4. Rode `python manage.py migrate` e `python manage.py collectstatic`.
5. Sirva a aplicacao com Gunicorn atras de Nginx (ver
   `deploy/nginx.conf` e `docker-compose.yml`).
6. Configure o Celery Beat para as tarefas agendadas (lembretes de
   agendamento, expurgo de notificacoes, backup diario).
7. Opcionalmente configure `SENTRY_DSN` para monitoramento de erros
   (`send_default_pii=False` por padrao, para nao enviar dados pessoais ao
   monitoramento).

### Deploy rapido no Render

O arquivo `render.yaml` na raiz do projeto e um Blueprint pronto para o
[Render](https://render.com): cria o servico web (Gunicorn via Docker),
worker do Celery, Celery Beat, Postgres e Redis gerenciados, com HTTPS
automatico e sem precisar mexer em servidor. Em Render -> New -> Blueprint,
aponte para este repositorio e revise os planos sugeridos antes de aplicar.

Limitacao conhecida: no Render, o disco persistente e exclusivo de cada
servico (diferente dos volumes compartilhados do `docker-compose.yml`) --
por isso o worker/beat nao tem acesso aos arquivos de midia salvos pelo
servico web, e o backup automatico de documentos anexados fica incompleto
ate configurarmos armazenamento em nuvem (S3/R2) com `django-storages`. O
backup do banco de dados (`pg_dump`) funciona normalmente. Isso nao impede
o sistema de entrar no ar -- e uma melhoria a fazer depois.

---

Este projeto foi construido como uma aplicacao Django funcional completa —
com banco de dados real, autenticacao real, permissoes reais, multitenancy
real, CRUDs funcionais, upload seguro, auditoria, dashboards com Chart.js,
API REST e testes automatizados de seguranca — pronta para evoluir rumo a
producao.
