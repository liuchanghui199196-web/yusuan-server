"""
禹算服务端 - Flask 主应用
API接口 + 管理后台 + 邮件通知
"""
import os
import jwt
import random
import smtplib
import threading
from datetime import datetime, timedelta
from functools import wraps
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_cors import CORS
from models import (
    db, User, ActivationCode, Order, EmailVerification,
    MEMBERSHIP_PLANS, TRIAL_DAYS
)

# ─────────────────────────────────────────────
# 应用配置
# ─────────────────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'yusuan-dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///yusuan.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# JWT配置
app.config['JWT_SECRET'] = os.environ.get('JWT_SECRET', 'yusuan-jwt-secret-2024')
JWT_EXPIRY_DAYS = 30  # Token有效期

# SMTP配置（QQ邮箱）
SMTP_HOST = 'smtp.qq.com'
SMTP_PORT = 465
SMTP_USER = os.environ.get('SMTP_USER', '815293259@qq.com')
SMTP_PASS = os.environ.get('SMTP_PASS', 'tpxcylhbhshqbaii')
DEVELOPER_EMAIL = os.environ.get('DEVELOPER_EMAIL', '815293259@qq.com')

# 管理员默认密码
ADMIN_DEFAULT_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'yusuan2024admin')

# CORS - 允许客户端跨域访问
CORS(app, resources={r"/api/*": {"origins": "*"}})

db.init_app(app)


# ─────────────────────────────────────────────
# JWT Token 工具函数
# ─────────────────────────────────────────────
def generate_token(user_id):
    """生成JWT Token"""
    payload = {
        'user_id': user_id,
        'exp': datetime.utcnow() + timedelta(days=JWT_EXPIRY_DAYS),
        'iat': datetime.utcnow(),
    }
    return jwt.encode(payload, app.config['JWT_SECRET'], algorithm='HS256')


def verify_token(token):
    """验证JWT Token，返回user_id"""
    try:
        payload = jwt.decode(token, app.config['JWT_SECRET'], algorithms=['HS256'])
        return payload.get('user_id')
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def token_required(f):
    """JWT认证装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]

        if not token:
            return jsonify({"success": False, "message": "缺少认证Token"}), 401

        user_id = verify_token(token)
        if user_id is None:
            return jsonify({"success": False, "message": "Token无效或已过期，请重新登录"}), 401

        current_user = User.query.get(user_id)
        if not current_user:
            return jsonify({"success": False, "message": "用户不存在"}), 401

        return f(current_user, *args, **kwargs)
    return decorated


def admin_required(f):
    """管理员认证装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'admin_user' not in session:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────
# 邮件发送
# ─────────────────────────────────────────────
def send_email(to_email, subject, body, is_html=False):
    """发送邮件（在后台线程中执行）"""
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = to_email
        msg['Subject'] = subject
        content_type = 'html' if is_html else 'plain'
        msg.attach(MIMEText(body, content_type, 'utf-8'))

        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"[邮件错误] 发送到 {to_email}: {e}")
        return False


def send_verification_code_email(email, code, purpose="注册"):
    """发送验证码邮件"""
    subject = f"【禹算】{purpose}验证码"
    body = f"""您好！

您正在进行禹算{purpose}操作，验证码为：{code}

验证码5分钟内有效，请勿泄露给他人。

如非本人操作，请忽略此邮件。
"""
    threading.Thread(target=send_email, args=(email, subject, body)).start()


def send_order_notification(order, user):
    """发送订单通知邮件给开发者"""
    subject = f"【禹算】新订单 - {order.plan_name}（¥{order.price}）"
    body = f"""新订单通知：

套餐：{order.plan_name}
价格：¥{order.price}
支付方式：{order.payment_method}
用户：{user.username}（{user.email}）
时间：{order.created_at.strftime('%Y-%m-%d %H:%M:%S')}

请登录管理后台处理此订单。
"""
    threading.Thread(target=send_email, args=(DEVELOPER_EMAIL, subject, body)).start()


# ─────────────────────────────────────────────
# API 接口
# ─────────────────────────────────────────────

# ---------- 健康检查 ----------
@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "version": "1.0.0", "server_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")})


