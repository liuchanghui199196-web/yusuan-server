"""
禹算服务端 - 数据库模型
用户表、激活码表、订单表
"""
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import hashlib
import json

db = SQLAlchemy()

# ─────────────────────────────────────────────
# 会员套餐配置（与客户端保持一致）
# ─────────────────────────────────────────────
MEMBERSHIP_PLANS = [
    {"name": "5天会员",    "days": 5,   "price": 5},
    {"name": "1个月会员",  "days": 30,  "price": 30},
    {"name": "3个月会员",  "days": 90,  "price": 81},
    {"name": "6个月会员",  "days": 180, "price": 153},
    {"name": "1年会员",    "days": 365, "price": 288},
    {"name": "2年会员",    "days": 730, "price": 540},
    {"name": "永久会员",   "days": -1,  "price": 702},
]
TRIAL_DAYS = 5
ACTIVATION_SECRET = "YuSuan2024Membership"


# ─────────────────────────────────────────────
# 用户表
# ─────────────────────────────────────────────
class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    is_member = db.Column(db.Boolean, default=False)
    is_permanent = db.Column(db.Boolean, default=False)
    membership_expiry = db.Column(db.DateTime, nullable=True)
    membership_plan = db.Column(db.String(50), nullable=True)
    activated_at = db.Column(db.DateTime, nullable=True)  # 会员激活时间
    trial_start = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    is_active_user = db.Column(db.Boolean, default=True)  # 账户是否可用

    # 关联订单
    orders = db.relationship('Order', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_trial_days_remaining(self):
        """计算试用剩余天数"""
        if not self.trial_start:
            return TRIAL_DAYS
        elapsed = (datetime.utcnow() - self.trial_start).days
        return max(0, TRIAL_DAYS - elapsed)

    def get_membership_info(self):
        """获取会员状态信息"""
        if self.is_permanent:
            return {
                "is_member": True,
                "is_permanent": True,
                "plan_name": "永久会员",
                "expiry_date": None,
                "trial_days_remaining": None,
            }
        if self.is_member and self.membership_expiry:
            if self.membership_expiry > datetime.utcnow():
                return {
                    "is_member": True,
                    "is_permanent": False,
                    "plan_name": self.membership_plan or "",
                    "expiry_date": self.membership_expiry.strftime("%Y-%m-%d %H:%M:%S"),
                    "trial_days_remaining": None,
                }
            else:
                # 会员已过期
                return {
                    "is_member": False,
                    "is_permanent": False,
                    "plan_name": self.membership_plan or "",
                    "expiry_date": self.membership_expiry.strftime("%Y-%m-%d %H:%M:%S"),
                    "trial_days_remaining": self.get_trial_days_remaining(),
                }
        return {
            "is_member": False,
            "is_permanent": False,
            "plan_name": None,
            "expiry_date": None,
            "trial_days_remaining": self.get_trial_days_remaining(),
        }

    def activate_membership(self, plan_index):
        """激活会员"""
        if plan_index < 0 or plan_index >= len(MEMBERSHIP_PLANS):
            return False
        plan = MEMBERSHIP_PLANS[plan_index]
        self.membership_plan = plan["name"]
        self.activated_at = datetime.utcnow()

        if plan["days"] == -1:
            # 永久会员
            self.is_permanent = True
            self.is_member = True
            self.membership_expiry = None
        else:
            # 限时会员
            self.is_permanent = False
            self.is_member = True
            # 计算试用剩余天数（未过期时叠加到会员期限）
            trial_remaining = self.get_trial_days_remaining()
            total_days = plan["days"] + trial_remaining
            if self.membership_expiry and self.membership_expiry > datetime.utcnow():
                # 续费：在现有到期时间基础上延长
                self.membership_expiry = self.membership_expiry + timedelta(days=plan["days"])
            else:
                # 新购/已过期：从当前时间开始（含试用剩余天数）
                self.membership_expiry = datetime.utcnow() + timedelta(days=total_days)
        return True

    def to_dict(self):
        """序列化为字典（不含敏感信息）"""
        info = self.get_membership_info()
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "last_login": self.last_login.strftime("%Y-%m-%d %H:%M:%S") if self.last_login else None,
            "is_member": info["is_member"],
            "is_permanent": info["is_permanent"],
            "membership_plan": info["plan_name"],
            "membership_expiry": info["expiry_date"],
            "trial_days_remaining": info["trial_days_remaining"],
        }

    def __repr__(self):
        return f'<User {self.username}>'


