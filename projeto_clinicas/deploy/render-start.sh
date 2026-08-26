#!/bin/bash
# Comando de inicializacao do servico web no Render.
#
# Roda migracoes e coleta os arquivos estaticos no MESMO container que vai
# servir as requisicoes (o "Pre-Deploy Command" do Render roda num container
# separado e efemero, entao arquivos gerados la -- como o manifesto do
# collectstatic -- nao chegam ao container que fica no ar).
set -e
python manage.py migrate --noinput
python manage.py ensure_superuser
python manage.py collectstatic --noinput
exec gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2