# ---------- 发送注册验证码 ----------
@app.route('/api/send-code', methods=['POST'])
def api_send_code():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "请求数据为空"}), 400

    email = data.get('email', '').strip()
    if not email or '@' not in email:
        return jsonify({"success": False, "message": "邮箱格式不正确"}), 400

    # 检查邮箱是否已注册
    if User.query.filter_by(email=email).first():
        return jsonify({"success": False, "message": "该邮箱已注册"}), 400

    # 检查发送频率（60秒内只能发一次）
    recent = EmailVerification.query.filter(
        EmailVerification.email == email,
        EmailVerification.created_at > datetime.utcnow() - timedelta(seconds=60)
    ).first()
    if recent:
        return jsonify({"success": False, "message": "发送过于频繁，请60秒后重试"}), 429

    # 生成6位验证码
    code = f"{random.randint(0, 999999):06d}"
    verification = EmailVerification(
        email=email,
        code=code,
        expires_at=datetime.utcnow() + timedelta(minutes=5),
    )
    db.session.add(verification)
    db.session.commit()

    # 发送邮件
    send_verification_code_email(email, code, purpose="注册")

    return jsonify({"success": True, "message": "验证码已发送"})


# ---------- 发送重置密码验证码 ----------
@app.route('/api/send-reset-code', methods=['POST'])
def api_send_reset_code():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "请求数据为空"}), 400

    email = data.get('email', '').strip()
    if not email or '@' not in email:
        return jsonify({"success": False, "message": "邮箱格式不正确"}), 400

    # 检查邮箱是否已注册（重置密码需要邮箱已注册）
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"success": False, "message": "该邮箱未注册"}), 404

    # 检查发送频率（60秒内只能发一次）
    recent = EmailVerification.query.filter(
        EmailVerification.email == email,
        EmailVerification.created_at > datetime.utcnow() - timedelta(seconds=60)
    ).first()
    if recent:
        return jsonify({"success": False, "message": "发送过于频繁，请60秒后重试"}), 429

    # 生成6位验证码
    code = f"{random.randint(0, 999999):06d}"
    verification = EmailVerification(
        email=email,
        code=code,
        purpose='reset_password',
        expires_at=datetime.utcnow() + timedelta(minutes=5),
    )
    db.session.add(verification)
    db.session.commit()

    # 发送邮件
    send_verification_code_email(email, code, purpose="重置密码")

    return jsonify({"success": True, "message": "验证码已发送"})


# ---------- 重置密码 ----------
@app.route('/api/reset-password', methods=['POST'])
def api_reset_password():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "请求数据为空"}), 400

    email = data.get('email', '').strip()
    code = data.get('code', '').strip()
    new_password = data.get('new_password', '')

    if not all([email, code, new_password]):
        return jsonify({"success": False, "message": "请填写所有字段"}), 400
    if len(new_password) < 4:
        return jsonify({"success": False, "message": "新密码至少4个字符"}), 400

    # 查找用户
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"success": False, "message": "该邮箱未注册"}), 404

    # 验证验证码（支持reset_password用途）
    verification = EmailVerification.query.filter(
        EmailVerification.email == email,
        EmailVerification.code == code,
        EmailVerification.is_used == False,
    ).order_by(EmailVerification.created_at.desc()).first()

    if not verification:
        return jsonify({"success": False, "message": "验证码不正确"}), 400
    if verification.expires_at < datetime.utcnow():
        return jsonify({"success": False, "message": "验证码已过期"}), 400

    # 更新密码
    user.set_password(new_password)
    verification.is_used = True
    db.session.commit()

    return jsonify({"success": True, "message": "密码重置成功"})


# ---------- 注册 ----------
@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "请求数据为空"}), 400

    email = data.get('email', '').strip()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    code = data.get('code', '').strip()

    # 参数验证
    if not all([email, username, password, code]):
        return jsonify({"success": False, "message": "请填写所有字段"}), 400
    if len(username) < 2:
        return jsonify({"success": False, "message": "用户名至少2个字符"}), 400
    if len(password) < 4:
        return jsonify({"success": False, "message": "密码至少4个字符"}), 400

    # 验证邮箱验证码（注册用途）
    verification = EmailVerification.query.filter_by(
        email=email, code=code, purpose='register', is_used=False
    ).order_by(EmailVerification.created_at.desc()).first()

    if not verification:
        return jsonify({"success": False, "message": "验证码不正确"}), 400
    if verification.expires_at < datetime.utcnow():
        return jsonify({"success": False, "message": "验证码已过期"}), 400

    # 检查用户名和邮箱唯一性
    if User.query.filter_by(username=username).first():
        return jsonify({"success": False, "message": "用户名已被占用"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"success": False, "message": "该邮箱已注册"}), 400

    # 创建用户
    user = User(
        username=username,
        email=email,
        trial_start=datetime.utcnow(),  # 注册即开始试用
    )
    user.set_password(password)
    db.session.add(user)

    # 标记验证码已使用
    verification.is_used = True
    db.session.commit()

    # 生成Token
    token = generate_token(user.id)

    return jsonify({
        "success": True,
        "message": "注册成功",
        "token": token,
        "user": user.to_dict(),
    })


