#!/bin/bash
# 禹算服务端一键部署脚本
# 用法：在服务器上执行 bash deploy.sh

set -e

echo "===== 禹算服务端部署 ====="

# ── 1. 安装依赖 ──
echo "[1/6] 安装系统依赖..."
apt update -y
apt install -y python3 python3-pip python3-venv nginx git

# ── 2. 创建项目目录 ──
echo "[2/6] 创建项目目录..."
PROJECT_DIR="/opt/yusuan-server"
mkdir -p "$PROJECT_DIR/data"
cd "$PROJECT_DIR"

# ── 3. 拉取代码（从Gitee） ─
echo "[3/6] 拉取代码..."
if [ ! -f "app.py" ]; then
    git clone https://gitee.com/liu-changhui-66/yusuan-server.git .
else
    echo "代码已存在，跳过拉取"
fi

# ── 4. 创建虚拟环境并安装依赖 ──
echo "[4/6] 安装Python依赖..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# ── 5. 创建systemd服务 ──
echo "[5/6] 配置后台服务..."
cat > /etc/systemd/system/yusuan.service << SERVICEEOF
[Unit]
Description=YuSuan Server
After=network.target

[Service]
User=root
WorkingDirectory=$PROJECT_DIR
Environment="DATABASE_URL=sqlite://$PROJECT_DIR/data/yusuan.db"
Environment="SECRET_KEY=yusuan2024supersecretkey123456"
Environment="JWT_SECRET=yusuan-jwt-2024-abcxyz789"
Environment="SMTP_USER=815293259@qq.com"
Environment="SMTP_PASS=tpxcylhbhshqbaii"
Environment="DEVELOPER_EMAIL=815293259@qq.com"
Environment="ADMIN_PASSWORD=yusuan2024admin"
ExecStart=$PROJECT_DIR/venv/bin/gunicorn --bind 127.0.0.1:5000 --workers 2 --timeout 120 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable yusuan
systemctl start yusuan

# ── 6. 配置Nginx ──
echo "[6/6] 配置Nginx..."
cat > /etc/nginx/sites-available/yusuan << NGINXEOF
server {
    listen 80;
    server_name _;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINXEOF

# 删除默认站点（如果有）
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/yusuan /etc/nginx/sites-enabled/yusuan
nginx -t && systemctl reload nginx

echo ""
echo "===== 部署完成 ====="
echo "管理后台: http://$(curl -s ifconfig.me)/admin"
echo "默认管理员: admin / yusuan2024admin"
echo ""
echo "常用命令:"
echo "  查看状态: systemctl status yusuan"
echo "  重启服务: systemctl restart yusuan"
echo "  查看日志: journalctl -u yusuan -f"
