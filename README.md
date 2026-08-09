# 禹算服务端 - 部署与集成指南

## 项目结构

```
yusuan-server/
├── app.py              # Flask主应用（API + 管理后台）
├── models.py           # 数据库模型（用户、激活码、订单）
├── yusuan_api.py       # 客户端API模块（集成到桌面程序）
├── requirements.txt    # Python依赖
├── Procfile            # Render部署配置
├── render.yaml         # Render一键部署配置
├── runtime.txt         # Python版本
├── .env.example        # 环境变量模板
└── templates/admin/    # 管理后台页面
    ├── login.html      # 管理员登录
    ├── dashboard.html  # 仪表盘
    ├── users.html      # 用户管理
    ├── codes.html      # 激活码管理
    └── orders.html     # 订单管理
```

---

## 一、本地运行测试

### 1. 安装依赖

```bash
cd yusuan-server
pip install -r requirements.txt
```

### 2. 启动服务

```bash
python app.py
```

服务启动在 http://localhost:5000

### 3. 访问管理后台

打开浏览器访问 http://localhost:5000/admin

默认管理员账号：`admin` / `yusuan2024admin`

### 4. 测试API

```bash
# 健康检查
curl http://localhost:5000/api/health

# 获取套餐列表
curl http://localhost:5000/api/plans
```

---

## 二、部署到 Render（免费）

### 方式一：一键部署（推荐）

1. 将 `yusuan-server` 文件夹推送到 GitHub 仓库
2. 访问 https://dashboard.render.com 注册/登录
3. 点击 "New +" → "Web Service"
4. 连接你的 GitHub 仓库
5. Render 会自动读取 `render.yaml` 配置
6. 在 "Environment" 中填写以下变量：
   - `SMTP_USER`: 815293259@qq.com
   - `SMTP_PASS`: tpxcylhbhshqbaii
   - `DEVELOPER_EMAIL`: 815293259@qq.com
   - `ADMIN_PASSWORD`: 你的管理后台密码
7. 点击 "Create Web Service" 完成部署

### 方式二：手动部署

1. 在 Render 创建 Web Service
2. 设置：
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 120 app:app`
3. 添加 Environment Variables（同上）
4. 添加 Persistent Disk（1GB），挂载路径 `/data`
5. 修改 `DATABASE_URL` 为 `sqlite:///data/yusuan.db`
6. 部署

### 部署后

- API地址：`https://你的服务名.onrender.com`
- 管理后台：`https://你的服务名.onrender.com/admin`
- 免费套餐会在15分钟无请求后休眠，下次访问自动唤醒（约30秒）

---

## 三、集成到桌面客户端

### 1. 复制API模块

将 `yusuan_api.py` 复制到桌面程序同目录。

### 2. 安装 requests 库

```bash
pip install requests
```

### 3. 修改桌面程序

在 `禹算-水利水电工程全阶段计费软件8.9.py` 中：

```python
# 在文件顶部添加
from yusuan_api import get_api

# 获取全局API实例
api = get_api()
```

### 4. 替换注册逻辑

找到 `_reg_verify_code()` 方法中注册成功后的代码，替换为：

```python
# 原代码：保存到本地
# _save_user_login_data(user_data)

# 新代码：注册到服务器
success, data = api.register(email, username, password, self._reg_code)
if success:
    login_success = True
    self._token = data.get('token')
    self._user_data = data.get('user')
    # 同时保存到本地（离线缓存）
    _save_user_login_data(user_data)
else:
    messagebox.showerror("注册失败", data.get('message', '未知错误'))
    return
```

### 5. 替换登录逻辑

找到 `_do_login()` 方法，替换为：

```python
def _do_login(self):
    username = self.login_username_entry.get().strip()
    password = self.login_password_entry.get().strip()

    if not username or not password:
        messagebox.showwarning("提示", "请输入用户名和密码")
        return

    # 优先尝试服务器登录
    if api.check_server():
        success, data = api.login(username, password)
        if success:
            self.login_success = True
            self._token = data.get('token')
            self._user_data = data.get('user')
            # 保存到本地
            user_data = {
                "username": username,
                "password_hash": _hash_password(password),
                "email": data.get('user', {}).get('email', ''),
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            _save_user_login_data(user_data)
            self.destroy()
            return
        else:
            messagebox.showerror("登录失败", data.get('message', '未知错误'))
            return

    # 服务器不可用，回退到本地登录
    # ... 原有本地登录逻辑 ...
```

### 6. 替换激活码验证

找到 `MembershipManager.activate_membership()` 方法，添加服务器激活：

```python
def activate_membership(self, code):
    # 优先尝试服务器激活
    if api.is_logged_in:
        success, data = api.activate_membership(code)
        if success:
            # 服务器激活成功，同步到本地
            # ... 更新本地membership数据 ...
            return True

    # 回退到本地验证
    # ... 原有本地验证逻辑 ...
```

### 7. 替换会员状态检查

```python
def get_membership_info(self):
    # 优先从服务器获取
    if api.is_logged_in and api.check_server():
        success, info = api.get_membership()
        if success:
            return info

    # 回退到本地数据
    # ... 原有本地逻辑 ...
```

---

## 四、管理后台使用

### 用户管理
- 查看所有注册用户
- 搜索用户（用户名/邮箱）
- 禁用/启用用户
- 手动设置会员套餐
- 重置用户密码

### 激活码管理
- 批量生成激活码（选择套餐和数量）
- 查看激活码使用状态
- 删除未使用的激活码
- 添加备注（如来源渠道）

### 订单管理
- 查看所有订单
- 按状态筛选（待支付/已支付/已取消）
- 确认支付（自动激活会员）
- 取消订单

---

## 五、API 接口文档

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | /api/health | 健康检查 | 无 |
| GET | /api/plans | 获取套餐列表 | 无 |
| POST | /api/send-code | 发送注册验证码 | 无 |
| POST | /api/register | 注册 | 无 |
| POST | /api/login | 登录 | 无 |
| GET | /api/membership | 获取会员状态 | JWT |
| POST | /api/verify-code | 验证激活码 | 无 |
| POST | /api/activate | 激活会员 | JWT |
| POST | /api/order | 提交订单 | JWT |
| POST | /api/change-password | 修改密码 | JWT |

### 认证方式

需要认证的接口在请求头中添加：
```
Authorization: Bearer <token>
```

### 响应格式

```json
{
    "success": true,
    "message": "操作成功",
    "data": {}
}
```

---

## 六、注意事项

1. **数据安全**：生产环境务必修改 `SECRET_KEY` 和 `JWT_SECRET`
2. **SQLite限制**：免费Render有磁盘限制，用户量大后建议迁移到 PostgreSQL
3. **休眠问题**：Render免费套餐会休眠，首次访问需等待约30秒唤醒
4. **邮件发送**：QQ邮箱SMTP有日发送限制（约50封），用户量大需升级
5. **备份**：定期备份 `/data/yusuan.db` 数据库文件

---

## 七、备选部署方案

如果 Render 不稳定，可考虑：

1. **Railway** (https://railway.app) - 每月$5免费额度，支持SQLite
2. **Fly.io** (https://fly.io) - 免费3个VM，支持持久存储
3. **Vercel** - 需改用 Serverless 架构（需重构代码）
4. **自有VPS** - 阿里云/腾讯云轻量应用服务器（约50元/月）