# ---------- 登录 ----------
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "请求数据为空"}), 400

    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({"success": False, "message": "请输入用户名和密码"}), 400

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({"success": False, "message": "用户名或密码错误"}), 401

    if not user.is_active_user:
        return jsonify({"success": False, "message": "账户已被禁用"}), 403

    # 更新最后登录时间
    user.last_login = datetime.utcnow()
    db.session.commit()

    # 生成Token
    token = generate_token(user.id)

    return jsonify({
        "success": True,
        "message": "登录成功",
        "token": token,
        "user": user.to_dict(),
    })


# ---------- 获取会员状态 ----------
@app.route('/api/membership', methods=['GET'])
@token_required
def api_get_membership(current_user):
    info = current_user.get_membership_info()
    return jsonify({
        "success": True,
        "membership": info,
        "user": current_user.to_dict(),
    })


# ---------- 验证激活码 ----------
@app.route('/api/verify-code', methods=['POST'])
def api_verify_activation_code():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "请求数据为空"}), 400

    code = data.get('code', '').strip().upper()
    if not code:
        return jsonify({"success": False, "message": "请输入激活码"}), 400

    ac = ActivationCode.verify_code(code)
    if not ac:
        return jsonify({"success": False, "message": "激活码无效"}), 400

    return jsonify({
        "success": True,
        "code_info": {
            "plan_name": ac.plan_name,
            "days": ac.days,
            "is_used": ac.is_used if ac.id else False,
        }
    })


# ---------- 激活会员 ----------
@app.route('/api/activate', methods=['POST'])
@token_required
def api_activate(current_user):
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "请求数据为空"}), 400

    code = data.get('code', '').strip().upper()
    if not code:
        return jsonify({"success": False, "message": "请输入激活码"}), 400

    # 验证激活码
    ac = ActivationCode.verify_code(code)
    if not ac:
        return jsonify({"success": False, "message": "激活码无效"}), 400

    # 检查是否已被使用（仅对数据库中已记录的激活码检查）
    if ac.id and ac.is_used:
        return jsonify({"success": False, "message": "该激活码已被使用"}), 400

    # 激活会员
    current_user.activate_membership(ac.plan_index)

    # 如果是数据库中的激活码，标记为已使用
    if ac.id:
        ac.is_used = True
        ac.used_by_user_id = current_user.id
        ac.used_at = datetime.utcnow()
    else:
        # 动态生成的激活码，保存到数据库
        new_ac = ActivationCode(
            code=code,
            plan_index=ac.plan_index,
            plan_name=ac.plan_name,
            days=ac.days,
            is_used=True,
            used_by_user_id=current_user.id,
            used_at=datetime.utcnow(),
        )
        db.session.add(new_ac)

    db.session.commit()

    info = current_user.get_membership_info()
    return jsonify({
        "success": True,
        "message": f"成功激活 {ac.plan_name}",
        "membership": info,
    })


# ---------- 提交订单 ----------
@app.route('/api/order', methods=['POST'])
@token_required
def api_create_order(current_user):
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "请求数据为空"}), 400

    plan_index = data.get('plan_index')
    payment_method = data.get('payment_method', 'wechat')

    if plan_index is None or plan_index < 0 or plan_index >= len(MEMBERSHIP_PLANS):
        return jsonify({"success": False, "message": "无效的套餐"}), 400

    plan = MEMBERSHIP_PLANS[plan_index]
    order = Order(
        user_id=current_user.id,
        plan_name=plan["name"],
        plan_index=plan_index,
        price=plan["price"],
        payment_method=payment_method,
        status='pending',
    )
    db.session.add(order)
    db.session.commit()

    # 发送通知邮件
    send_order_notification(order, current_user)

    return jsonify({
        "success": True,
        "message": "订单已提交",
        "order": order.to_dict(),
    })


