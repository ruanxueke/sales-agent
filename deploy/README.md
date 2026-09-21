# 阿里云部署步骤（简版）

1. 把整个项目上传到服务器，例如放到 `/opt/sales-agent/`。
2. 上传后进入项目目录：

```bash
cd /opt/sales-agent
```

3. 安装环境（只需一次）：

```bash
sudo bash deploy/install.sh
```

4. 启动服务：

```bash
sudo bash deploy/start.sh
```

5. 配置 Nginx，把 `deploy/nginx-sales.conf` 里的 `你的域名.com` 改成你的域名，然后执行：

```bash
sudo cp deploy/nginx-sales.conf /etc/nginx/conf.d/sales-agent.conf
sudo nginx -t
sudo systemctl reload nginx
```

6. 申请 HTTPS 证书：

```bash
sudo certbot --nginx -d 你的域名.com
```

7. 公众号后台服务器配置：

```text
URL: https://你的域名.com/wechat
Token: token2026
EncodingAESKey: E1sYAnwAUlOQ6k1JLJajm3GBRV18hTtyqlT7sSC3rgt
```

注意：服务器在大陆时，域名需要先完成 ICP 备案。
