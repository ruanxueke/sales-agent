#!/usr/bin/env bash
set -e

# 阿里云 Ubuntu 服务器：一键安装 Docker、Nginx、Certbot
echo "===== 开始安装基础环境 ====="
sudo apt update
sudo apt install -y ca-certificates curl gnupg nginx
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable --now docker
sudo apt install -y certbot python3-certbot-nginx
echo "===== 基础环境安装完成 ====="