# ---------- 修改密码 ----------
@app.route('/api/change-password', methods=['POST'])
@token_required
def api_change_password(current_user):
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "请求数据为空"}), 400

    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')

    if not old_password or not new_password:
        return jsonify({"success": False, "message": "请输入原密码和新密码"}), 400
    if len(new_password) < 4:
        return jsonify({"success": False, "message": "新密码至少4个字符"}), 400
    if not current_user.check_password(old_password):
        return jsonify({"success": False, "message": "原密码错误"}), 400

    current_user.set_password(new_password)
    db.session.commit()

    return jsonify({"success": True, "message": "密码修改成功"})


# ---------- 获取套餐列表 ----------
@app.route('/api/plans', methods=['GET'])
def api_get_plans():
    return jsonify({
        "success": True,
        "plans": MEMBERSHIP_PLANS,
        "trial_days": TRIAL_DAYS,
    })


# ─────────────────────────────────────────────
# 管理后台
# ─────────────────────────────────────────────
@app.route('/admin')
def admin_index():
    if 'admin_user' not in session:
        return redirect(url_for('admin_login'))
    # 仪表盘数据
    total_users = User.query.count()
    total_members = User.query.filter_by(is_member=True).count()
    total_permanent = User.query.filter_by(is_permanent=True).count()
    total_orders = Order.query.count()
    total_revenue = db.session.query(db.func.sum(Order.price)).filter(
        Order.status == 'paid'
    ).scalar() or 0
    pending_orders = Order.query.filter_by(status='pending').count()
    recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(10).all()

    return render_template('admin/dashboard.html',
        total_users=total_users,
        total_members=total_members,
        total_permanent=total_permanent,
        total_orders=total_orders,
        total_revenue=total_revenue,
        pending_orders=pending_orders,
        recent_users=recent_users,
        recent_orders=recent_orders,
    )


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')

        # 检查管理员账户
        admin = User.query.filter_by(username=username, is_admin=True).first()
        if admin and admin.check_password(password):
            session['admin_user'] = admin.username
            session['admin_id'] = admin.id
            return redirect(url_for('admin_index'))

        # 默认管理员账户
        if username == 'admin' and password == ADMIN_DEFAULT_PASSWORD:
            # 自动创建管理员用户
            admin = User.query.filter_by(username='admin').first()
            if not admin:
                admin = User(username='admin', email='admin@yusuan.local', is_admin=True)
                admin.set_password(password)
                db.session.add(admin)
                db.session.commit()
            session['admin_user'] = 'admin'
            session['admin_id'] = admin.id
            return redirect(url_for('admin_index'))

        return render_template('admin/login.html', error="用户名或密码错误")

    return render_template('admin/login.html', error=None)


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_user', None)
    session.pop('admin_id', None)
    return redirect(url_for('admin_login'))


# ---------- 管理后台：用户管理 ----------
@app.route('/admin/users')
@admin_required
def admin_users():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '').strip()
    query = User.query
    if search:
        query = query.filter(
            db.or_(
                User.username.contains(search),
                User.email.contains(search),
            )
        )
    users = query.order_by(User.created_at.desc()).paginate(page=page, per_page=20)
    return render_template('admin/users.html', users=users, search=search)


@app.route('/admin/users/<int:user_id>/toggle', methods=['POST'])
@admin_required
def admin_toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.username == 'admin':
        return jsonify({"success": False, "message": "不能禁用管理员账户"}), 400
    user.is_active_user = not user.is_active_user
    db.session.commit()
    status = "启用" if user.is_active_user else "禁用"
    return jsonify({"success": True, "message": f"已{status}用户 {user.username}"})


@app.route('/admin/users/<int:user_id>/reset-password', methods=['POST'])
@admin_required
def admin_reset_password(user_id):
    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password', '123456')
    user.set_password(new_password)
    db.session.commit()
    return jsonify({"success": True, "message": f"已重置 {user.username} 的密码"})


