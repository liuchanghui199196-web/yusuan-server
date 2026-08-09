"""
禹算客户端API模块
集成到桌面客户端，与服务端通信
用法：from yusuan_api import YuSuanAPI
"""
import json
import os
import hashlib
import threading
from datetime import datetime

try:
    import requests
except ImportError:
    requests = None

# ─────────────────────────────────────────────
# 服务端地址（部署后替换为实际URL）
# ─────────────────────────────────────────────
SERVER_URL = os.environ.get('YUSUAN_SERVER', 'http://154.8.149.148')

# 本地Token存储路径
_TOKEN_PATH = os.path.join(os.environ.get('APPDATA', '.'), '禹算', 'api_token.json')


class YuSuanAPI:
    """禹算服务端API客户端"""

    def __init__(self, server_url=None):
        self.server_url = (server_url or SERVER_URL).rstrip('/')
        self._token = None
        self._user = None
        self._load_token()

    # ─────────────────────────────────────────
    # Token 持久化
    # ─────────────────────────────────────────
    def _load_token(self):
        """从本地文件加载Token"""
        try:
            if os.path.exists(_TOKEN_PATH):
                with open(_TOKEN_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._token = data.get('token')
                    self._user = data.get('user')
        except Exception:
            pass

    def _save_token(self, token, user):
        """保存Token到本地文件"""
        self._token = token
        self._user = user
        try:
            os.makedirs(os.path.dirname(_TOKEN_PATH), exist_ok=True)
            with open(_TOKEN_PATH, 'w', encoding='utf-8') as f:
                json.dump({'token': token, 'user': user}, f, ensure_ascii=False)
        except Exception:
            pass

    def _clear_token(self):
        """清除本地Token"""
        self._token = None
        self._user = None
        try:
            if os.path.exists(_TOKEN_PATH):
                os.remove(_TOKEN_PATH)
        except Exception:
            pass

    # ─────────────────────────────────────────
    # HTTP 请求工具
    # ─────────────────────────────────────────
    def _headers(self, auth=False):
        """构造请求头"""
        h = {'Content-Type': 'application/json'}
        if auth and self._token:
            h['Authorization'] = f'Bearer {self._token}'
        return h

    def _request(self, method, path, data=None, auth=False):
        """
        发送HTTP请求
        返回: (success: bool, result: dict)
        """
        if requests is None:
            return False, {"message": "缺少requests库，请运行: pip install requests"}

        url = f"{self.server_url}{path}"
        try:
            if method == 'GET':
                resp = requests.get(url, headers=self._headers(auth), timeout=10)
            else:
                resp = requests.post(url, json=data, headers=self._headers(auth), timeout=10)

            result = resp.json()

            # Token过期，清除本地登录状态
            if resp.status_code == 401:
                self._clear_token()

            return result.get('success', False), result

        except requests.exceptions.ConnectionError:
            return False, {"message": "无法连接服务器，请检查网络连接"}
        except requests.exceptions.Timeout:
            return False, {"message": "服务器响应超时，请稍后重试"}
        except Exception as e:
            return False, {"message": f"请求失败: {str(e)}"}

    # ─────────────────────────────────────────
    # 公开API方法
    # ─────────────────────────────────────────
    def check_server(self):
        """检查服务器是否可用"""
        try:
            success, data = self._request('GET', '/api/health')
            return success
        except Exception:
            return False

    def get_plans(self):
        """获取会员套餐列表"""
        success, data = self._request('GET', '/api/plans')
        if success:
            return data.get('plans', []), data.get('trial_days', 5)
        return [], 5

    def send_verification_code(self, email):
        """发送注册验证码"""
        return self._request('POST', '/api/send-code', {'email': email})

    def register(self, email, username, password, code):
        """
        注册账户
        返回: (success, data)  data包含token和user信息
        """
        success, data = self._request('POST', '/api/register', {
            'email': email,
            'username': username,
            'password': password,
            'code': code,
        })
        if success:
            self._save_token(data.get('token', ''), data.get('user', {}))
        return success, data

    def login(self, username, password):
        """
        登录
        返回: (success, data)  data包含token和user信息
        """
        success, data = self._request('POST', '/api/login', {
            'username': username,
            'password': password,
        })
        if success:
            self._save_token(data.get('token', ''), data.get('user', {}))
        return success, data

    def logout(self):
        """退出登录（清除本地Token）"""
        self._clear_token()

    @property
    def is_logged_in(self):
        """是否已登录"""
        return self._token is not None

    @property
    def current_user(self):
        """当前登录用户信息"""
        return self._user

    def get_membership(self):
        """
        获取会员状态
        返回: (success, membership_info_dict)
        """
        success, data = self._request('GET', '/api/membership', auth=True)
        if success:
            # 更新本地用户信息
            user = data.get('user')
            if user:
                self._save_token(self._token, user)
            return True, data.get('membership', {})
        return False, {}

    def verify_activation_code(self, code):
        """
        验证激活码
        返回: (success, code_info_dict)
        """
        return self._request('POST', '/api/verify-code', {'code': code})

    def activate_membership(self, code):
        """
        使用激活码激活会员
        返回: (success, data)
        """
        success, data = self._request('POST', '/api/activate', {'code': code}, auth=True)
        if success:
            # 更新本地用户信息
            membership = data.get('membership', {})
            if self._user:
                self._user['is_member'] = membership.get('is_member', False)
                self._user['is_permanent'] = membership.get('is_permanent', False)
                self._user['membership_plan'] = membership.get('plan_name')
                self._user['membership_expiry'] = membership.get('expiry_date')
                self._save_token(self._token, self._user)
        return success, data

    def create_order(self, plan_index, payment_method='wechat'):
        """
        提交订单
        返回: (success, order_dict)
        """
        return self._request('POST', '/api/order', {
            'plan_index': plan_index,
            'payment_method': payment_method,
        }, auth=True)

    def change_password(self, old_password, new_password):
        """修改密码"""
        return self._request('POST', '/api/change-password', {
            'old_password': old_password,
            'new_password': new_password,
        }, auth=True)


# ─────────────────────────────────────────────
# 全局单例（方便客户端直接使用）
# ─────────────────────────────────────────────
_api_instance = None

def get_api():
    """获取全局API实例"""
    global _api_instance
    if _api_instance is None:
        _api_instance = YuSuanAPI()
    return _api_instance
