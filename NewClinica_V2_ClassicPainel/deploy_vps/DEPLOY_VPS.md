# Deploy no VPS (sem dor de cabeça) - NewClínica

Este deploy usa **Docker + Nginx + Certbot** (SSL automático).

## 1) No seu VPS (Ubuntu 22.04/24.04)
Instale Docker:
- sudo apt update
- sudo apt install -y ca-certificates curl gnupg
- sudo install -m 0755 -d /etc/apt/keyrings
- curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
- sudo chmod a+r /etc/apt/keyrings/docker.gpg
- echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
- sudo apt update
- sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
- sudo usermod -aG docker $USER
(saia e entre no SSH novamente)

## 2) Suba o projeto
Coloque a pasta `NewClinica_V2_ClassicPainel` em `/opt/newclinica` por SCP/WinSCP.

## 3) Configure domínio e variáveis
Entre em:
- cd /opt/newclinica/NewClinica_V2_ClassicPainel/deploy_vps

Copie o .env:
- cp .env.example .env
Edite o `.env` e troque `SECRET_KEY`.

Edite o domínio no Nginx:
- nano nginx/conf.d/newclinica.conf
Troque `__DOMINIO__` por exemplo `clinica.seudominio.com`

## 4) Primeiro start (HTTP)
- docker compose up -d --build

## 5) Gerar SSL (Let's Encrypt)
Crie a pasta do certbot (se não existir):
- mkdir -p certbot/www certbot/conf

Rode (troque email e domínio):
- docker compose run --rm certbot certonly --webroot -w /var/www/certbot -d clinica.seudominio.com --email seuemail@dominio.com --agree-tos --no-eff-email

Agora atualize o Nginx para HTTPS:
1) Abra `nginx/conf.d/newclinica.conf`
2) Adicione o bloco HTTPS (exemplo abaixo). Depois:
- docker compose restart nginx

### Exemplo bloco HTTPS (cole abaixo do server 80):
server {
    listen 443 ssl;
    server_name clinica.seudominio.com;

    ssl_certificate /etc/letsencrypt/live/clinica.seudominio.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/clinica.seudominio.com/privkey.pem;

    location / {
        proxy_pass http://newclinica:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

## 6) Backup do banco (recomendado)
O SQLite fica em:
- deploy_vps/data/newclinica.db

Faça backup diário dessa pasta (rsync, zip, ou enviar pra nuvem).