@app.route('/admin/users/<int:user_id>/set-member', methods=['POST'])
@admin_required
def admin_set_member(user_id):
    user = User.query.get_or_404(user_id)
    plan_index = request.form.get('plan_index', type=int)
    if plan_index is not None and 0 <= plan_index < len(MEMBERSHIP_PLANS):
        user.activate_membership(plan_index)
        db.session.commit()
        return jsonify({"success": True, "message": f"已设置 {user.username} 为 {MEMBERSHIP_PLANS[plan_index]['name']}"})
    return jsonify({"success": False, "message": "无效的套餐"}), 400


# ---------- 管理后台：激活码管理 ----------
@app.route('/admin/codes')
@admin_required
def admin_codes():
    page = request.args.get('page', 1, type=int)
    codes = ActivationCode.query.order_by(ActivationCode.created_at.desc()).paginate(
        page=page, per_page=30
    )
    return render_template('admin/codes.html', codes=codes, plans=MEMBERSHIP_PLANS)


@app.route('/admin/codes/generate', methods=['POST'])
@admin_required
def admin_generate_codes():
    plan_index = request.form.get('plan_index', type=int)
    count = request.form.get('count', 1, type=int)
    note = request.form.get('note', '')

    if plan_index is None or plan_index < 0 or plan_index >= len(MEMBERSHIP_PLANS):
        return jsonify({"success": False, "message": "无效的套餐"}), 400
    if count < 1 or count > 100:
        return jsonify({"success": False, "message": "生成数量1-100"}), 400

    plan = MEMBERSHIP_PLANS[plan_index]
    generated = []

    # 找到当前套餐最大的serial，避免重复
    for serial in range(1000):
        code = ActivationCode.generate_code(plan_index, serial)
        if not ActivationCode.query.filter_by(code=code).first():
            ac = ActivationCode(
                code=code,
                plan_index=plan_index,
                plan_name=plan["name"],
                days=plan["days"],
                note=note,
            )
            db.session.add(ac)
            generated.append(code)
            if len(generated) >= count:
                break

    db.session.commit()
    return jsonify({
        "success": True,
        "message": f"已生成 {len(generated)} 个激活码",
        "codes": generated,
    })


@app.route('/admin/codes/<int:code_id>/delete', methods=['POST'])
@admin_required
def admin_delete_code(code_id):
    code = ActivationCode.query.get_or_404(code_id)
    if code.is_used:
        return jsonify({"success": False, "message": "已使用的激活码不能删除"}), 400
    db.session.delete(code)
    db.session.commit()
    return jsonify({"success": True, "message": "已删除"})


# ---------- 管理后台：订单管理 ----------
@app.route('/admin/orders')
@admin_required
def admin_orders():
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', '')
    query = Order.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    orders = query.order_by(Order.created_at.desc()).paginate(page=page, per_page=20)
    return render_template('admin/orders.html', orders=orders, status_filter=status_filter)


@app.route('/admin/orders/<int:order_id>/confirm', methods=['POST'])
@admin_required
def admin_confirm_order(order_id):
    order = Order.query.get_or_404(order_id)
    if order.status == 'paid':
        return jsonify({"success": False, "message": "订单已确认"}), 400

    order.status = 'paid'
    order.paid_at = datetime.utcnow()

    # 自动激活会员
    user = User.query.get(order.user_id)
    if user:
        user.activate_membership(order.plan_index)

    db.session.commit()
    return jsonify({"success": True, "message": "订单已确认，会员已激活"})


@app.route('/admin/orders/<int:order_id>/cancel', methods=['POST'])
@admin_required
def admin_cancel_order(order_id):
    order = Order.query.get_or_404(order_id)
    order.status = 'cancelled'
    db.session.commit()
    return jsonify({"success": True, "message": "订单已取消"})


# ─────────────────────────────────────────────
# 数据库初始化
# ─────────────────────────────────────────────
def init_db():
    """创建所有表并初始化默认管理员"""
    with app.app_context():
        db.create_all()
        # 创建默认管理员
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                email='admin@yusuan.local',
                is_admin=True,
            )
            admin.set_password(ADMIN_DEFAULT_PASSWORD)
            db.session.add(admin)
            db.session.commit()
            print("[初始化] 管理员账户已创建: admin / " + ADMIN_DEFAULT_PASSWORD)
        print("[初始化] 数据库就绪")


# ─────────────────────────────────────────────
# 启动入口
# ─────────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