# ─────────────────────────────────────────────
# 激活码表
# ─────────────────────────────────────────────
class ActivationCode(db.Model):
    __tablename__ = 'activation_codes'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(19), unique=True, nullable=False, index=True)
    plan_index = db.Column(db.Integer, nullable=False)
    plan_name = db.Column(db.String(50), nullable=False)
    days = db.Column(db.Integer, nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    used_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    note = db.Column(db.String(200), nullable=True)  # 管理员备注

    used_by = db.relationship('User', backref='used_codes')

    @staticmethod
    def generate_code(plan_index, serial):
        """生成激活码（与客户端算法一致）"""
        if plan_index < 0 or plan_index >= len(MEMBERSHIP_PLANS):
            return None
        plan = MEMBERSHIP_PLANS[plan_index]
        data = {
            "plan": plan["name"],
            "days": plan["days"],
            "secret": ACTIVATION_SECRET,
            "serial": serial,
        }
        json_str = json.dumps(data, sort_keys=True)
        hash_hex = hashlib.sha256(json_str.encode()).hexdigest()[:16]
        code = f"{hash_hex[:4]}-{hash_hex[4:8]}-{hash_hex[8:12]}-{hash_hex[12:16]}"
        return code.upper()

    @staticmethod
    def verify_code(code):
        """
        验证激活码：先查数据库，如果数据库有记录则直接返回；
        否则遍历所有套餐×1000序列号匹配。
        """
        code = code.strip().upper()
        # 优先查数据库
        ac = ActivationCode.query.filter_by(code=code).first()
        if ac:
            return ac

        # 数据库没有，遍历算法匹配
        for pi, plan in enumerate(MEMBERSHIP_PLANS):
            for serial in range(1000):
                generated = ActivationCode.generate_code(pi, serial)
                if generated == code:
                    # 动态创建（不保存到数据库，仅返回信息）
                    ac = ActivationCode(
                        code=code,
                        plan_index=pi,
                        plan_name=plan["name"],
                        days=plan["days"],
                    )
                    return ac
        return None

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "plan_index": self.plan_index,
            "plan_name": self.plan_name,
            "days": self.days,
            "is_used": self.is_used,
            "used_by_username": self.used_by.username if self.used_by else None,
            "used_at": self.used_at.strftime("%Y-%m-%d %H:%M:%S") if self.used_at else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "note": self.note,
        }

    def __repr__(self):
        return f'<ActivationCode {self.code}>'


# ─────────────────────────────────────────────
# 订单表
# ─────────────────────────────────────────────
class Order(db.Model):
    __tablename__ = 'orders'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    plan_name = db.Column(db.String(50), nullable=False)
    plan_index = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(20), nullable=False)  # wechat / alipay
    status = db.Column(db.String(20), default='pending')  # pending / paid / cancelled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)
    note = db.Column(db.String(200), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.user.username if self.user else None,
            "plan_name": self.plan_name,
            "price": self.price,
            "payment_method": self.payment_method,
            "status": self.status,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "paid_at": self.paid_at.strftime("%Y-%m-%d %H:%M:%S") if self.paid_at else None,
            "note": self.note,
        }

    def __repr__(self):
        return f'<Order {self.id} - {self.plan_name}>'


# ─────────────────────────────────────────────
# 邮箱验证码表（用于注册验证）
# ─────────────────────────────────────────────
class EmailVerification(db.Model):
    __tablename__ = 'email_verifications'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, index=True)
    code = db.Column(db.String(6), nullable=False)
    purpose = db.Column(db.String(20), default='register')  # register / reset_password
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_used = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<EmailVerification {self.email}>'
