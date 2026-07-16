# -*- coding: utf-8 -*-
#  Copyright (C) 2026 FjiNeko
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#  You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.


# 导入环境变量
from dotenv import load_dotenv
load_dotenv() 


# 引入必要的库
import datetime
from datetime import datetime as dt
import jwt
import time
import string
import os
import requests
from functools import wraps
import logging
import json
import redis
import subprocess
from flask import Flask, request, jsonify, g, make_response, after_this_request, send_from_directory, redirect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from datetime import timedelta, timezone 
import uuid
from PIL import Image, ImageDraw, ImageFont # 生成验证码照片 和 图片处理
import base64
import random
import io
import hashlib 
import requests
from bs4 import BeautifulSoup
import re



# 引入自编库
from .translation import translate_with_chatgpt
from .db import fetch_user_db, execute_user_db, close_user_db_connection
from .utils.id import format_sequential_uid
from .utils.hash import hash_password, check_password
from .utils.response import success, error
from .utils.email_utils import send_password_reset_email

######################################
#                                    #
#          初始化结构与实例           #
#                                    #
######################################
# 色池
AESTHETIC_GRADIENTS = [
    ((17, 24, 39), (75, 85, 99)),     # 深空灰色
    ((31, 31, 31), (110, 245, 0)),    # 赛博绿色
    ((20, 30, 48), (36, 59, 85)),     # 深邃蓝色
    ((67, 67, 67), (0, 0, 0)),        # 金属黑色
    ((15, 32, 39), (32, 58, 67)),     # 深空色
    ((55, 59, 68), (66, 134, 244)),   # 蓝灰色
    ((29, 29, 29), (195, 55, 100)),   # 暗粉色
    ((0, 0, 0), (67, 67, 67)),        # 黑曜石色
    ((89, 92, 104), (33, 33, 33)),    # 碳纤维色
]

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

# 获取密钥与过期时间
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
app.config['SECRET_KEY'] = SECRET_KEY 
app.config['JWT_ACCESS_TOKEN_EXPIRES_HOURS'] = int(os.getenv('JWT_ACCESS_TOKEN_EXPIRES_HOURS', 24))

# Redis连接初始化
REDIS_HOST = os.getenv('REDIS_HOST')
REDIS_PORT = os.getenv('REDIS_PORT')
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)


# 初始化Flask-Limiter
# 默认使用内存存储
limiter_storage = "memory://" 
limiter = Limiter(
    get_remote_address,
    app=app,
    storage_uri=limiter_storage,
    strategy="moving-window"
)

redis_client = None # 默认为空
try:
    # 初始化连接
    test_client = redis.StrictRedis(
        host=REDIS_HOST, 
        port=REDIS_PORT, 
        password=REDIS_PASSWORD, 
        db=0, 
        socket_timeout=1, 
        decode_responses=True
    )
    
    if test_client.ping():
        redis_client = test_client
        # 构建 Flask-Limiter 的连接字符串
        if REDIS_PASSWORD:
            # 有密码格式: redis://:密码@地址:端口
            limiter_storage = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}"
        else:
            # 无密码格式: redis://地址:端口
            limiter_storage = f"redis://{REDIS_HOST}:{REDIS_PORT}"
            
        logger.info(f"Redis connected successfully on port {REDIS_PORT}.")
except Exception as e:
    logger.warning(f"Redis connection failed: {e}. Falling back to MEMORY mode.")
    redis_client = None

######################################
#                                    #
#       测试连通性、配置跨域           #
#                                    #
######################################
CORS(app, resources={r"/api/*": {"origins": [
    "https://cgbgear.cn",
], "supports_credentials": True, "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"]}})

# 测试CORS配置和后端连通性路由
@app.route('/api/test/cors', methods=['GET'])
def test_cors():
    logger.info("CORS test endpoint called.")
    test_data = {
        "status": "success",
        "message": "CORS test successful!",
        "your_origin": request.headers.get('Origin', 'Unknown (No Origin Header)'),
        "backend_time": datetime.datetime.now(timezone.utc).isoformat()
    }
    try:
        user_count_data = fetch_user_db("SELECT COUNT(id) AS count FROM users", one=True)
        test_data['db_connection_status'] = "success"
        test_data['total_users_in_db'] = user_count_data['count'] if user_count_data else 0
    except Exception as e:
        test_data['db_connection_status'] = f"failed: {str(e)}"
        test_data['total_users_in_db'] = -1
        logger.error(f"Error connecting to DB in /api/test/cors: {e}", exc_info=True)
    logger.debug(f"Responding to /api/test/cors with data: {test_data}")
    return success(test_data)



# 确保在请求结束时关闭数据库连接
app.teardown_appcontext(close_user_db_connection)


######################################
#                                    #
#    图片处理配置、辅助函数 PHOTOS     #
#                                    #
######################################

# 图片存储物理根路径
IMG_ROOT_PATH = os.getenv('IMG_ROOT_PATH')
# 图片访问基础 URL
IMAGE_SERVER_BASE_URL = os.getenv('IMAGE_SERVER_BASE_URL')
# 确保目录存在
DEFAULT_AVATAR_SUBFOLDER = 'avatars'
for subpath in ['photo', DEFAULT_AVATAR_SUBFOLDER]: # 使用DEFAULT_AVATAR_SUBFOLDER
    full_path = os.path.join(IMG_ROOT_PATH, subpath)
    if not os.path.exists(full_path):
        os.makedirs(full_path, exist_ok=True)
        logger.info(f"Created directory: {full_path}")
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'}
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
def generate_random_filename_26():
    """生成26位随机字母数字字符串"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=26))
def compress_image_to_webp(input_path, output_path):
    """
    使用 FFmpeg 将图片无损压缩为 WebP。
    命令: ffmpeg -i input.jpg -lossless 1 -y output.webp
    """
    try:
        # 构建 FFmpeg 命令 (无损压缩)
        command = [
            'ffmpeg',
            '-i', input_path,
            '-lossless', '1',       # 无损模式
            '-compression_level', '6', # 压缩级别 (0-6)，6最慢但压缩率最好
            '-y',                   # 覆盖输出文件
            output_path
        ]
        
        # 执行命令，捕获输出以便调试
        result = subprocess.run(
            command, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        logger.debug(f"FFmpeg compression successful: {output_path}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Image processing error: {e}")
        return False
def process_upload_workflow(file, target_dir, final_filename_base):
    """
    通用的上传处理流程：保存临时 -> FFmpeg压缩 -> 清理 -> 返回相对路径
    final_filename_base: 不带 .webp 后缀的基础名
    """
    original_ext = file.filename.rsplit('.', 1)[1].lower()
    
    # 1. 保存原始文件 (临时)
    temp_filename = f"temp_{uuid.uuid4().hex}.{original_ext}"
    temp_path = os.path.join(target_dir, temp_filename)
    file.save(temp_path)
    
    # 2. 构建目标文件名 (例如: wrapper.jpg_.webp)
    # 这里的逻辑是：文件名_.webp
    final_filename = f"{final_filename_base}.{original_ext}_.webp"
    final_path = os.path.join(target_dir, final_filename)
    
    # 3. 调用 FFmpeg 压缩
    success = compress_image_to_webp(temp_path, final_path)
    
    # 4. 清理临时文件
    if os.path.exists(temp_path):
        os.remove(temp_path)
        
    if success:
        return final_filename
    else:
        return None

######################################
#                                    #
#       配置日志、用户活动记录         #
#                                    #
######################################
@app.before_request
def log_request_info():
    logger.info(f"Incoming request: {request.method} {request.path} from {request.remote_addr}")
    if request.is_json:
        json_data = request.get_json(silent=True)
        if json_data:
            # 过滤敏感字段
            logged_data = {k: v for k, v in json_data.items() if k not in ['password', 'confirm_password', 'token']} 
            logger.debug(f"Request JSON data: {logged_data}")
        else:
            logger.debug("Request body is not JSON or is empty.")
@app.after_request
def log_response_info(response):
    logger.info(f"Responding to {request.method} {request.path} with status {response.status_code}")
    return response
# IP地理位置查询辅助函数
def get_ip_location(ip_address):
    if ip_address in ('127.0.0.1', 'localhost', '::1'):
        logger.debug(f"IP address {ip_address} is localhost, skipping external lookup.")
        return "Localhost"
    # 修复无法获取归属地问题
    api_url = f"https://ip9.com.cn/get?ip={ip_address}" 
    try:
        # 防止卡死登录接口
        response = requests.get(api_url, timeout=1.5)
        # 检查HTTP协议错误
        response.raise_for_status()
        result = response.json()
        if result.get('ret') == 200 and 'data' in result:
            data = result['data']
            country = data.get('country', '')
            big_area = data.get('big_area', '')
            prov = data.get('prov', '')
            city = data.get('city', '')
            isp = data.get('isp', '')
             # 处理省份/城市逻辑
            if prov == city or city.startswith(prov) or prov.startswith(city):
                location_middle = city
            else:
                location_middle = f"{prov} {city}"
            location_parts = [country, big_area, location_middle, isp]
            location = " ".join([p for p in location_parts if p and p.strip()])
            logger.debug(f"IP location for {ip_address}: {location}")
            return location
        else:
            logger.warning(f"IP location API failed for {ip_address}: {data.get('message', 'Unknown error')}")
            return "Unknown"
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching IP location for {ip_address}: {e}", exc_info=True)
        return "Unknown"
    except Exception as e:
        logger.error(f"Unexpected error in get_ip_location for {ip_address}: {e}", exc_info=True)
        return "Unknown"

def update_last_activity_optimized(user_id):
    """
    优化用户活跃时间更新：
    1. 使用Redis原子锁控制数据库写入频率 (5分钟一次)。
    2. 使用Redis ZSET实时维护在线用户列表。
    """
    now_ts = datetime.datetime.now(timezone.utc).timestamp()
    if not redis_client:
        execute_user_db('UPDATE users SET last_activity = %s WHERE id = %s', 
                        (datetime.datetime.now(timezone.utc), user_id))
        return
    try:
        redis_key_online = "stats:online_users"
        redis_client.zadd(redis_key_online, {str(user_id): now_ts})
    except Exception as e:
        logger.error(f"Redis ZADD failed: {e}")

    cache_key = f"throttle:last_act:{user_id}"
    if redis_client.set(cache_key, "1", ex=300, nx=True):
        execute_user_db('UPDATE users SET last_activity = %s WHERE id = %s', 
                        (datetime.datetime.fromtimestamp(now_ts, timezone.utc), user_id))
        logger.debug(f"DB WRITE: Updated last_activity for user {user_id}")
def increment_view_count_optimized(table_name, id_col, item_id):
    """
    优化浏览量更新（Write-Back策略）
    先在Redis中自增，每累积 10 次浏览，才统一刷入数据库一次。
    """
    if not redis_client:
        execute_user_db(f'UPDATE {table_name} SET view_count = view_count + 1 WHERE {id_col} = %s', (item_id,))
        return 1 # 无法获取准确增加值，返回1
    redis_key = f"buffer:view_count:{table_name}:{item_id}"
    current_buffer = redis_client.incr(redis_key)
    if current_buffer >= 10:
        execute_user_db(f'UPDATE {table_name} SET view_count = view_count + %s WHERE {id_col} = %s', (current_buffer, item_id))
        redis_client.delete(redis_key)
        logger.debug(f"DB WRITE: Flushed {current_buffer} views to {table_name} ID {item_id}")
        return 0 # 缓冲区已清空
    return current_buffer # 返回当前缓冲区的值，用于前端显示修正
def add_activity_log(user_id, activity_type, actor_uid=None, related_id=None, related_type=None, description=None, points_change=0):
    """添加一条活动日志。"""
    if actor_uid is None and hasattr(g, 'uid'):
        actor_uid = g.uid
    execute_user_db(
        """
        INSERT INTO activity_log (user_id, actor_uid, activity_type, related_id, related_type, description, points_change)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (user_id, actor_uid, activity_type, related_id, related_type, description, points_change)
    )
    logger.info(f"Activity logged for user {user_id}: {activity_type} by actor {actor_uid}")

######################################
#                                    #
#       用户接口（登录、注册）         #
#                                    #
######################################
# 强制登录
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        logger.debug(f"login_required decorator activated for endpoint: {request.path}")
        token = request.cookies.get('jwt_token')
        if not token:
            logger.warning(f"Access denied for {request.path}: No token in cookies.")
            response_error = make_response(error("Unauthorized: Token missing.", 401))
            response_error.delete_cookie('jwt_token', path='/', samesite='Lax', secure=not app.debug)
            return response_error
        # 黑名单检查
        if redis_client:
            # Token黑名单Key，通常存储登出时的token签名或完整token
            token_hash = hashlib.md5(token.encode()).hexdigest()
            blacklist_key = f"blacklist:token:{token_hash}"
            if redis_client.exists(blacklist_key):
                logger.warning(f"Access denied: Token is in blacklist.")
                response_error = make_response(error("Unauthorized: You have logged out.", 401))
                response_error.delete_cookie('jwt_token', path='/', samesite='Lax', secure=not app.debug)
                return response_error
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            g.uid = data['uid']
            g.email = data['email']
            logger.info(f"JWT decoded successfully. g.uid: {g.uid}, g.email: {g.email}")
            user_info = fetch_user_db('SELECT id, display_name, role FROM users WHERE uid = %s', (g.uid,), one=True)
            if user_info:
                g.user_id = user_info['id']
                g.username = user_info['display_name']
                g.user_role = user_info['role']
                logger.debug(f"User found in DB for g.uid {g.uid}. User ID: {g.user_id}, Username: {g.username}, Role: {g.user_role}")
                update_last_activity_optimized(g.user_id)
                logger.debug(f"Updated last_activity for user {g.user_id}.")
            else:
                logger.error(f"User NOT found in DB for UID '{g.uid}' extracted from token. Invalidating token.")
                response_error = make_response(error("Unauthorized: User not found for this token.", 401))
                response_error.delete_cookie('jwt_token', path='/', samesite='Lax', secure=not app.debug)
                return response_error
        except jwt.ExpiredSignatureError:
            logger.warning(f"JWT token expired for request to {request.path}. Invalidating token.")
            response_error = make_response(error("Unauthorized: Token has expired. Please log in again.", 401))
            response_error.delete_cookie('jwt_token', path='/', samesite='Lax', secure=not app.debug)
            return response_error
        except jwt.InvalidTokenError:
            logger.warning(f"Invalid JWT token for request to {request.path}. Invalidating token.")
            response_error = make_response(error("Unauthorized: Invalid token. Please log in again.", 401))
            response_error.delete_cookie('jwt_token', path='/', samesite='Lax', secure=not app.debug)
            return response_error
        except Exception as e:
            logger.error(f"Unexpected JWT verification error for {request.path}: {e}", exc_info=True)
            response_error = make_response(error(f"Unauthorized: Token verification error: {str(e)}", 401))
            response_error.delete_cookie('jwt_token', path='/', samesite='Lax', secure=not app.debug)
            return response_error
        return f(*args, **kwargs)
    return decorated_function

# 游客访问
def jwt_optional(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        logger.debug(f"jwt_optional decorator activated for endpoint: {request.path}")  
        g.uid = None
        g.email = None
        g.user_id = None
        g.username = None 
        g.user_role = 'guest' # 默认为游客角色
        token = request.cookies.get('jwt_token')
        if token:
            try:
                data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
                g.uid = data['uid']
                g.email = data['email']
                logger.info(f"JWT (optional) decoded successfully. g.uid: {g.uid}, g.email: {g.email}")
                user_info = fetch_user_db('SELECT id, display_name, role FROM users WHERE uid = %s', (g.uid,), one=True)
                if user_info:
                    g.user_id = user_info['id']
                    g.username = user_info['display_name'] # [修改] 使用 display_name
                    g.user_role = user_info['role']
                    logger.debug(f"User found in DB for g.uid {g.uid}. User ID: {g.user_id}, Username: {g.username}, Role: {g.user_role}")
                    update_last_activity_optimized(g.user_id)
                    logger.debug(f"Updated last_activity for user {g.user_id}.")
                else:
                    logger.warning(f"User NOT found in DB for UID '{g.uid}' extracted from (optional) token. Treating as guest and clearing cookie.")
                    # 如果token有效但用户不存在，也清除cookie
                    @after_this_request
                    def clear_invalid_cookie(response):
                        response.delete_cookie('jwt_token', path='/', samesite='Lax', secure=not app.debug)
                        return response
                    g.uid = None
                    g.email = None
                    g.user_id = None
                    g.username = None
                    g.user_role = 'guest'

            except jwt.ExpiredSignatureError:
                logger.warning(f"JWT (optional) token expired for request to {request.path}. Treating as guest and clearing cookie.")
                # token过期，清除cookie
                @after_this_request
                def clear_expired_cookie(response):
                    response.delete_cookie('jwt_token', path='/', samesite='Lax', secure=not app.debug)
                    return response
                g.uid = None
                g.email = None
                g.user_id = None
                g.username = None
                g.user_role = 'guest'
            except jwt.InvalidTokenError:
                logger.warning(f"Invalid JWT (optional) token for request to {request.path}. Treating as guest and clearing cookie.")
                # token无效，清除cookie
                @after_this_request
                def clear_invalid_cookie(response):
                    response.delete_cookie('jwt_token', path='/', samesite='Lax', secure=not app.debug)
                    return response
                g.uid = None
                g.email = None
                g.user_id = None
                g.username = None
                g.user_role = 'guest'
            except Exception as e:
                logger.error(f"Unexpected JWT verification error in optional for {request.path}: {e}", exc_info=True)
                # 其他验证错误，也视为游客
                g.uid = None
                g.email = None
                g.user_id = None
                g.username = None
                g.user_role = 'guest'
        else:
            logger.debug(f"No JWT token found in cookies for (optional) request to {request.path}. Treating as guest.")
        return f(*args, **kwargs)
    return decorated_function

# 角色权限装饰器
def role_required(required_role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not hasattr(g, 'user_role') or g.user_role != required_role:
                logger.warning(f"Permission denied for user {getattr(g, 'uid', 'N/A')} (Role: {getattr(g, 'user_role', 'N/A')}) to access {request.path}. Required role: {required_role}")
                return error("Permission denied. Insufficient role.", 403)
            logger.debug(f"User {g.uid} (Role: {g.user_role}) has required role '{required_role}' for {request.path}.")
            return f(*args, **kwargs)
        return decorated_function
    return decorator



# CGB等级计算函数
def calculate_level(cgb_points):
    """根据CGB点数计算用户等级，最高8级。"""
    if cgb_points < 200: return 1
    elif cgb_points < 300: return 2
    elif cgb_points < 600: return 3
    elif cgb_points < 1000: return 4
    elif cgb_points < 1500: return 5
    elif cgb_points < 2500: return 6
    elif cgb_points < 4000: return 7
    else: return 8 

# CGB点数和活动日志更新辅助函数
def update_user_cgb_points(user_id, points_change, reason, related_id=None, related_type=None):
    """更新用户CGB点数，并记录活动日志。"""
    if points_change == 0:
        return True 
    current_points_data = fetch_user_db('SELECT cgb_points FROM users WHERE id = %s', (user_id,), one=True)
    if not current_points_data:
        logger.error(f"Attempted to update CGB points for non-existent user_id: {user_id}")
        return False
    current_points = current_points_data['cgb_points']
    new_points = current_points + points_change
    execute_user_db('UPDATE users SET cgb_points = %s WHERE id = %s', (new_points, user_id))
    new_level = calculate_level(new_points)
    execute_user_db('UPDATE users SET level = %s WHERE id = %s', (new_level, user_id))
    log_description = f"{'获得' if points_change > 0 else '失去'} {abs(points_change)} CGB点: {reason}"
    add_activity_log(user_id, 'points_change', actor_uid=g.uid, related_id=related_id, related_type=related_type, description=log_description, points_change=points_change)
    logger.info(f"User {user_id} CGB points changed by {points_change}. New total: {new_points}. New level: {new_level}")
    return True

def award_badge(user_id, badge_id):
    """授予用户徽章。"""
    has_badge = fetch_user_db('SELECT 1 FROM user_badges WHERE user_id = %s AND badge_id = %s', (user_id, badge_id), one=True)
    if has_badge:
        logger.info(f"User {user_id} already has badge {badge_id}. Skipping.")
        return
    execute_user_db('INSERT INTO user_badges (user_id, badge_id) VALUES (%s, %s)', (user_id, badge_id))
    badge_name_data = fetch_user_db('SELECT name FROM badges WHERE id = %s', (badge_id,), one=True)
    badge_name = badge_name_data['name'] if badge_name_data else None
    add_activity_log(user_id, 'badge_awarded', actor_uid=g.uid, related_id=badge_id, related_type='badge', description=f"获得了“{badge_name}”徽章")
    logger.info(f"User {user_id} awarded badge {badge_id}: {badge_name}")

def get_current_week_start_date():
    """获取本周的开始日期 (周一)。"""
    today = datetime.date.today()
    return today - datetime.timedelta(days=today.weekday())

def initialize_weekly_goals(user_id):
    """为用户初始化本周目标，如果尚未设置。"""
    week_start = get_current_week_start_date()
    existing_goals = fetch_user_db(
        'SELECT goal_type FROM user_goals WHERE user_id = %s AND week_start_date = %s',
        (user_id, week_start)
    )
    existing_goal_types = {g['goal_type'] for g in existing_goals}
    if 'post' not in existing_goal_types:
        execute_user_db(
            'INSERT INTO user_goals (user_id, goal_type, target_count, current_count, week_start_date) VALUES (%s, "post", %s, 0, %s)',
            (user_id, 5, week_start) # 默认本周发帖目标5
        )
        logger.info(f"Initialized post goal for user {user_id} for week {week_start}.")
    if 'reply' not in existing_goal_types:
        execute_user_db(
            'INSERT INTO user_goals (user_id, goal_type, target_count, current_count, week_start_date) VALUES (%s, "reply", %s, 0, %s)',
            (user_id, 10, week_start) # 默认本周回复目标10
        )
        logger.info(f"Initialized reply goal for user {user_id} for week {week_start}.")

def update_weekly_goal_progress(user_id, goal_type):
    """更新用户周目标的进度。"""
    week_start = get_current_week_start_date()
    goal = fetch_user_db(
        'SELECT id, target_count, current_count, is_completed FROM user_goals WHERE user_id = %s AND goal_type = %s AND week_start_date = %s',
        (user_id, goal_type, week_start),
        one=True
    )
    if goal and not goal['is_completed']:
        new_current_count = goal['current_count'] + 1
        is_completed = (new_current_count >= goal['target_count'])
        execute_user_db(
            'UPDATE user_goals SET current_count = %s, is_completed = %s WHERE id = %s',
            (new_current_count, is_completed, goal['id'])
        )
        logger.info(f"User {user_id} updated {goal_type} goal. Current: {new_current_count}, Completed: {is_completed}")
        if is_completed:
            update_user_cgb_points(user_id, 20, f"完成本周{goal_type}目标", related_id=goal['id'], related_type='goal')

# 默认头像辅助函数
def generate_default_avatar_for_user(uid, char_to_display):
    """
    为特定用户生成默认头像
    :param uid: 用户 UID (用于文件名)
    :param char_to_display: 显示在头像上的字符 (通常是首字)
    :return: 相对路径 (例如: 'defaults/100001_12345678.jpg') 或 None
    """
    try:
        # 路径准备
        current_dir = os.path.dirname(os.path.abspath(__file__))
        font_path = os.path.join(current_dir, 'fonts', 'msyh.ttc') 
        save_dir = os.path.join(IMG_ROOT_PATH, DEFAULT_AVATAR_SUBFOLDER)
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        # 创建画布 (500x500 高清)
        size = (500, 500)
        img = Image.new('RGB', size, (20, 20, 20))
        draw = ImageDraw.Draw(img)
        # 绘制背景 (随机渐变)
        color_start, color_end = random.choice(AESTHETIC_GRADIENTS)
        for y in range(size[1]):
            # 线性插值计算颜色
            r = int(color_start[0] + (color_end[0] - color_start[0]) * y / size[1])
            g = int(color_start[1] + (color_end[1] - color_start[1]) * y / size[1])
            b = int(color_start[2] + (color_end[2] - color_start[2]) * y / size[1])
            draw.line((0, y, size[0], y), fill=(r, g, b))
        # 加载字体
        font_size = 250
        try:
            font = ImageFont.truetype(font_path, font_size)
        except OSError:
            logger.warning("Default font not found, using system default.")
            font = ImageFont.load_default()

        # 居中绘制文字
        char = char_to_display[0].upper() if char_to_display else '?'
        # 计算文字位置
        # 垂直居中
        if hasattr(draw, 'textbbox'):
            left, top, right, bottom = draw.textbbox((0, 0), char, font=font)
            text_w = right - left
            text_h = bottom - top
            x = (size[0] - text_w) / 2 - left
            y = (size[1] - text_h) / 2 - top - (text_h * 0.1) 
        else:
            text_w, text_h = draw.textsize(char, font=font)
            x = (size[0] - text_w) / 2
            y = (size[1] - text_h) / 2
        # 文字阴影
        draw.text((x + 4, y + 4), char, font=font, fill=(0, 0, 0, 80))
        # 文字主体
        draw.text((x, y), char, font=font, fill=(255, 255, 255))
        # 保存
        timestamp = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        filename = f"{uid}_{timestamp}.jpg"
        full_path = os.path.join(save_dir, filename)
        # 优化压缩保存
        img.save(full_path, 'JPEG', quality=90, optimize=True)
        return os.path.join(DEFAULT_AVATAR_SUBFOLDER, filename) # 返回相对路径
    except Exception as e:
        logger.error(f"Avatar generation failed for UID {uid}: {e}")
        return None
# 认证接口
@app.route('/api/cgbregister', methods=['POST'])
def register():
    logger.info("Register endpoint called.")
    data = request.get_json()
    # 获取基本信息
    email = data.get('email')
    password = data.get('password')
    confirm_password = data.get('confirm_password')
    # 即使数据库要求非空，这里通过 get 默认为空字符串 '' 也能满足 text/varchar 类型的非空约束
    first_name = data.get('first_name', '').strip()
    last_name = data.get('last_name', '').strip()
    # 真实姓名
    true_name_parts = [p for p in [first_name, last_name] if p]
    true_name = " ".join(true_name_parts) if true_name_parts else None
    # 基础校验
    if not email or not password:
        return error("请填写邮箱和密码", 400)
    if password != confirm_password:
        return error("两次输入的密码不一致", 400)
    # 密码强度校验
    if len(password) < 8 or not any(char.isdigit() for char in password) or not any(char.isalpha() for char in password):
        return error("密码至少8位，且包含字母和数字", 400)
    # 邮箱唯一性
    user_exists = fetch_user_db('SELECT id FROM users WHERE email = %s', (email,), one=True)
    if user_exists:
        return error("该邮箱已被注册", 409)
    # 生成随机显示名称辅助函数
    random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
    display_name = f"用户{random_suffix}"
    pwd_hash = hash_password(password)
    try:
        insert_sql = """
            INSERT INTO users (email, password_hash, display_name, true_name, first_name, last_name)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        user_internal_id = execute_user_db(
            insert_sql,
            (email, pwd_hash, display_name, true_name, first_name, last_name)
        )
        if not user_internal_id:
            logger.error(f"Failed to retrieve auto-increment ID for {email}")
            return error("注册失败: 数据库写入异常", 500)
        # 生成并更新 UID
        # 初始化点数为 25
        uid = format_sequential_uid(user_internal_id, 6)
        update_user_sql = "UPDATE users SET uid = %s, cgb_points = 25 WHERE id = %s"
        execute_user_db(update_user_sql, (uid, user_internal_id))
        logger.info(f"User registered: {email} -> UID: {uid}, DisplayName: {display_name}")
        # 生成默认头像
        # 取第一个字
        char_for_avatar = display_name[0] if display_name else '默'
        # 调用之前定义的生成函数 (确保函数 generate_default_avatar_for_user 在 app.py 中可见)
        avatar_relative_path = generate_default_avatar_for_user(uid, char_for_avatar)
        if avatar_relative_path:
            full_avatar_url = f"{IMAGE_SERVER_BASE_URL}/{avatar_relative_path}"
            execute_user_db('UPDATE users SET avatar_url = %s WHERE id = %s', (full_avatar_url, user_internal_id))
            logger.info(f"Default avatar set for {uid}: {full_avatar_url}")
        else:
            logger.warning(f"Skipping avatar generation for {uid} due to internal error.")
        return success({"uid": uid, "display_name": display_name}, "注册成功！已赠送25 CGB点数用于个性化设置。")
    except Exception as e:
        logger.error(f"Database error during registration for {email}: {e}", exc_info=True)
        # 针对特定数据库错误提示
        if "1364" in str(e):
            return error("注册失败：数据库字段缺失默认值，请联系管理员", 500)
        return error(f"注册失败: 服务器内部错误", 500)
# 登录路由
@app.route('/api/cgblogin', methods=['POST'])
def login():
    logger.info("Login endpoint called.")
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    captcha_id = data.get('captcha_id')
    captcha_value = data.get('captcha_value')

    logger.debug(f"Attempting login for email: {email}")
    if not email or not password:
        logger.warning(f"Login failed for email {email}: Missing email or password in request.")
        return error("请输入邮箱和密码", 400)
    if not captcha_id or not captcha_value:
        logger.warning(f"Login failed for email {email}: Missing captcha ID or value.")
        return error("请输入验证码", 400)
    captcha_valid = False
    # 优先尝试Redis验证
    if redis_client:
        stored_value = redis_client.get(f"captcha:{captcha_id}")
        if stored_value:
            if stored_value == captcha_value.lower():
                captcha_valid = True
                redis_client.delete(f"captcha:{captcha_id}")
                logger.debug(f"Captcha {captcha_id} verified via Redis.")
            else:
                redis_client.delete(f"captcha:{captcha_id}")
                return error("验证码不正确", 400)

    # Redis未命中或未验证，尝试从数据库验证
    if not captcha_valid:
        captcha_record = fetch_user_db(
            'SELECT value, expires_at, is_used FROM captcha_store WHERE id = %s',
            (captcha_id,),
            one=True
        )

        if not captcha_record:
            logger.warning(f"Login failed: Invalid captcha ID '{captcha_id}'.")
            return error("验证码无效或已过期", 400)
        if captcha_record['is_used']:
            return error("验证码已使用，请刷新", 400)
        if captcha_record['expires_at'] < datetime.datetime.now(timezone.utc):
            execute_user_db('UPDATE captcha_store SET is_used = TRUE WHERE id = %s', (captcha_id,))
            return error("验证码已过期，请刷新", 400)
        if captcha_record['value'] == captcha_value.lower():
            captcha_valid = True
            execute_user_db('UPDATE captcha_store SET is_used = TRUE WHERE id = %s', (captcha_id,))
            logger.debug(f"Captcha {captcha_id} verified via DB.")
        else:
            execute_user_db('UPDATE captcha_store SET is_used = TRUE WHERE id = %s', (captcha_id,))
            return error("验证码不正确", 400)
    
    # 拦截请求
    if not captcha_valid:
        return error("验证码校验失败", 400)
    user = fetch_user_db('SELECT id, uid, email, password_hash, display_name, role FROM users WHERE email = %s', (email,), one=True)

    if not user:
        logger.warning(f"Login failed for email {email}: User not found in database.")
        return error("账号或密码错误", 401)
    if check_password(user['password_hash'], password):
        logger.info(f"Login successful for user {email} (UID: {user['uid']}).")

        token_payload = {
            'uid': user['uid'],
            'email': user['email'],
            'exp': datetime.datetime.now(timezone.utc) + timedelta(hours=app.config['JWT_ACCESS_TOKEN_EXPIRES_HOURS']),
            'iat': datetime.datetime.now(timezone.utc)
        }
        token = jwt.encode(token_payload, app.config['SECRET_KEY'], algorithm='HS256')
        logger.debug(f"Generated JWT token for user {user['uid']}.")

        user_id = user['id']
        login_ip = request.headers.get('X-Forwarded-For')
        logger.info(f"切割前的IP地址：{login_ip}")
        login_ip = login_ip.split(', ')[0].strip()
        logger.info(f"切割后的IP地址：{login_ip}")
        login_device = request.headers.get('User-Agent')
        login_location = get_ip_location(login_ip)

        log_sql = """
            INSERT INTO login_logs (user_id, login_ip, login_location, login_device)
            VALUES (%s, %s, %s, %s)
        """
        try:
            logger.debug(f"Logging login event for user {user_id} from {login_ip} ({login_location}).")
            execute_user_db(log_sql, (user_id, login_ip, login_location, login_device))
            logger.debug(f"Login log entry created for user {user_id}.")
        except Exception as e:
            logger.error(f"Error logging login event for user {user_id}: {e}", exc_info=True)

        initialize_weekly_goals(user['id'])
        update_last_activity_optimized(user['id'])

        # 返回给前端的用户非敏感信息
        user_info_for_frontend = {
            "uid": user['uid'],
            "username": user['display_name'], 
            "email": user['email'],
            "role": user['role']
        }

        # 构建响应并设置Cookie
        response_json = success({"user": user_info_for_frontend}, "登录成功")
        response = make_response(response_json)
        response.set_cookie(
            'jwt_token',
            token,
            max_age=timedelta(hours=app.config['JWT_ACCESS_TOKEN_EXPIRES_HOURS']).total_seconds(),
            httponly=True,
            samesite='Lax', # 防止CSRF攻击
            path='/',
            secure=True 
            # secure=not app.debug 
            # 生产环境 secure=True, 开发环境 secure=False
        )
        return response
    else:
        logger.warning(f"Login failed for email {email}: Invalid password provided.")
        return error("账号或密码错误", 401)

# 登出路由
@app.route('/api/cgblogout', methods=['POST'])
def cgblogout():
    logger.info("Logout endpoint called. Deleting jwt_token cookie.")
        # 将Token加入Redis黑名单
    token = request.cookies.get('jwt_token')
    if token and redis_client:
        try:
            # 计算剩余有效期
            expire_seconds = app.config['JWT_ACCESS_TOKEN_EXPIRES_HOURS'] * 3600
            token_hash = hashlib.md5(token.encode()).hexdigest()
            redis_client.setex(f"blacklist:token:{token_hash}", expire_seconds, "1")
            logger.info(f"Token added to blacklist: {token_hash}")
        except Exception as e:
            logger.error(f"Failed to blacklist token: {e}")

    # ---------------------------------------
    response = make_response(success(message="登出成功"))
    response.delete_cookie('jwt_token', path='/', samesite='Lax', secure=not app.debug)
    return response

# 保持用户登录状态
@app.route('/api/user/me', methods=['GET'])
@jwt_optional 
def get_current_user():
    logger.info(f"Get current user info endpoint called. Current g.uid: {g.uid}")

    if g.uid: # 如果g.uid 存在，说明用户已登录
        user_info = {
            "is_logged_in": True,
            "uid": g.uid,
            "user_id": g.user_id,
            "username": g.username,
            "email": g.email,
            "role": g.user_role,
            "avatar_url": None # 默认设置为 None，从数据库获取
        }
        # 从数据库获取更多信息
        full_user_data = fetch_user_db('SELECT cgb_points, level, avatar_url, true_name FROM users WHERE id = %s', (g.user_id,), one=True)
        if full_user_data:
            user_info['cgb_points'] = full_user_data['cgb_points']
            user_info['level'] = full_user_data['level']
            user_info['avatar_url'] = full_user_data['avatar_url'] 
            user_info['true_name'] = full_user_data['true_name'] 
        logger.debug(f"Returning logged-in user info for UID: {g.uid}")
        return success(user_info)
    else: # 否则，用户为游客
        logger.debug("Returning guest user info.")
        return success({
            "is_logged_in": False,
            "uid": None,
            "user_id": None,
            "username": "Guest",
            "email": None,
            "role": "guest",
            "avatar_url": None,
            "true_name": None 
        })


# 验证码图片生成函数
def generate_captcha_image(text):
    width, height = 280, 100 # 再次调整画布到更合理的大小，先排除画布问题
    
    bg_color = (random.randint(200, 255), random.randint(200, 255), random.randint(200, 255))
    image = Image.new('RGB', (width, height), color=bg_color)
    draw = ImageDraw.Draw(image)

    font_path = os.path.join(os.path.dirname(__file__), 'fonts', 'Minecraft_Next_Font_12px2.0.ttf')
    desired_font_size = 60 # 使用一个相对正常的字体大小，便于观察
    font = None
    try:
        if os.path.exists(font_path):
            logger.info(f"Attempting to load custom font from: {font_path} with size {desired_font_size}")
            # 尝试加载自定义字体
            font = ImageFont.truetype(font_path, desired_font_size)
            logger.info(f"Custom font '{font_path}' loaded successfully.")
        else:
            logger.warning(f"Custom font file not found at: {font_path}. Falling back to default font.")
            font = ImageFont.load_default()
    except Exception as e:
        # 捕获所有可能的异常，包括内部渲染错误
        logger.error(f"Error loading custom font '{font_path}': {e}. Falling back to default font.", exc_info=True)
        font = ImageFont.load_default()

        except Exception as e:
            logger.error(f"Error loading fallback font: {e}. Still using default Pillow font.", exc_info=True)


    # 随机深色
    def get_random_color():
        return (random.randint(30, 120), random.randint(30, 120), random.randint(30, 120))
    # 调整循环和绘制逻辑以适应更大的画布和字体
    char_width_estimate = desired_font_size * 0.8 # 估计每个字符的宽度
    start_x = (width - len(text) * char_width_estimate) / 2 # 居中开始绘制
    for i, char in enumerate(text):
        # 临时画布要大到能容纳旋转后的字符
        temp_canvas_size = int(desired_font_size * 1.5) # 给旋转留足空间
        char_image = Image.new('RGBA', (temp_canvas_size, temp_canvas_size), (0, 0, 0, 0))
        char_draw = ImageDraw.Draw(char_image)
        # 在临时画布上绘制字符，位置偏上，但留足旋转后的空间
        # 绘制位置需要根据字体度量来微调，这里是粗略估计
        char_draw.text((temp_canvas_size * 0.1, temp_canvas_size * 0.05), char, font=font, fill=get_random_color())
        angle = random.randint(-20, 20) 
        char_image = char_image.rotate(angle, expand=1, resample=Image.Resampling.BICUBIC)
        
        # 计算粘贴位置
        paste_x = int(start_x + i * char_width_estimate + random.randint(-5, 5))
        paste_y = random.randint(0, height - temp_canvas_size) # 垂直方向随机，但确保在图片范围内
        
        image.paste(char_image, (paste_x, paste_y), char_image)

    # 绘制干扰线
    for _ in range(random.randint(6, 10)):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = random.randint(0, width), random.randint(0, height)
        draw.line((x1, y1, x2, y2), fill=get_random_color(), width=random.randint(1, 3))
    # 绘制干扰点
    for _ in range(int(width * height / 15)): # 根据面积调整点数
        draw.point((random.randint(0, width), random.randint(0, height)), fill=get_random_color())

    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format='PNG')
    return img_byte_arr.getvalue()


@app.route('/api/captcha/generate', methods=['GET'])
@limiter.limit("20 per minute; 5 per 10 second") 
def generate_captcha():
    logger.info("Generating new captcha.")
    try:
        captcha_text = ''.join(random.choices('0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ', k=5))
        captcha_id = str(uuid.uuid4())

        if redis_client:
            # Key: captcha:{id}, Value: text
            redis_client.setex(f"captcha:{captcha_id}", 300, captcha_text.lower())
        else:
            expires_at = datetime.datetime.now(timezone.utc) + timedelta(minutes=5)
            execute_user_db(
                'INSERT INTO captcha_store (id, value, expires_at) VALUES (%s, %s, %s)',
                (captcha_id, captcha_text.lower(), expires_at)
            )
        
        img_bytes = generate_captcha_image(captcha_text)


        img_base64 = base64.b64encode(img_bytes).decode('utf-8')

        logger.debug(f"Captcha generated: ID={captcha_id}, Text={captcha_text}")
        return success({
            "captcha_id": captcha_id,
            "captcha_image_src": f"data:image/png;base64,{img_base64}"
        }, "验证码生成成功")

    except Exception as e:
        logger.error(f"Error generating captcha: {e}", exc_info=True)
        return error(f"验证码生成失败: {str(e)}", 500)


# 首页接口
@app.route('/api/home/stats', methods=['GET'])
def get_home_stats():
    logger.info("Get home stats endpoint called.")

    # 读取缓存
    cache_key = "cache:home_stats"
    if redis_client:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            return success(json.loads(cached_data), "首页统计数据获取成功(Cache)")

    try:
        # 主题数 (板块+子板块)
        total_sections_data = fetch_user_db('SELECT COUNT(id) AS count FROM forum_sections', one=True)
        count_sections = total_sections_data['count'] if total_sections_data and 'count' in total_sections_data else 0
        total_subsections_data = fetch_user_db('SELECT COUNT(id) AS count FROM forum_subsections', one=True)
        count_subsections = total_subsections_data['count'] if total_subsections_data and 'count' in total_subsections_data else 0
        total_topics_count = count_sections + count_subsections

        # 帖子数 (帖子+回复)
        total_posts_data = fetch_user_db('SELECT COUNT(id) AS count FROM forum_posts WHERE status=1', one=True)
        actual_forum_posts_count = total_posts_data['count'] if total_posts_data and 'count' in total_posts_data else 0
        total_replies_data = fetch_user_db('SELECT COUNT(id) AS count FROM forum_replies', one=True)
        total_posts_and_replies = actual_forum_posts_count

        # 用户数
        total_users_data = fetch_user_db('SELECT COUNT(id) AS count FROM users', one=True)
        total_users = total_users_data['count'] if total_users_data and 'count' in total_users_data else 0

        # 在线数
        five_minutes_ago = datetime.datetime.now(timezone.utc) - timedelta(minutes=5)
        
        # 在线人数统计
        online_users = 0
        if redis_client:
            try:
                # 统计5分钟内活跃的用户
                now_ts = time.time()
                min_ts = now_ts - 300
                # 移除过期的
                redis_client.zremrangebyscore("stats:online_users", 0, min_ts)
                # 统计剩余数量
                online_users = redis_client.zcard("stats:online_users")
            except Exception as e:
                logger.error(f"Redis ZCOUNT failed: {e}")
                five_minutes_ago = datetime.datetime.now(timezone.utc) - timedelta(minutes=5)
                online_users_data = fetch_user_db('SELECT COUNT(id) AS count FROM users WHERE last_activity >= %s', (five_minutes_ago,), one=True)
                online_users = online_users_data['count'] if online_users_data else 0
        else:
            five_minutes_ago = datetime.datetime.now(timezone.utc) - timedelta(minutes=5)
            online_users_data = fetch_user_db('SELECT COUNT(id) AS count FROM users WHERE last_activity >= %s', (five_minutes_ago,), one=True)
            online_users = online_users_data['count'] if online_users_data else 0

        stats_data = {
            "topics": total_topics_count,
            "posts": total_posts_and_replies,
            "users": total_users,
            "online": online_users
        }

        # 写入缓存
        if redis_client:
            redis_client.setex(cache_key, 30, json.dumps(stats_data))
        logger.info(f"Home stats fetched successfully: {stats_data}")
        return success(stats_data, "首页统计数据获取成功")
    except Exception as e:
        logger.error(f"Error fetching home stats: {e}", exc_info=True)
        return error(f"获取首页统计数据失败: {str(e)}", 500)


# 论坛接口
@app.route('/api/forum/modules', methods=['GET'])
def get_forum_modules():
    logger.info("Get forum modules endpoint called.")
    cache_key = "cache:forum_modules"
    if redis_client:
        cached_data = redis_client.get(cache_key)
        if cached_data:
             return success(json.loads(cached_data))
    try:
        # 获取主分区
        sections_sql = "SELECT id, name, order_index, is_active FROM forum_sections WHERE is_active = TRUE ORDER BY order_index ASC"
        sections_data = fetch_user_db(sections_sql)

        result = []
        for section in sections_data:
            # 获取子版块
            subsections_sql = """
                SELECT id, section_id, name, link_path, order_index, is_active 
                FROM forum_subsections 
                WHERE section_id = %s AND is_active = TRUE 
                ORDER BY order_index ASC
            """
            subsections_data = fetch_user_db(subsections_sql, (section['id'],))

            section_dict = {
                'id': section['id'],
                'name': section['name'],
                'order_index': section['order_index'],
                'subsections': []
            }

            for sub in subsections_data:
                section_dict['subsections'].append({
                    'id': sub['id'], # 这个ID很重要，发帖要传
                    'name': sub['name'],
                    'link_path': sub['link_path'], # 前端路由匹配用
                    'order_index': sub['order_index']
                })
            result.append(section_dict)
        
         # 写入缓存
        if redis_client:
            redis_client.setex(cache_key, 3600, json.dumps(result))
        return success(result, "Forum modules fetched successfully")
    except Exception as e:
        logger.error(f"Error fetching forum modules: {e}", exc_info=True)
        return error("获取论坛模块失败", 500)

@app.route('/api/forum/thread', methods=['POST'])
@login_required
def create_thread():
    data = request.get_json()
    title = data.get('title')
    content_html = data.get('content') 
    subsection_id = data.get('subsection_id') 
    # 兼容处理
    if not subsection_id and 'module_id' in data:
        subsection_id = data['module_id']

    if not all([title, content_html, subsection_id]):
        return error("缺少标题、内容或版块ID", 400)

    # 预览生成
    raw_text_content = str(content_html) if content_html else ""
    clean_text = re.sub(r'<[^>]+>', '', raw_text_content) 
    content_text_preview = clean_text[:200]
    
    insert_sql = """
        INSERT INTO forum_posts 
        (user_id, subsection_id, title, content, content_text_preview, 
         created_at, updated_at, last_reply_at, last_reply_user_id, last_reply_username)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    now = datetime.datetime.now(timezone.utc)
    params = (
        g.user_id, subsection_id, title, content_html, content_text_preview, 
        now, now, now, g.user_id, g.username
    )
    
    print(f"[DEBUG] 准备执行 SQL, user_id={g.user_id}, content字段长度={len(str(content_html))}")

    try:
        post_id = execute_user_db(insert_sql, params)
        print(f"[DEBUG] SQL 执行完毕, 返回 post_id: {post_id}")

        if post_id:
            update_user_cgb_points(g.user_id, 10, "发帖奖励", related_id=post_id, related_type='post')
            add_activity_log(g.user_id, 'posted_thread', actor_uid=g.uid, related_id=post_id, related_type='post', description=f"发布了帖子《{title}》")

            execute_user_db("""
                INSERT INTO user_forum_stats (user_id, thread_count) VALUES (%s, 1)
                ON DUPLICATE KEY UPDATE thread_count = thread_count + 1
            """, (g.user_id,))
            
            print("----- [DEBUG] 发帖成功结束 -----")
            return success({"post_id": post_id}, "帖子创建成功", 201)
        else:
            print("[ERROR] 数据库执行未返回 ID")
            return error("帖子创建失败", 500)

    except Exception as e:
        print(f"----- [CRITICAL ERROR] 发生异常: {e}")
        import traceback
        traceback.print_exc() # 打印完整报错堆栈
        return error(f"创建帖子失败: {str(e)}", 500)



# 获取帖子列表 (支持分页、搜索、筛选)
@app.route('/api/forum/posts', methods=['GET'])
@jwt_optional # 识别当前用户，以便判断是否点赞
def get_forum_posts():
    # 参数获取
    subsection_id = request.args.get('subsection_id')
    category_slug = request.args.get('category_slug')
    
    search_term = request.args.get('search', '')
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    order_by_param = request.args.get('order_by', 'last_reply_at DESC')

    offset = (page - 1) * limit
    conditions = ["fp.status = 1"]
    filter_params = []

    # 筛选逻辑
    if subsection_id:
        conditions.append("fp.subsection_id = %s")
        filter_params.append(subsection_id)
    elif category_slug:
        conditions.append("fp.subsection_id IN (SELECT id FROM forum_subsections WHERE link_path LIKE %s)")
        filter_params.append(f"%{category_slug}%")
    if search_term:
        conditions.append("(fp.title LIKE %s)")
        filter_params.append(f"%{search_term}%")

    where_clause = "WHERE " + " AND ".join(conditions)

    # 排序安全检查
    valid_orders = {
        'created_at DESC': 'fp.created_at DESC',
        'last_reply_at DESC': 'fp.last_reply_at DESC',
        'view_count DESC': 'fp.view_count DESC',
        'likes_count DESC': 'fp.likes_count DESC'
    }
    order_sql = valid_orders.get(order_by_param, 'fp.last_reply_at DESC')

    # 查询总数
    count_sql = f"SELECT COUNT(fp.id) AS count FROM forum_posts fp {where_clause}"
    total_data = fetch_user_db(count_sql, tuple(filter_params), one=True)
    total_posts = total_data['count'] if total_data else 0

    # 查询列表数据
    current_uid = g.user_id if g.user_id else 0 
    data_sql = f"""
        SELECT fp.id, fp.title, fp.view_count, fp.reply_count, fp.likes_count, 
               fp.created_at, fp.last_reply_at, fp.last_reply_username, fp.is_sticky, fp.is_essence, fp.user_id,
               u.uid AS author_uid, u.display_name AS author_display_name,
               u.avatar_url, u.nickname_color,
               fs.name as subsection_name,
               (SELECT 1 FROM post_likes pl WHERE pl.post_id = fp.id AND pl.user_id = %s LIMIT 1) as has_liked
        FROM forum_posts fp
        JOIN users u ON fp.user_id = u.id
        LEFT JOIN forum_subsections fs ON fp.subsection_id = fs.id
        {where_clause}
        ORDER BY fp.is_sticky DESC, {order_sql}
        LIMIT %s OFFSET %s
    """
    query_params = [current_uid] + filter_params + [limit, offset]
    posts = fetch_user_db(data_sql, tuple(query_params))
    formatted_posts = []
    for post in posts:
        formatted_posts.append({
            'id': post['id'],
            'title': post['title'],
            'author': post['author_display_name'],
            'author_uid': post['author_uid'],
            'author_user_id': post['user_id'], # 判断是否是自己的帖子
            'author_avatar_url': post['avatar_url'], # 头像
            'nickname_color': post['nickname_color'], # 昵称颜色
            'subsection_name': post['subsection_name'],
            'publishDate': post['created_at'].strftime('%Y-%m-%d') if post['created_at'] else '',
            'replies': post['reply_count'],
            'views': post['view_count'],
            'likes': post['likes_count'],
            'has_liked': bool(post['has_liked']), # 状态同步
            'isSticky': bool(post['is_sticky']),
            'isFeatured': bool(post['is_essence']),
            'lastReply': {
                'user': post['last_reply_username'],
                'time': post['last_reply_at'].strftime('%Y-%m-%d %H:%M') if post['last_reply_at'] else ''
            }
        })

    return success({
        "posts": formatted_posts,
        "total": total_posts,
        "page": page,
        "limit": limit
    })
       
# 获取用户装饰信息辅助函数(称号、前3个徽章)
def get_user_decorations(user_id):
    try:
        # 获取佩戴的称号
        title_sql = """
            SELECT t.name, t.style_css 
            FROM user_titles t
            JOIN users u ON u.current_title_id = t.id
            WHERE u.id = %s
        """
        title = fetch_user_db(title_sql, (user_id,), one=True)
        
        # 获取前3个徽章
        badges_sql = """
            SELECT b.name, b.icon_url, b.description
            FROM user_badges ub
            JOIN badges b ON ub.badge_id = b.id
            WHERE ub.user_id = %s
            ORDER BY ub.created_at DESC
            LIMIT 3
        """
        badges = fetch_user_db(badges_sql, (user_id,))
        return title, badges
    except Exception as e:
        logger.error(f"Error fetching decorations for user {user_id}: {e}")
        return None, []

#  获取帖子详情
@app.route('/api/forum/post/<int:post_id>', methods=['GET'])
@app.route('/api/forum/thread/<int:post_id>', methods=['GET'])
@jwt_optional 
def get_post_detail(post_id):
    logger.info(f"Get post detail endpoint called for ID: {post_id}")
    try:
        execute_user_db("UPDATE forum_posts SET view_count = view_count + 1 WHERE id = %s", (post_id,))
        current_uid = g.user_id if g.user_id else 0
        sql = """
            SELECT fp.id, fp.title, fp.content, fp.created_at, fp.view_count, fp.reply_count,
                   fp.subsection_id, fp.is_locked, fp.tags, fp.user_id,
                   u.display_name AS author_display_name, u.level, u.cgb_points, 
                   u.uid AS author_uid, u.avatar_url, u.nickname_color,
                   fs.name AS subsection_name,
                   (SELECT 1 FROM post_likes pl WHERE pl.post_id = fp.id AND pl.user_id = %s LIMIT 1) as has_liked,
                   (SELECT COUNT(*) FROM post_likes WHERE post_id = fp.id) as real_likes_count
            FROM forum_posts fp
            LEFT JOIN users u ON fp.user_id = u.id
            LEFT JOIN forum_subsections fs ON fp.subsection_id = fs.id
            WHERE fp.id = %s AND fp.status = 1 
        """
        row = fetch_user_db(sql, (current_uid, post_id), one=True)
        
        if not row:
            return error("主题不存在或已被删除", 404)

        # 获取装饰信息 (称号 + 徽章)
        title_info, badges_list = get_user_decorations(row['user_id'])

        post_data = {
            "id": row['id'],
            "title": row['title'],
            "content": row['content'],
            "created_at": row['created_at'].isoformat() if row['created_at'] else None,
            "view_count": row['view_count'],
            "reply_count": row['reply_count'],
            "is_locked": bool(row['is_locked']),
            "tags": row['tags'].split(',') if row.get('tags') else [],
            "user_id": row['user_id'], # 作者 DB ID
            "author_uid": row.get('author_uid'),
            "author_name": row.get('author_display_name') or "Unknown",
            "author_avatar_url": row.get('avatar_url'),
            "nickname_color": row.get('nickname_color'), # [新增]
            "level": row.get('level', 1),
            "cgb_points": row.get('cgb_points', 0),
            "subsection_name": row.get('subsection_name'),
            "subsection_id": row.get('subsection_id'),
            "likes": row['real_likes_count'], # [新增]
            "has_liked": bool(row['has_liked']), # [新增]
            "author_title": title_info, # [新增]
            "author_badges": badges_list # [新增]
        }
        
        return success(post_data)
    except Exception as e:
        logger.error(f"Error fetching post detail: {e}", exc_info=True)
        return error(f"获取帖子详情失败: {str(e)}", 500)

# 获取回复列表 
@app.route('/api/forum/post/<int:post_id>/replies', methods=['GET'])
@jwt_optional # [关键]
def get_post_replies(post_id):
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 10))
    offset = (page - 1) * limit
    current_uid = g.user_id if g.user_id else 0
    sql = """
        SELECT fr.id, fr.content, fr.created_at, fr.floor_number, fr.likes_count, fr.user_id,
               u.uid as author_uid, u.display_name AS author_name, 
               u.level, u.cgb_points, u.avatar_url, u.nickname_color,
               (SELECT 1 FROM reply_likes rl WHERE rl.reply_id = fr.id AND rl.user_id = %s LIMIT 1) as has_liked
        FROM forum_replies fr
        LEFT JOIN users u ON fr.user_id = u.id
        WHERE fr.post_id = %s AND fr.status = 1
        ORDER BY fr.floor_number ASC
        LIMIT %s OFFSET %s
    """
    replies = fetch_user_db(sql, (current_uid, post_id, limit, offset))
    formatted = []
    for r in replies:
        # 获取每个回复者的装饰信息
        title_info, badges_list = get_user_decorations(r['user_id'])

        formatted.append({
            'id': r['id'],
            'content': r['content'],
            'floor': r['floor_number'],
            'likes': r['likes_count'],
            'has_liked': bool(r['has_liked']), 
            'time': r['created_at'].strftime('%Y-%m-%d %H:%M') if r['created_at'] else '',
            'author': {
                'user_id': r['user_id'], 
                'uid': r['author_uid'],
                'name': r.get('author_name') or "Unknown",
                'level': r.get('level', 1),
                'cgb_points': r.get('cgb_points', 0),
                'avatar_url': r.get('avatar_url'),
                'nickname_color': r.get('nickname_color'), 
                'title': title_info,
                'badges': badges_list
            }
        })
    
    return success(formatted)

# 获取帖子内容用于编辑
@app.route('/api/forum/thread/<int:post_id>/edit', methods=['GET'])
@login_required
def get_post_for_edit(post_id):
    logger.info(f"Get post for edit endpoint called for ID: {post_id} by user {g.user_id}")
    try:
        # 只有帖子作者或管理员可以编辑
        post = fetch_user_db(
            'SELECT id, user_id, title, content, subsection_id FROM forum_posts WHERE id = %s AND status = 1',
            (post_id,),
            one=True
        )

        if not post:
            return error("帖子不存在或无权编辑", 404)

        if post['user_id'] != g.user_id and g.user_role != 'admin':
            return error("您无权编辑此帖子", 403)

        return success({
            'id': post['id'],
            'title': post['title'],
            'content': post['content'],
            'subsection_id': post['subsection_id']
        })
    except Exception as e:
        logger.error(f"Error fetching post {post_id} for edit: {e}", exc_info=True)
        return error(f"获取帖子编辑内容失败: {str(e)}", 500)

# 更新帖子
@app.route('/api/forum/thread/<int:post_id>', methods=['PUT'])
@login_required
def update_forum_post(post_id):
    logger.info(f"Update post endpoint called for ID: {post_id} by user {g.user_id}")
    data = request.get_json()
    title = data.get('title')
    content_html = data.get('content')
    subsection_id = data.get('subsection_id')

    if not all([title, content_html, subsection_id]):
        return error("缺少标题、内容或版块ID", 400)
    try:
        # 只有帖子作者或管理员可以编辑
        post = fetch_user_db(
            'SELECT id, user_id FROM forum_posts WHERE id = %s AND status = 1',
            (post_id,),
            one=True
        )
        if not post:
            return error("帖子不存在或无权编辑", 404)
        if post['user_id'] != g.user_id and g.user_role != 'admin':
            return error("您无权编辑此帖子", 403)
        # 预览生成
        raw_text_content = str(content_html) if content_html else ""
        clean_text = re.sub(r'<[^>]+>', '', raw_text_content) 
        content_text_preview = clean_text[:200]
        now = datetime.datetime.now(timezone.utc)
        update_sql = """
            UPDATE forum_posts
            SET title = %s, content = %s, content_text_preview = %s, subsection_id = %s, updated_at = %s
            WHERE id = %s
        """
        execute_user_db(update_sql, (title, content_html, content_text_preview, subsection_id, now, post_id))
        add_activity_log(g.user_id, 'edited_post', actor_uid=g.uid, related_id=post_id, related_type='post', description=f"编辑了帖子《{title}》")
        return success(None, "帖子更新成功")
    except Exception as e:
        logger.error(f"Error updating post {post_id}: {e}", exc_info=True)
        return error(f"更新帖子失败: {str(e)}", 500)

# 删除帖子
@app.route('/api/forum/thread/<int:post_id>', methods=['DELETE'])
@login_required
def delete_forum_post(post_id):
    logger.info(f"Delete post endpoint called for ID: {post_id} by user {g.user_id}")
    try:
        # 只有帖子作者或管理员可以删除
        post = fetch_user_db(
            'SELECT id, user_id, title FROM forum_posts WHERE id = %s AND status = 1',
            (post_id,),
            one=True
        )
        if not post:
            return error("帖子不存在或无权删除", 404)
        if post['user_id'] != g.user_id and g.user_role != 'admin':
            return error("您无权删除此帖子", 403)
        # 软删除
        execute_user_db('UPDATE forum_posts SET status = 0 WHERE id = %s', (post_id,))
        add_activity_log(g.user_id, 'deleted_post', actor_uid=g.uid, related_id=post_id, related_type='post', description=f"删除了帖子《{post['title']}》")
        return success(None, "帖子删除成功")
    except Exception as e:
        logger.error(f"Error deleting post {post_id}: {e}", exc_info=True)
        return error(f"删除帖子失败: {str(e)}", 500)


# 5. 回复帖子
@app.route('/api/forum/post/<int:post_id>/reply', methods=['POST'])
@login_required
def create_reply(post_id):
    data = request.get_json()
    content = data.get('content')
    if not content:
        return error("回复内容不能为空", 400)
    # 检查帖子是否存在
    post = fetch_user_db("SELECT id, title, subsection_id FROM forum_posts WHERE id = %s", (post_id,), one=True)
    if not post:
        return error("帖子不存在", 404)
    insert_sql = """
        INSERT INTO forum_replies (post_id, user_id, content, created_at, floor_number, status)
        VALUES (%s, %s, %s, %s, 
        (SELECT COUNT(id) + 1 FROM forum_replies AS fr WHERE fr.post_id = %s), 1)
    """
    now = datetime.datetime.now(timezone.utc)
    try:
        # 回复
        reply_id = execute_user_db(insert_sql, (post_id, g.user_id, content, now, post_id))
        if reply_id:
            # 统计数据
            update_post_sql = """
                UPDATE forum_posts 
                SET reply_count = reply_count + 1, 
                    last_reply_at = %s, 
                    last_reply_user_id = %s,
                    last_reply_username = %s
                WHERE id = %s
            """
            execute_user_db(update_post_sql, (now, g.user_id, g.username, post_id))
            # 奖励和日志
            update_user_cgb_points(g.user_id, 2, "回复奖励")
            add_activity_log(g.user_id, 'replied_post', actor_uid=g.uid, related_id=post_id, related_type='post', description=f"回复了帖子《{post['title']}》")
            
            # 更新用户统计表
            execute_user_db("""
                INSERT INTO user_forum_stats (user_id, reply_count) VALUES (%s, 1)
                ON DUPLICATE KEY UPDATE reply_count = reply_count + 1
            """, (g.user_id,))
            return success({"reply_id": reply_id}, "回复成功", 201)
        else:
            return error("回复失败", 500)
    except Exception as e:
        logger.error(f"Error creating reply: {e}", exc_info=True)
        return error("回复失败", 500)

# 点赞
@app.route('/api/forum/post/<int:post_id>/like', methods=['POST'])
@login_required
def like_post(post_id):
    logger.info(f"Like post endpoint called for post ID: {post_id} by UID: {g.uid}.")
    
    # 检查是否重复点赞
    existing_like = fetch_user_db('SELECT 1 FROM post_likes WHERE post_id = %s AND user_id = %s', (post_id, g.user_id), one=True)
    if existing_like:
        return error("您已经点赞过此帖子了", 400)

    # 执行点赞
    execute_user_db('UPDATE forum_posts SET likes_count = likes_count + 1 WHERE id = %s', (post_id,))
    execute_user_db('INSERT INTO post_likes (post_id, user_id) VALUES (%s, %s)', (post_id, g.user_id))

    # 获取帖子作者信息
    sql = """
        SELECT fp.user_id, fp.title, u.uid as author_uid 
        FROM forum_posts fp
        LEFT JOIN users u ON fp.user_id = u.id
        WHERE fp.id = %s
    """
    post_owner_info = fetch_user_db(sql, (post_id,), one=True)
    
    if post_owner_info:
        post_owner_id = post_owner_info['user_id']
        post_title = post_owner_info['title']

        # 给作者加分
        update_user_cgb_points(post_owner_id, 2, "帖子被点赞奖励", related_id=post_id, related_type='post')
        
        # 记录日志
        add_activity_log(
            post_owner_id, 
            'liked_post', 
            actor_uid=g.uid, # 点赞者的 UID
            related_id=post_id, 
            related_type='post', 
            description=f"您的帖子《{post_title}》被 @{g.username} 点赞了"
        )
        logger.info(f"Post {post_id} liked by {g.uid}. Post owner {post_owner_id} awarded CGB points.")
    else:
        logger.warning(f"Post {post_id} not found when processing like by {g.uid}.")
        
    return success(None, "点赞成功")

# 取消点赞帖子
@app.route('/api/forum/post/<int:post_id>/like', methods=['DELETE'])
@login_required
def unlike_post(post_id):
    logger.info(f"Unlike post endpoint called for post ID: {post_id} by UID: {g.uid}.")
    
    # 查询帖子是否存在及作者信息
    post_info = fetch_user_db('SELECT user_id FROM forum_posts WHERE id = %s', (post_id,), one=True)
    if not post_info:
        logger.warning(f"Post {post_id} not found when user {g.uid} attempted to unlike it.")
        return error("帖子不存在", 404)
    
    post_owner_id = post_info['user_id']

    # 作者不能取消点赞自己的帖子
    if post_owner_id == g.user_id:
        logger.warning(f"User {g.uid} attempted to unlike their own post {post_id}.")
        return error("不能取消点赞自己的帖子", 400) # 或者返回其他更合适的错误信息

    # 检查用户是否确实点赞过此帖子
    existing_like = fetch_user_db('SELECT 1 FROM post_likes WHERE post_id = %s AND user_id = %s', (post_id, g.user_id), one=True)
    if not existing_like:
        logger.warning(f"User {g.uid} attempted to unlike post {post_id} which they had not liked.")
        return error("您尚未点赞此帖子", 400)
    # 执行取消点赞
    execute_user_db('UPDATE forum_posts SET likes_count = likes_count - 1 WHERE id = %s AND likes_count > 0', (post_id,))
    execute_user_db('DELETE FROM post_likes WHERE post_id = %s AND user_id = %s', (post_id, g.user_id))
    # 获取帖子作者信息 (用于扣分和日志)
    sql = """
        SELECT fp.user_id, fp.title, u.uid as author_uid, u.display_name as author_display_name
        FROM forum_posts fp
        LEFT JOIN users u ON fp.user_id = u.id
        WHERE fp.id = %s
    """
    post_owner_full_info = fetch_user_db(sql, (post_id,), one=True)
    if post_owner_full_info:
        post_title = post_owner_full_info['title']
        post_author_display_name = post_owner_full_info['author_display_name'] or post_owner_full_info['author_uid']
        # 扣除作者分数
        update_user_cgb_points(post_owner_id, -2, "帖子被取消点赞扣分", related_id=post_id, related_type='post')
        # 记录日志
        add_activity_log(
            post_owner_id, # 帖子作者的 user_id
            'unliked_post', 
            actor_uid=g.uid, # 取消点赞者的 UID
            related_id=post_id, 
            related_type='post', 
            description=f"您的帖子《{post_title}》被 @{g.username} 取消点赞了"
        )
        logger.info(f"Post {post_id} unliked by {g.uid}. Post owner {post_owner_id} deducted CGB points.")
    else:
        logger.warning(f"Post {post_id} owner info not found after unlike by {g.uid}.")
    return success(None, "取消点赞成功")

# 点赞回复
@app.route('/api/forum/reply/<int:reply_id>/like', methods=['POST'])
@login_required
def like_reply(reply_id):
    logger.info(f"Like reply endpoint called for reply ID: {reply_id} by UID: {g.uid}.")
    # 检查是否重复点赞
    existing_like = fetch_user_db('SELECT 1 FROM reply_likes WHERE reply_id = %s AND user_id = %s', (reply_id, g.user_id), one=True)
    if existing_like:
        return error("您已经点赞过此回复了", 400)
    # 执行点赞
    execute_user_db('UPDATE forum_replies SET likes_count = likes_count + 1 WHERE id = %s', (reply_id,))
    execute_user_db('INSERT INTO reply_likes (reply_id, user_id) VALUES (%s, %s)', (reply_id, g.user_id))
    # 获取回复作者信息
    sql = "SELECT user_id, content FROM forum_replies WHERE id = %s"
    reply_info = fetch_user_db(sql, (reply_id,), one=True)
    if reply_info:
        reply_owner_id = reply_info['user_id']
        reply_content_preview = reply_info['content'][:20] if reply_info['content'] else '...'
        update_user_cgb_points(reply_owner_id, 1, "回复被点赞奖励", related_id=reply_id, related_type='reply')
        # 记录日志
        add_activity_log(
            reply_owner_id, 
            'liked_reply', 
            actor_uid=g.uid, 
            related_id=reply_id, 
            related_type='reply', 
            description=f"您的回复 '{reply_content_preview}' 被 @{g.username} 点赞了"
        )
        logger.info(f"Reply {reply_id} liked by {g.uid}. Reply owner {reply_owner_id} awarded CGB points.")
    else:
        logger.warning(f"Reply {reply_id} not found when processing like by {g.uid}.")
    return success(None, "点赞成功")

# 搜索接口与热榜/占位符
def _generate_search_id(length=15):
    pool = string.ascii_lowercase + string.digits
    return ''.join(random.choice(pool) for _ in range(length))
def _ensure_search_tables():
    """幂等创建搜索相关表，并补齐 search_id 字段。"""
    execute_user_db(
        """
        CREATE TABLE IF NOT EXISTS search_logs (
          id BIGINT PRIMARY KEY AUTO_INCREMENT,
          search_id VARCHAR(32) NOT NULL DEFAULT '',
          user_id BIGINT NULL,
          keywords VARCHAR(255) NOT NULL DEFAULT '',
          scope ENUM('all','products','works','qa','trade') DEFAULT 'all',
          ip_addr VARCHAR(64) DEFAULT NULL,
          user_agent VARCHAR(255) DEFAULT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          KEY idx_search_id (search_id),
          KEY idx_user_id (user_id),
          KEY idx_keywords (keywords)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
        commit=True
    )
    # 历史表结构兼容：老表可能没有 search_id
    try:
        execute_user_db(
            "ALTER TABLE search_logs ADD COLUMN search_id VARCHAR(32) NOT NULL DEFAULT '' AFTER id",
            commit=True
        )
    except Exception:
        pass
    try:
        execute_user_db(
            "ALTER TABLE search_logs ADD INDEX idx_search_id (search_id)",
            commit=True
        )
    except Exception:
        pass
    execute_user_db(
        """
        CREATE TABLE IF NOT EXISTS search_hot_keywords (
          id BIGINT PRIMARY KEY AUTO_INCREMENT,
          keyword VARCHAR(255) NOT NULL UNIQUE,
          search_count INT NOT NULL DEFAULT 0,
          last_searched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
        commit=True
    )

@app.route('/api/search', methods=['GET'])
@jwt_optional
def api_search():
    """
    综合搜索接口
    - keywords: 搜索关键词（为空时不返回全部内容，返回 no_keywords 标志）
    - scope: all | products | works | qa | trade
    - show: 每类返回条数（默认12，1-100）
    行为：
      1) 记录搜索日志 search_logs
      2) 累积热搜计数 search_hot_keywords
      3) 有关键词时执行各类查询；无关键词时返回 no_keywords 标记 + 空数组
    """
    keywords = (request.args.get('keywords') or '').strip()
    search_id = (request.args.get('id') or '').strip().lower()
    scope = (request.args.get('scope') or 'all').strip().lower()
    show = request.args.get('show', '12').strip()
    # 兼容
    if not search_id or len(search_id) != 15 or not search_id.isalnum():
        search_id = _generate_search_id(15)
    try:
        page_size = int(show)
    except ValueError:
        page_size = 12
    if page_size <= 0 or page_size > 100:
        page_size = 12
    if scope not in ('all', 'products', 'works', 'qa', 'trade'):
        scope = 'all'
    user_id = getattr(g, 'user_id', None)
    ip_addr = request.headers.get('X-Forwarded-For') or request.remote_addr or ''
    if ip_addr and ',' in ip_addr:
        ip_addr = ip_addr.split(',')[0].strip()
    ua = (request.headers.get('User-Agent') or '')[:250]
    # 不存在建表
    try:
        _ensure_search_tables()
    except Exception as e:
        logger.warning(f"Ensure search tables failed: {e}")
    # 日志
    try:
        execute_user_db(
            """
            INSERT INTO search_logs (search_id, user_id, keywords, scope, ip_addr, user_agent)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (search_id, user_id, keywords, scope, ip_addr, ua)
        )
    except Exception as e:
        logger.error(f"Insert search_logs failed: {e}")
    # 累积热搜
    if keywords:
        try:
            # 先尝试更新，若不存在则插入
            rows = execute_user_db(
                "UPDATE search_hot_keywords SET search_count = search_count + 1 WHERE keyword = %s",
                (keywords,),
                commit=True
            )
            if rows == 0:
                execute_user_db(
                    "INSERT INTO search_hot_keywords (keyword, search_count) VALUES (%s, 1)",
                    (keywords,),
                    commit=True
                )
        except Exception as e:
            logger.error(f"Update hot keywords failed: {e}")
    # 无关键词：不返回全部内容
    if not keywords:
        return success({
            'id': search_id,
            'keywords': '',
            'scope': scope,
            'page_size': page_size,
            'products': [],
            'works': [],
            'qa': [],
            'trade': [],
            'no_keywords': True
        }, '未提供关键词')
    kw_like = f"%{keywords}%"
    products = []
    works = []
    qa_items = []
    trade_items = []
    # 产品
    if scope in ('all', 'products'):
        try:
            products = fetch_user_db(
                """
                SELECT
                  p.id,
                  p.brand,
                  p.name,
                  p.en_name      AS name_en,
                  p.category,
                  p.price,
                  p.hot_score,
                  p.is_new,
                  p.image,
                  p.tags,
                  p.buy_url,
                  p.buy_platform,
                  p.favorites,
                  p.likes
                FROM products p
                WHERE (
                  p.name LIKE %s OR p.en_name LIKE %s OR p.brand LIKE %s OR p.tags LIKE %s
                )
                ORDER BY p.hot_score DESC, p.created_at DESC
                LIMIT %s
                """,
                (kw_like, kw_like, kw_like, kw_like, page_size)
            )
            for p in products:
                tags_val = p.get('tags')
                if isinstance(tags_val, str) and tags_val:
                    try:
                        p['tags'] = json.loads(tags_val)
                    except Exception:
                        p['tags'] = []
                elif tags_val is None:
                    p['tags'] = []
        except Exception as e:
            logger.warning(f"Search products skipped: {e}")
            products = []
    # 玩家优质作品
    if scope in ('all', 'works'):
        try:
            works = fetch_user_db(
                """
                SELECT w.id, w.title, w.author_nick AS author, w.short_desc AS summary
                FROM player_works w
                WHERE w.status = 1 AND (
                  w.title LIKE %s OR w.author_nick LIKE %s OR w.short_desc LIKE %s
                )
                ORDER BY w.rank_score DESC, w.created_at DESC
                LIMIT %s
                """,
                (kw_like, kw_like, kw_like, page_size)
            )
            for w in works:
                try:
                    tag_rows = fetch_user_db(
                        """
                        SELECT t.name FROM work_tags t
                        JOIN work_tag_map m ON m.tag_id = t.id
                        WHERE m.work_id = %s
                        """,
                        (w['id'],)
                    )
                    w['tags'] = [r['name'] for r in tag_rows]
                except Exception:
                    w['tags'] = []
        except Exception as e:
            logger.warning(f"Search works skipped: {e}")
            works = []
    # 问答
    if scope in ('all', 'qa'):
        try:
            qa_items = fetch_user_db(
                """
                SELECT q.id, q.title, q.asker_nick AS asker, q.reply_count AS replies
                FROM qa_questions q
                WHERE q.status = 1 AND (q.title LIKE %s OR q.asker_nick LIKE %s)
                ORDER BY q.created_at DESC
                LIMIT %s
                """,
                (kw_like, kw_like, page_size)
            )
        except Exception as e:
            logger.warning(f"Search qa skipped: {e}")
            qa_items = []
    # 出物/收物
    if scope in ('all', 'trade'):
        try:
            trade_items = fetch_user_db(
                """
                SELECT t.id, t.title AS name, t.type, t.price,
                       (SELECT image_url FROM trade_images WHERE trade_item_id = t.id AND is_primary = 1 LIMIT 1) AS image,
                       t.buy_url, t.buy_platform, t.favorites, t.likes
                FROM trade_items t
                WHERE t.status = 'active' AND (t.title LIKE %s OR t.type LIKE %s)
                ORDER BY t.created_at DESC
                LIMIT %s
                """,
                (kw_like, kw_like, page_size)
            )
        except Exception as e:
            logger.warning(f"Search trade skipped: {e}")
            trade_items = []
    return success({
        'id': search_id,
        'keywords': keywords,
        'scope': scope,
        'page_size': page_size,
        'products': products,
        'works': works,
        'qa': qa_items,
        'trade': trade_items,
        'no_keywords': False
    }, '搜索成功')


@app.route('/api/search/hot', methods=['GET'])
def api_search_hot():
    """返回热搜关键词列表（按搜索次数倒序）"""
    try:
        limit = int(request.args.get('limit', 10))
    except ValueError:
        limit = 10
    if limit <= 0 or limit > 100:
        limit = 10
    try:
        execute_user_db(
            """
            CREATE TABLE IF NOT EXISTS search_hot_keywords (
              id BIGINT PRIMARY KEY AUTO_INCREMENT,
              keyword VARCHAR(255) NOT NULL UNIQUE,
              search_count INT NOT NULL DEFAULT 0,
              last_searched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            commit=True
        )
    except Exception as e:
        logger.warning(f"Ensure search_hot_keywords failed: {e}")

    rows = fetch_user_db(
        "SELECT keyword, search_count FROM search_hot_keywords ORDER BY search_count DESC, last_searched_at DESC LIMIT %s",
        (limit,)
    )
    keywords = [r['keyword'] for r in rows]
    return success({'items': keywords})


@app.route('/api/search/placeholder', methods=['GET'])
@jwt_optional
def api_search_placeholder():
    """
    返回搜索框占位词：
      - 优先使用该用户最近一次搜索词
      - 其次使用同 IP 最近一次搜索词
      - 再次随机取热搜或返回默认
    """
    default_placeholder = '输入关键词开始搜索'
    user_id = getattr(g, 'user_id', None)
    ip_addr = request.headers.get('X-Forwarded-For') or request.remote_addr or ''
    if ip_addr and ',' in ip_addr:
        ip_addr = ip_addr.split(',')[0].strip()
    # 确保表存在
    try:
        _ensure_search_tables()
    except Exception as e:
        logger.warning(f"Ensure search_logs failed: {e}")
    # 最近一次用户搜索
    if user_id:
        row = fetch_user_db(
            "SELECT keywords FROM search_logs WHERE user_id = %s AND keywords <> '' ORDER BY id DESC LIMIT 1",
            (user_id,),
            one=True
        )
        if row and row.get('keywords'):
            return success({'placeholder': row['keywords']})
    # 最近一次IP搜索
    if ip_addr:
        row = fetch_user_db(
            "SELECT keywords FROM search_logs WHERE ip_addr = %s AND keywords <> '' ORDER BY id DESC LIMIT 1",
            (ip_addr,),
            one=True
        )
        if row and row.get('keywords'):
            return success({'placeholder': row['keywords']})
    # 随机热搜
    hot = fetch_user_db(
        "SELECT keyword FROM search_hot_keywords ORDER BY search_count DESC, last_searched_at DESC LIMIT 30"
    )
    if hot:
        import random as _r
        return success({'placeholder': _r.choice(hot)['keyword']})
    return success({'placeholder': default_placeholder})



# 用户个人中心接口
@app.route('/api/user/profile', methods=['GET'])
@login_required
def get_user_profile():
    logger.info(f"User profile request for UID: {g.uid}")
    current_user_id = g.user_id
    current_uid = g.uid
    user_data = {}
    try:
        user_info = fetch_user_db(
            '''SELECT id, uid, email, display_name, true_name, cgb_points, level, role, last_activity, created_at, avatar_url,
               nickname_color, selected_title_id, cgb_booster_active, lottery_tickets, squad_limit
               FROM users WHERE id = %s''',
            (current_user_id,),
            one=True
        )
        if not user_info:
            logger.error(f"User with ID {current_user_id} not found during profile fetch.")
            return error("用户未找到", 404)
        # 当前佩戴的称号详情
        current_title_info = None
        if user_info['selected_title_id']:
            current_title_info = fetch_user_db(
                'SELECT id, name, style_css FROM titles WHERE id = %s',
                (user_info['selected_title_id'],),
                one=True
            )
        # 获取用户拥有的所有称号
        owned_titles = fetch_user_db(
            '''SELECT t.id, t.name, t.style_css 
               FROM user_titles ut 
               JOIN titles t ON ut.title_id = t.id 
               WHERE ut.user_id = %s''',
            (current_user_id,)
        )
        user_data['user_info'] = {
            'uid': user_info['uid'],
            'username': user_info['display_name'],
            'true_name': user_info['true_name'],
            'email': user_info['email'],
            'cgb_points': user_info['cgb_points'],
            'created_at': user_info['created_at'],
            'level': user_info['level'],
            'role': user_info['role'],
            'last_activity': user_info['last_activity'].isoformat() if user_info['last_activity'] else None,
            'avatar_url': user_info['avatar_url'],
            'nickname_color': user_info['nickname_color'],
            'cgb_booster_active': bool(user_info['cgb_booster_active']),
            'lottery_tickets': user_info['lottery_tickets'],
            'squad_limit': user_info['squad_limit'],
            'current_title': current_title_info, # 对象: {id, name, style_css}
            'owned_titles': owned_titles         #
        }
        total_posts_result = fetch_user_db(
            'SELECT COUNT(id) AS count FROM forum_posts WHERE user_id = %s',
            (current_user_id,),
            one=True
        )
        total_posts = total_posts_result['count'] if total_posts_result else 0
        total_replies_result = fetch_user_db(
            'SELECT COUNT(id) AS count FROM forum_replies WHERE user_id = %s',
            (current_user_id,),
            one=True
        )
        total_replies = total_replies_result['count'] if total_replies_result else 0
        user_data['forum_contribution'] = {
            'total_posts': total_posts,
            'total_replies': total_replies,
        }
        now = datetime.datetime.now(timezone.utc)
        yesterday = now - datetime.timedelta(days=1)
        posts_today_result = fetch_user_db(
            'SELECT COUNT(id) AS count FROM forum_posts WHERE user_id = %s AND created_at >= %s',
            (current_user_id, yesterday),
            one=True
        )
        posts_today = posts_today_result['count'] if posts_today_result else 0
        replies_today_result = fetch_user_db(
            'SELECT COUNT(id) AS count FROM forum_replies WHERE user_id = %s AND created_at >= %s',
            (current_user_id, yesterday),
            one=True
        )
        replies_today = replies_today_result['count'] if replies_today_result else 0
        points_gained_today_result = fetch_user_db(
            'SELECT SUM(points_change) AS sum_points FROM activity_log WHERE user_id = %s AND activity_type = "points_change" AND created_at >= %s', # [修改] activity_type 为 points_change
            (current_user_id, yesterday),
            one=True
        )
        points_gained_today = points_gained_today_result['sum_points'] if points_gained_today_result and points_gained_today_result['sum_points'] is not None else 0
        likes_received_today_result = fetch_user_db(
            'SELECT COUNT(id) AS count FROM activity_log WHERE user_id = %s AND (activity_type = "liked_post" OR activity_type = "liked_reply") AND created_at >= %s',
            (current_user_id, yesterday),
            one=True
        )
        likes_received_today = likes_received_today_result['count'] if likes_received_today_result else 0
        user_data['today_performance'] = {
            'posts_today': posts_today,
            'replies_today': replies_today,
            'points_gained_today': points_gained_today,
            'likes_received_today': likes_received_today,
        }
        week_start = get_current_week_start_date()
        user_goals_raw = fetch_user_db(
            'SELECT goal_type, target_count, current_count, is_completed FROM user_goals WHERE user_id = %s AND week_start_date = %s',
            (current_user_id, week_start)
        )
        user_goals = {
            'post_goal': {'target': 0, 'current': 0, 'completed': False},
            'reply_goal': {'target': 0, 'current': 0, 'completed': False}
        }
        for goal in user_goals_raw:
            if goal['goal_type'] == 'post':
                user_goals['post_goal'] = {'target': goal['target_count'], 'current': goal['current_count'], 'completed': bool(goal['is_completed'])}
            elif goal['goal_type'] == 'reply':
                user_goals['reply_goal'] = {'target': goal['target_count'], 'current': goal['current_count'], 'completed': bool(goal['is_completed'])}
        user_data['weekly_goals'] = user_goals
        latest_posts_raw = fetch_user_db(
            'SELECT id, title, created_at FROM forum_posts WHERE user_id = %s ORDER BY created_at DESC LIMIT 3',
            (current_user_id,)
        )
        latest_posts = []
        for post in latest_posts_raw:
            latest_posts.append({
                'id': post['id'],
                'title': post['title'],
                'created_at': post['created_at'].isoformat() if post['created_at'] else None
            })
        user_data['latest_posts'] = latest_posts
        recent_activities_raw = fetch_user_db(
            """
            SELECT al.activity_type, al.related_id, al.related_type, al.description, al.created_at, al.points_change,
                   u_actor.display_name AS actor_display_name, u_actor.uid AS actor_uid,
                   fp.title AS post_title, fr.content AS reply_content, b.name AS badge_name
            FROM activity_log al
            LEFT JOIN users u_actor ON al.actor_uid = u_actor.uid
            LEFT JOIN forum_posts fp ON al.related_id = fp.id AND al.related_type = 'post'
            LEFT JOIN forum_replies fr ON al.related_id = fr.id AND al.related_type = 'reply'
            LEFT JOIN badges b ON al.related_id = b.id AND al.related_type = 'badge'
            WHERE al.user_id = %s
            ORDER BY al.created_at DESC
            LIMIT 10
            """,
            (current_user_id,)
        )
        recent_activities = []
        for activity in recent_activities_raw:
            description = activity['description']
            if not description:
                actor_name = activity['actor_display_name'] or activity['actor_uid'] or '某用户'
                if activity['activity_type'] == 'posted_thread':
                    description = f"发布了帖子《{activity['post_title'] or '未知帖子'}》"
                elif activity['activity_type'] == 'replied_post':
                    post_title_for_reply = fetch_user_db('SELECT title FROM forum_posts WHERE id = %s', (activity['related_id'],), one=True)
                    description = f"回复了帖子《{post_title_for_reply['title'] if post_title_for_reply else '未知帖子'}》"
                elif activity['activity_type'] == 'liked_post':
                    description = f"您的帖子《{activity['post_title'] or '未知帖子'}》被 @{actor_name} 点赞了"
                elif activity['activity_type'] == 'liked_reply':
                    description = f"您的回复 '{activity['reply_content'][:20] if activity['reply_content'] else '...'}' 被 {actor_name} 点赞了"
                elif activity['activity_type'] == 'badge_awarded':
                    description = f"获得了“{activity['badge_name'] or '未知徽章'}”徽章"
                elif activity['activity_type'] == 'points_change': 
                     description = f"{'获得' if activity['points_change'] > 0 else '失去'} {abs(activity['points_change'])} CGB点"
                elif activity['activity_type'] == 'edited_post': 
                    description = f"编辑了帖子《{activity['post_title'] or '未知帖子'}》"
                elif activity['activity_type'] == 'deleted_post': 
                    description = f"删除了帖子《{activity['post_title'] or '未知帖子'}》"
                elif activity['activity_type'] == 'updated_nickname': 
                    description = f"修改了显示名称为“{activity['description'].split('为“')[1].strip('”') if '为“' in activity['description'] else '未知名称'}”"
                elif activity['activity_type'] == 'updated_avatar': 
                    description = "修改了个人头像"
                else:
                    description = "进行了未知活动"
            recent_activities.append({
                'type': activity['activity_type'],
                'description': description,
                'created_at': activity['created_at'].isoformat() if activity['created_at'] else None
            })
        user_data['recent_activities'] = recent_activities
        user_badges_raw = fetch_user_db(
            """
            SELECT b.id, b.name, b.description, b.icon_url, ub.awarded_at
            FROM user_badges ub
            JOIN badges b ON ub.badge_id = b.id
            WHERE ub.user_id = %s
            ORDER BY ub.awarded_at DESC
            LIMIT 6
            """,
            (current_user_id,)
        )
        user_badges = []
        for badge in user_badges_raw:
            user_badges.append({
                'id': badge['id'],
                'name': badge['name'],
                'description': badge['description'],
                'icon_url': badge['icon_url'],
                'awarded_at': badge['awarded_at'].isoformat() if badge['awarded_at'] else None
            })
        user_data['user_badges'] = user_badges
        logger.info(f"User profile for UID {current_uid} fetched successfully.")
        return success(user_data, "个人资料获取成功")
    except Exception as e:
        logger.error(f"Error fetching user profile for UID {current_uid}: {e}", exc_info=True)
        return error(f"获取个人资料失败: {str(e)}", 500)

@app.route('/api/user/profile/customization', methods=['PUT'])
@login_required
def update_profile_customization():
    data = request.get_json()
    action = data.get('action') 
    
    if action == 'update_color':
        # 允许的预设颜色值 
        color_val = data.get('color')
        if color_val and len(color_val) > 100:
            return error("颜色代码过长", 400)
        # 重置
        execute_user_db('UPDATE users SET nickname_color = %s WHERE id = %s', (color_val, g.user_id))
        return success(None, "昵称颜色已更新")
    elif action == 'update_title':
        title_id = data.get('title_id')
        if title_id is None:
            # 卸下称号
            execute_user_db('UPDATE users SET selected_title_id = NULL WHERE id = %s', (g.user_id,))
            return success(None, "称号已卸下")
        # 验证是否拥有
        has_title = fetch_user_db(
            'SELECT 1 FROM user_titles WHERE user_id = %s AND title_id = %s',
            (g.user_id, title_id),
            one=True
        )
        if not has_title:
            return error("您未拥有该称号", 403)
        execute_user_db('UPDATE users SET selected_title_id = %s WHERE id = %s', (title_id, g.user_id))
        return success(None, "称号佩戴成功")
    return error("无效的操作类型", 400)

# 修改用户显示名路由
@app.route('/api/user/update_nickname', methods=['PUT'])
@login_required
def update_user_nickname_route():
    logger.info(f"User {g.user_id} ({g.uid}) attempting to update nickname.")
    data = request.get_json()
    new_display_name = data.get('display_name')
    if not new_display_name or not new_display_name.strip():
        return error("显示名称不能为空", 400)
    new_display_name = new_display_name.strip()
    current_user = fetch_user_db('SELECT display_name, cgb_points FROM users WHERE id = %s', (g.user_id,), one=True)
    if not current_user:
        return error("用户不存在", 404)
    if current_user['display_name'] == new_display_name:
        return error("新名称与当前名称相同，无需修改", 400)

    # 检查CGB点数是否足够
    COST_CGB_POINTS = 10
    if current_user['cgb_points'] < COST_CGB_POINTS:
        return error(f"您的 CGB 点数不足 {COST_CGB_POINTS} 点，无法修改名称。", 403)

    try:
        execute_user_db('UPDATE users SET display_name = %s WHERE id = %s', (new_display_name, g.user_id))
        # 扣除点数并记录活动日志
        update_user_cgb_points(g.user_id, -COST_CGB_POINTS, f"修改显示名称为“{new_display_name}”", related_type='user_action')
        add_activity_log(g.user_id, 'updated_nickname', actor_uid=g.uid, description=f"修改了显示名称为“{new_display_name}”")
        return success(None, "显示名称更新成功")
    except Exception as e:
        logger.error(f"Error updating nickname for user {g.user_id}: {e}", exc_info=True)
        return error(f"修改显示名称失败: {str(e)}", 500)


@app.route('/api/user/posts', methods=['GET'])
@login_required
def get_user_all_posts():
    logger.info(f"Get all posts for UID: {g.uid}.")
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 10))
    offset = (page - 1) * limit

    try:
        posts_raw = fetch_user_db(
            'SELECT id, title, created_at, likes_count FROM forum_posts WHERE user_id = %s AND status = 1 ORDER BY created_at DESC LIMIT %s OFFSET %s',
            (g.user_id, limit, offset)
        )
        total_posts_data = fetch_user_db('SELECT COUNT(id) AS count FROM forum_posts WHERE user_id = %s AND status = 1', (g.user_id,), one=True)
        total_posts = total_posts_data['count'] if total_posts_data else 0

        posts = []
        for post in posts_raw:
            posts.append({
                'id': post['id'],
                'title': post['title'],
                'created_at': post['created_at'].isoformat() if post['created_at'] else None,
                'likes_count': post['likes_count']
            })
        logger.info(f"Fetched {len(posts)} posts for UID {g.uid}, page {page}.")
        return success({
            'posts': posts,
            "total": total_posts,
            "page": page,
            "limit": limit
        }, "用户帖子列表获取成功")
    except Exception as e:
        logger.error(f"Error fetching all posts for UID {g.uid}: {e}", exc_info=True)
        return error(f"获取用户帖子失败: {str(e)}", 500)


@app.route('/api/cgbpassword_forget', methods=['POST'])
@limiter.limit("5 per minute; 20 per hour")
def cgbpassword_forget():
    data = request.get_json() or {}
    action = (data.get('action') or '').strip().lower()

    if not action:
        action = 'request' if 'email' in data and 'reset_token' not in data else 'reset'

    # --------------------------
    # Step A: 申请重置（发送令牌）
    # --------------------------
    if action == 'request':
        email = (data.get('email') or '').strip()
        captcha_id = (data.get('captcha_id') or '').strip()
        captcha_value = (data.get('captcha_value') or '').strip().lower()

        if not email:
            return error("请输入邮箱", 400)
        if not captcha_id or not captcha_value:
            return error("请输入验证码", 400)

        # 校验图形验证码
        captcha_valid = False
        if redis_client:
            try:
                stored_value = redis_client.get(f"captcha:{captcha_id}")
                if stored_value:
                    if stored_value == captcha_value:
                        captcha_valid = True
                        redis_client.delete(f"captcha:{captcha_id}")
                        logger.debug(f"Captcha {captcha_id} verified via Redis (password forget).")
                    else:
                        redis_client.delete(f"captcha:{captcha_id}")
                        return error("验证码不正确", 400)
            except Exception as e:
                logger.error(f"Redis error when verifying captcha for password forget: {e}")

        if not captcha_valid:
            captcha_record = fetch_user_db(
                'SELECT value, expires_at, is_used FROM captcha_store WHERE id = %s',
                (captcha_id,),
                one=True
            )

            if not captcha_record:
                return error("验证码无效或已过期", 400)

            if captcha_record['is_used']:
                return error("验证码已使用，请刷新", 400)

            if captcha_record['expires_at'] < datetime.datetime.now(timezone.utc):
                execute_user_db('UPDATE captcha_store SET is_used = TRUE WHERE id = %s', (captcha_id,))
                return error("验证码已过期，请刷新", 400)

            if captcha_record['value'] == captcha_value:
                captcha_valid = True
                execute_user_db('UPDATE captcha_store SET is_used = TRUE WHERE id = %s', (captcha_id,))
                logger.debug(f"Captcha {captcha_id} verified via DB (password forget).")
            else:
                execute_user_db('UPDATE captcha_store SET is_used = TRUE WHERE id = %s', (captcha_id,))
                return error("验证码不正确", 400)

        # 不暴露邮箱是否存在（防枚举）
        user = fetch_user_db('SELECT id, email FROM users WHERE email = %s', (email,), one=True)

        debug_token = None
        try:
            # 统一生成短期重置令牌
            exp_minutes = int(os.getenv('PASSWORD_RESET_EXP_MINUTES', 15))
            payload = {
                'email': email,
                'purpose': 'password_reset',
                'exp': datetime.datetime.now(timezone.utc) + timedelta(minutes=exp_minutes),
                'iat': datetime.datetime.now(timezone.utc)
            }
            reset_token = jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')

            # 生产应通过邮件下发，此处仅记录日志；
            logger.info(f"Password reset token generated for {email} (exists={bool(user)}). TTL={exp_minutes}m")
            if app.debug:
                debug_token = reset_token
        except Exception as e:
            logger.error(f"Failed to create password reset token: {e}", exc_info=True)
            reset_token = None

        # 若邮箱存在且生成成功，尝试通过SMTP下发邮件
        if user and reset_token:
            try:
                # 计算前端重置链接
                base = os.getenv('FRONTEND_BASE_URL')
                if not base:
                    base = request.headers.get('Origin') or request.headers.get('Referer')
                if base:
                    base = base.rstrip('/')
                else:
                    base = request.host_url.rstrip('/')
                reset_link = f"{base}/terminal/login?reset_token={reset_token}"

                # 发送邮件
                sent = send_password_reset_email(email, reset_link)
                if not sent:
                    logger.warning(f"Password reset email not sent (SMTP not configured or failed) for {email}")
            except Exception as e:
                logger.error(f"Error sending password reset email to {email}: {e}", exc_info=True)

        # 统一成功响应
        resp_data = {"message": "如果该邮箱存在，我们已向其发送了重置指引。"}
        if app.debug and debug_token:
            # 仅在调试环境返回，避免生产泄露
            resp_data["debug_reset_token"] = debug_token
        return success(resp_data, "请求已受理")

    # 执行重置（使用令牌）
    if action == 'reset':
        reset_token = (data.get('reset_token') or '').strip()
        new_password = data.get('new_password') or ''
        confirm_password = data.get('confirm_password') or ''

        if not reset_token:
            return error("缺少重置令牌", 400)
        if not new_password:
            return error("请输入新密码", 400)
        if new_password != confirm_password:
            return error("两次输入的密码不一致", 400)

        # 简单强度校验，与注册保持一致
        if len(new_password) < 8 or not any(c.isdigit() for c in new_password) or not any(c.isalpha() for c in new_password):
            return error("密码至少8位，且包含字母和数字", 400)

        # 校验令牌并提取邮箱
        try:
            payload = jwt.decode(reset_token, app.config['SECRET_KEY'], algorithms=['HS256'])
            if payload.get('purpose') != 'password_reset':
                return error("无效的重置令牌", 400)
            email = payload.get('email')
            if not email:
                return error("无效的重置令牌", 400)
        except jwt.ExpiredSignatureError:
            return error("重置链接已过期，请重新申请", 400)
        except jwt.InvalidTokenError:
            return error("无效的重置令牌", 400)
        except Exception as e:
            logger.error(f"Unexpected error decoding reset token: {e}")
            return error("令牌解析失败", 400)

        # 查找用户并更新密码
        user = fetch_user_db('SELECT id FROM users WHERE email = %s', (email,), one=True)
        if not user:
            # 统一泛化错误，避免暴露
            return error("无效或已失效的重置令牌", 400)

        try:
            new_hash = hash_password(new_password)
            execute_user_db('UPDATE users SET password_hash = %s WHERE id = %s', (new_hash, user['id']))
            logger.info(f"Password reset success for {email} (user_id={user['id']}).")
            return success(None, "密码重置成功，请使用新密码登录")
        except Exception as e:
            logger.error(f"Password reset DB update failed for {email}: {e}", exc_info=True)
            return error("密码重置失败：服务器内部错误", 500)

    return error("无效的 action 参数，应为 request 或 reset", 400)


@app.route('/api/user/activities', methods=['GET'])
@login_required
def get_user_all_activities():
    logger.info(f"Get all activities for UID: {g.uid}.")
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 10))
    offset = (page - 1) * limit

    try:
        activities_raw = fetch_user_db(
            """
            SELECT al.activity_type, al.related_id, al.related_type, al.description, al.created_at, al.points_change,
                   u_actor.display_name AS actor_display_name, u_actor.uid AS actor_uid,
                   fp.title AS post_title, fr.content AS reply_content, b.name AS badge_name
            FROM activity_log al
            LEFT JOIN users u_actor ON al.actor_uid = u_actor.uid
            LEFT JOIN forum_posts fp ON al.related_id = fp.id AND al.related_type = 'post'
            LEFT JOIN forum_replies fr ON al.related_id = fr.id AND al.related_type = 'reply'
            LEFT JOIN badges b ON al.related_id = b.id AND al.related_type = 'badge'
            WHERE al.user_id = %s
            ORDER BY al.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (g.user_id, limit, offset)
        )
        total_activities_data = fetch_user_db('SELECT COUNT(id) AS count FROM activity_log WHERE user_id = %s', (g.user_id,), one=True)
        total_activities = total_activities_data['count'] if total_activities_data else 0

        activities = []
        for activity in activities_raw:
            description = activity['description']
            if not description:
                actor_name = activity['actor_display_name'] or activity['actor_uid'] or '某用户'
                if activity['activity_type'] == 'posted_thread':
                    description = f"发布了帖子《{activity['post_title'] or '未知帖子'}》"
                elif activity['activity_type'] == 'replied_post':
                    post_title_for_reply = fetch_user_db('SELECT title FROM forum_posts WHERE id = %s', (activity['related_id'],), one=True)
                    description = f"回复了帖子《{post_title_for_reply['title'] if post_title_for_reply else '未知帖子'}》"
                elif activity['activity_type'] == 'liked_post':
                    description = f"您的帖子《{activity['post_title'] or '未知帖子'}》被 @{actor_name} 点赞了"
                elif activity['activity_type'] == 'liked_reply':
                    description = f"您的回复 '{activity['reply_content'][:20] if activity['reply_content'] else '...'}' 被 @{actor_name} 点赞了"
                elif activity['activity_type'] == 'badge_awarded':
                    description = f"获得了“{activity['badge_name'] or '未知徽章'}”徽章"
                elif activity['activity_type'] == 'points_change':
                     description = f"{'获得' if activity['points_change'] > 0 else '失去'} {abs(activity['points_change'])} CGB点"
                elif activity['activity_type'] == 'edited_post':
                    description = f"编辑了帖子《{activity['post_title'] or '未知帖子'}》"
                elif activity['activity_type'] == 'deleted_post':
                    description = f"删除了帖子《{activity['post_title'] or '未知帖子'}》"
                elif activity['activity_type'] == 'updated_nickname':
                    description = f"修改了显示名称为“{activity['description'].split('为“')[1].strip('”') if '为“' in activity['description'] else '未知名称'}”"
                else:
                    description = "进行了未知活动"

            activities.append({
                'type': activity['activity_type'],
                'description': description,
                'created_at': activity['created_at'].isoformat() if activity['created_at'] else None
            })
        logger.info(f"Fetched {len(activities)} activities for UID {g.uid}, page {page}.")
        return success({
            'activities': activities,
            "total": total_activities,
            "page": page,
            "limit": limit
        }, "用户活动列表获取成功")
    except Exception as e:
        logger.error(f"Error fetching all activities for UID {g.uid}: {e}", exc_info=True)
        return error(f"获取用户活动失败: {str(e)}", 500)

@app.route('/api/user/badges', methods=['GET'])
@login_required
def get_user_all_badges():
    logger.info(f"Get all badges for UID: {g.uid}.")
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 10))
    offset = (page - 1) * limit

    try:
        badges_raw = fetch_user_db(
            """
            SELECT b.id, b.name, b.description, b.icon_url, ub.awarded_at
            FROM user_badges ub
            JOIN badges b ON ub.badge_id = b.id
            WHERE ub.user_id = %s
            ORDER BY ub.awarded_at DESC
            LIMIT %s OFFSET %s
            """,
            (g.user_id, limit, offset)
        )
        total_badges_data = fetch_user_db('SELECT COUNT(id) AS count FROM user_badges WHERE user_id = %s', (g.user_id,), one=True)
        total_badges = total_badges_data['count'] if total_badges_data else 0

        badges = []
        for badge in badges_raw:
            badges.append({
                'id': badge['id'],
                'name': badge['name'],
                'description': badge['description'],
                'icon_url': badge['icon_url'],
                'awarded_at': badge['awarded_at'].isoformat() if badge['awarded_at'] else None
            })
        logger.info(f"Fetched {len(badges)} badges for UID {g.uid}, page {page}.")
        return success({
            'badges': badges,
            "total": total_badges,
            "page": page,
            "limit": limit
        }, "用户徽章列表获取成功")
    except Exception as e:
        logger.error(f"Error fetching all badges for UID {g.uid}: {e}", exc_info=True)
        return error(f"获取用户徽章失败: {str(e)}", 500)

#####################################################
#                                                   #
#                管理员接口 ADMIN                    #
#       此处编写的都是与前端管理员后台有关的接口        #
#                                                   #
#####################################################

@app.route('/api/admin/dashboard', methods=['GET'])
@login_required
@role_required('admin')
def admin_dashboard():
    logger.info(f"Admin dashboard requested by admin UID: {g.uid}.")
    try:
        total_users_data = fetch_user_db("SELECT COUNT(id) AS count FROM users", one=True)
        total_users = total_users_data['count'] if total_users_data else 0

        total_posts_data = fetch_user_db("SELECT COUNT(id) AS count FROM forum_posts", one=True)
        total_posts = total_posts_data['count'] if total_posts_data else 0

        new_users_today_data = fetch_user_db("SELECT COUNT(id) AS count FROM users WHERE created_at >= %s", (datetime.datetime.now(timezone.utc) - datetime.timedelta(days=1),), one=True)
        new_users_today = new_users_today_data['count'] if new_users_today_data else 0

        stats = {
            "total_users": total_users,
            "total_posts": total_posts,
            "new_users_today": new_users_today
        }
        logger.info("Admin dashboard data fetched successfully.")
        return success(stats, "管理员仪表盘数据")
    except Exception as e:
        logger.error(f"Error fetching admin dashboard data for UID {g.uid}: {e}", exc_info=True)
        return error(f"获取管理员仪表盘数据失败: {str(e)}", 500)

@app.route('/api/admin/grant_supporter_benefits', methods=['POST'])
@login_required
@role_required('admin')
def grant_supporter_benefits():
    """
    一键发放：永久双倍卡、抽奖x5、战术小队x2、首发者称号、首发者徽章
    """
    data = request.get_json()
    target_uid = data.get('target_uid')
    target_user = fetch_user_db('SELECT id, display_name FROM users WHERE uid = %s', (target_uid,), one=True)
    if not target_user:
        return error("目标用户不存在", 404)
    t_id = target_user['id']
    
    try:
        execute_user_db('''
            UPDATE users 
            SET cgb_booster_active = TRUE,
                lottery_tickets = lottery_tickets + 5,
                squad_limit = GREATEST(squad_limit, 2)
            WHERE id = %s
        ''', (t_id,))
        # 【首发者】称号 
        title_data = fetch_user_db('SELECT id, name FROM titles WHERE name = "首发者"', one=True)
        if title_data:
            # 防止重复报错
            execute_user_db(
                'INSERT IGNORE INTO user_titles (user_id, title_id, is_permanent) VALUES (%s, %s, TRUE)',
                (t_id, title_data['id'])
            )
        # 【首发者】徽章 
        badge_data = fetch_user_db('SELECT id, name FROM badges WHERE name = "首发者"', one=True)
        if badge_data:
             execute_user_db(
                'INSERT IGNORE INTO user_badges (user_id, badge_id) VALUES (%s, %s)',
                (t_id, badge_data['id'])
            )
        # 日志
        log_desc = "获得了【首发者权益包】：永久双倍增益、抽奖次数x5、战术小队上限x2、首发者称号与徽章"
        add_activity_log(t_id, 'gift_received', actor_uid=g.uid, description=log_desc)
        return success(None, f"已成功向用户 {target_user['display_name']} 发放首发者权益包")
    except Exception as e:
        logger.error(f"Grant benefits error: {e}")
        return error("发放失败", 500)

@app.route('/api/admin/get_users', methods=['GET'])
@login_required
@role_required('admin')
def admin_get_users():
    """
    获取用户列表，支持按角色筛选 (admin/user)
    """
    role = request.args.get('role', 'user') # 默认获取普通用户
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    offset = (page - 1) * limit
    logger.info(f"Admin {g.uid} fetching users list. Role: {role}, Page: {page}")
    try:
        # 查询用户
        sql = """
            SELECT id, uid, display_name, email, true_name, cgb_points,
                   level, created_at, last_activity, role
            FROM users
            WHERE role = %s
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        users_raw = fetch_user_db(sql, (role, limit, offset))
        # 查询总数
        count_sql = "SELECT COUNT(id) as count FROM users WHERE role = %s"
        total_data = fetch_user_db(count_sql, (role,), one=True)
        total = total_data['count'] if total_data else 0
        # 格式化时间
        formatted_users = []
        for u in users_raw:
            formatted_users.append({
                "uid": u['uid'],
                "display_name": u['display_name'],
                "email": u['email'],
                "true_name": u['true_name'],
                "cgb_points": u['cgb_points'],
                "level": u['level'],
                "created_at": u['created_at'].strftime('%Y-%m-%d') if u['created_at'] else 'N/A',
                "last_active": u['last_activity'].strftime('%Y-%m-%d %H:%M') if u['last_activity'] else 'Never'
            })
        return success({
            "users": formatted_users,
            "total": total,
            "page": page,
            "limit": limit
        })
    except Exception as e:
        logger.error(f"Error fetching users: {e}", exc_info=True)
        return error(f"获取用户列表失败: {str(e)}", 500)


@app.route('/api/admin/publish_product', methods=['POST'])
@login_required
@role_required('admin')
def admin_publish_product():
    """
    管理员发布新产品
    """
    data = request.get_json()
    logger.info(f"Admin {g.uid} publishing product: {data.get('name')}")
    # 必填字段检查
    required_fields = ['name', 'brand', 'category', 'price', 'image']
    if not all(field in data for field in required_fields):
        return error("缺少必填字段 (name, brand, category, price, image)", 400)
    try:
        brand = data.get('brand')
        name = data.get('name')
        en_name = data.get('en_name', '')
        category = data.get('category')
        price = data.get('price')
        image = data.get('image')
        buy_url = data.get('buy_url', '')
        buy_platform = data.get('buy_platform', '')
        # 自动翻译英文名称
        if not en_name and name:
            en_name = translate_with_chatgpt(name, 'en-us')
        tags_list = data.get('tags', [])
        tags_json = json.dumps(tags_list) if isinstance(tags_list, list) else '[]'
        hot_score = data.get('hot_score', 0)
        is_new = True
        # 生成产品ID
        max_id_result = fetch_user_db("SELECT id FROM products ORDER BY CAST(SUBSTRING(id, 2) AS UNSIGNED) DESC LIMIT 1", one=True)
        if max_id_result and max_id_result['id']:
            last_num = int(max_id_result['id'][1:])
            product_id = f"p{last_num + 1}"
        else:
            product_id = "p1"
        sql = """
            INSERT INTO products
            (id, brand, name, en_name, category, price, hot_score, is_new, image, tags, buy_url, buy_platform, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        now = datetime.datetime.now(timezone.utc)
        execute_user_db(sql, (
            product_id, brand, name, en_name, category, price, hot_score, is_new, image, tags_json, buy_url, buy_platform, now
        ))
        return success(None, "产品发布成功")
    except Exception as e:
        logger.error(f"Error publishing product: {e}", exc_info=True)
        return error(f"发布产品失败: {str(e)}", 500)


@app.route('/api/admin/publish_announcement', methods=['POST'])
@login_required
@role_required('admin')
def admin_publish_announcement():
    """
    管理员发布完整公告：支持多语言翻译、链接、附件、影响范围。
    """
    data = request.get_json()
    logger.info(f"Admin {g.uid} publishing complex announcement.")
    #  获取基础字段
    title_cn = data.get('title_zh_cn')
    content_cn = data.get('content_zh_cn')
    if not title_cn or not content_cn:
        return error("简体中文标题和内容是必填项", 400)
    # 自动翻译逻辑 
    t_en = data.get('title_en_us') or translate_with_chatgpt(title_cn, 'en-us')
    c_en = data.get('content_en_us') or translate_with_chatgpt(content_cn, 'en-us')
    t_hk = data.get('title_zh_hk') or translate_with_chatgpt(title_cn, 'zh-hk')
    c_hk = data.get('content_zh_hk') or translate_with_chatgpt(content_cn, 'zh-hk')
    t_tw = data.get('title_zh_tw') or translate_with_chatgpt(title_cn, 'zh-tw')
    c_tw = data.get('content_zh_tw') or translate_with_chatgpt(content_cn, 'zh-tw')
    try:
        sql_main = """
            INSERT INTO announcements (
                title_zh_cn, content_zh_cn, title_en_us, content_en_us,
                title_zh_hk, content_zh_hk, title_zh_tw, content_zh_tw,
                category, status, publish_date, effective_date, end_date,
                is_pinned, pin_priority, impact_scope
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        # 处理JSON和时间
        impact_scope = json.dumps(data.get('impact_scope', {}))
        now = datetime.datetime.now(timezone.utc)
        publish_date = data.get('publish_date') or now
        effective_date = data.get('effective_date') or now
        end_date = data.get('end_date')
        params_main = (
            title_cn, content_cn, t_en, c_en,
            t_hk, c_hk, t_tw, c_tw,
            data.get('category', 'system_maintenance'),
            data.get('status', 'new'),
            publish_date, effective_date, end_date,
            data.get('is_pinned', False),
            data.get('pin_priority', 0),
            impact_scope
        )
        announcement_id = execute_user_db(sql_main, params_main)
        if not announcement_id:

            res = fetch_user_db("SELECT LAST_INSERT_ID() as id", one=True)
            announcement_id = res['id']
        links = data.get('links', []) # 格式: [{url, link_text, is_terms_of_service}]
        for link in links:
            execute_user_db(
                "INSERT INTO announcement_links (announcement_id, url, link_text, is_terms_of_service) VALUES (%s, %s, %s, %s)",
                (announcement_id, link.get('url'), link.get('link_text'), link.get('is_terms_of_service', False))
            )
        # 插入附件表announcement_attachments
        attachments = data.get('attachments', []) 
        for att in attachments:
            execute_user_db(
                "INSERT INTO announcement_attachments (announcement_id, filename, file_url, file_size, file_type) VALUES (%s, %s, %s, %s, %s)",
                (announcement_id, att.get('filename'), att.get('file_url'), att.get('file_size', 0), att.get('file_type', ''))
            )
        return success({"id": announcement_id}, "公告及其关联内容发布成功 (已同步翻译)")
    except Exception as e:
        logger.error(f"Error publishing announcement: {e}", exc_info=True)
        return error(f"发布失败: {str(e)}", 500)


# 设置用户身份
@app.route('/api/admin/set_user_role', methods=['POST'])
@login_required
@role_required('admin')
def admin_set_user_role():
    data = request.get_json()
    uid = data.get('uid')
    role = data.get('role')
    if not uid or not role:
        return error("缺少必要参数", 400)
    try:
        execute_user_db("UPDATE users SET role = %s WHERE uid = %s", (role, uid))
        return success(None, f"已设置用户 {uid} 为 {role}")
    except Exception as e:
        logger.error(f"Error setting user role: {e}", exc_info=True)
        return error(f"设置失败: {str(e)}", 500)
# 封禁用户
@app.route('/api/admin/ban_user', methods=['POST'])
@login_required
@role_required('admin')
def admin_ban_user():
    data = request.get_json()
    uid = data.get('uid')
    duration = data.get('duration')
    if not uid or not duration:
        return error("缺少必要参数", 400)
    try:
        if duration == 'permanent':
            ban_until = datetime.datetime(2099, 12, 31, tzinfo=timezone.utc)
        else:
            hours_map = {'1h': 1, '6h': 6, '1d': 24, '7d': 168, '30d': 720}
            hours = hours_map.get(duration, 168)
            ban_until = datetime.datetime.now(timezone.utc) + datetime.timedelta(hours=hours)
        execute_user_db("UPDATE users SET banned_until = %s WHERE uid = %s", (ban_until, uid))
        return success(None, f"已封禁用户 {uid}")
    except Exception as e:
        logger.error(f"Error banning user: {e}", exc_info=True)
        return error(f"封禁失败: {str(e)}", 500)

# 删除、移除用户
@app.route('/api/admin/user/<uid>', methods=['DELETE'])
@login_required
@role_required('admin')
def admin_delete_user(uid):
    try:
        execute_user_db("DELETE FROM users WHERE uid = %s", (uid,))
        return success(None, f"已删除用户 {uid}")
    except Exception as e:
        logger.error(f"Error deleting user: {e}", exc_info=True)
        return error(f"删除失败: {str(e)}", 500)
# 重置用户昵称
@app.route('/api/admin/reset_nickname', methods=['POST'])
@login_required
@role_required('admin')
def admin_reset_nickname():
    data = request.get_json()
    uid = data.get('uid')
    new_nickname = data.get('new_nickname', '默认用户')
    if not uid:
        return error("缺少用户ID", 400)
    try:
        execute_user_db("UPDATE users SET display_name = %s WHERE uid = %s", (new_nickname, uid))
        return success(None, f"已重置用户 {uid} 昵称")
    except Exception as e:
        logger.error(f"Error resetting nickname: {e}", exc_info=True)
        return error(f"重置失败: {str(e)}", 500)

# 产品API路由
@app.route('/api/products', methods=['GET'])
def get_all_products():
    logger.info("Received request for /api/products")
    try:
        products_data = fetch_user_db("""
            SELECT 
                id, brand, name, en_name, category, price, hot_score AS hotScore, 
                is_new AS isNew, image, tags, buy_url AS buyUrl, 
                buy_platform AS buyPlatform, favorites, likes, created_at AS createdAt
            FROM products
            ORDER BY created_at DESC
        """)
        # 处理数据格式 
        processed_products = []
        for product in products_data:
            if product['tags']:
                try:
                    product['tags'] = json.loads(product['tags'])
                except json.JSONDecodeError:
                    product['tags'] = [] # 解析失败则设为空列表
            else:
                product['tags'] = [] # 如果tags为NULL也设为空列表
            if product['createdAt']:
                product['createdAt'] = product['createdAt'].isoformat() # 转换为 ISO 格式字符串
            processed_products.append(product)
        logger.info(f"Successfully fetched {len(processed_products)} products.")
        return success(data=processed_products)
    except Exception as e:
        logger.error(f"Error fetching products: {e}", exc_info=True)
        return error(f"获取产品数据失败: {str(e)}", 500)

# 更新产品
@app.route('/api/admin/product/<string:product_id>', methods=['PUT'])
@login_required
@role_required('admin')
def admin_update_product(product_id):
    data = request.get_json()
    try:
        updates = []
        params = []
        if 'price' in data:
            updates.append("price = %s")
            params.append(data['price'])
        if 'discount' in data:
            updates.append("discount = %s")
            params.append(data['discount'])
        if not updates:
            return error("没有可更新的字段", 400)
        params.append(product_id)
        sql = f"UPDATE products SET {', '.join(updates)} WHERE id = %s"
        execute_user_db(sql, tuple(params))
        return success(None, "产品更新成功")
    except Exception as e:
        logger.error(f"Error updating product: {e}", exc_info=True)
        return error(f"更新失败: {str(e)}", 500)

# 删除产品
@app.route('/api/admin/product/<string:product_id>', methods=['DELETE'])
@login_required
@role_required('admin')
def admin_delete_product(product_id):
    try:
        execute_user_db("DELETE FROM products WHERE id = %s", (product_id,))
        return success(None, "产品删除成功")
    except Exception as e:
        logger.error(f"Error deleting product: {e}", exc_info=True)
        return error(f"删除失败: {str(e)}", 500)

# 切换产品显示状态
@app.route('/api/admin/product/<string:product_id>/toggle_visibility', methods=['POST'])
@login_required
@role_required('admin')
def admin_toggle_product_visibility(product_id):
    try:
        execute_user_db("UPDATE products SET is_visible = NOT is_visible WHERE id = %s", (product_id,))
        return success(None, "产品状态切换成功")
    except Exception as e:
        logger.error(f"Error toggling product visibility: {e}", exc_info=True)
        return error(f"切换失败: {str(e)}", 500)

# 上传附件
@app.route('/api/admin/upload_file', methods=['POST'])
@login_required
@role_required('admin')
def admin_upload_file():
    if 'file' not in request.files:
        return error("没有文件", 400)
    file = request.files['file']
    if file.filename == '':
        return error("文件名为空", 400)
    try:
        import time
        ext = os.path.splitext(file.filename)[1].lstrip('.')
        timestamp = int(time.time())
        folder_name_plain = f"{ext.upper()}{g.uid}{timestamp}"
        folder_name_encrypted = hashlib.md5(folder_name_plain.encode()).hexdigest()
        upload_dir = os.path.join('/www/wwwroot/cgbgear.cn/files', folder_name_encrypted)
        os.makedirs(upload_dir, exist_ok=True)
        random_name = f"{uuid.uuid4().hex}.{ext}"
        file_path = os.path.join(upload_dir, random_name)
        file.save(file_path)
        file_url = f"https://cgbgear.cn/files/{folder_name_encrypted}/{random_name}"
        return success({"url": file_url}, "文件上传成功")
    except Exception as e:
        logger.error(f"Error uploading file: {e}", exc_info=True)
        return error(f"上传失败: {str(e)}", 500)


def _get_localized_field(item, field_prefix, lang):
    # This is your existing helper function
    if lang == 'en-us' and item.get(f'{field_prefix}_en_us'):
        return item[f'{field_prefix}_en_us']
    if lang == 'zh-hk' and item.get(f'{field_prefix}_zh_hk'):
        return item[f'{field_prefix}_zh_hk']
    if lang == 'zh-tw' and item.get(f'{field_prefix}_zh_tw'):
        return item[f'{field_prefix}_zh_tw']
    if item.get(f'{field_prefix}_zh_cn'):
        return item[f'{field_prefix}_zh_cn']
    if item.get(f'{field_prefix}_en_us'): # Fallback
        return item[f'{field_prefix}_en_us']
    return ""

@app.route('/api/announcement', methods=['GET'])
def get_announcements():
    """
    获取网站公告列表，支持分页、语言、日期、分类和状态过滤。
    
    Query Params:
        page (int): 当前页码, 默认为 1
        limit (int): 每页条数, 默认为 10
        lang (str): 语言代码 (e.g., 'zh-cn', 'en-us', 'zh-hk', 'zh-tw'), 默认为 'zh-cn'
        date (str): YYYY-MM-DD 格式，用于筛选特定日期的公告
        category (str): 公告分类 (e.g., 'system_maintenance', 'policy_update')
        status (str): 公告状态 (e.g., 'new', 'ongoing', 'ended')
    """
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 100)) # 公告通常一次性加载某个日期的所有公告
    offset = (page - 1) * limit
    lang = request.args.get('lang', 'zh-cn')
    
    # Filter parameters
    date_filter = request.args.get('date') # YYYY-MM-DD
    category_filter = request.args.get('category')
    status_filter = request.args.get('status')

    sql_base = """
        SELECT
            a.id,
            a.title_zh_cn, a.title_en_us, a.title_zh_hk, a.title_zh_tw,
            a.content_zh_cn, a.content_en_us, a.content_zh_hk, a.content_zh_tw,
            a.category, a.status, a.publish_date, a.effective_date, a.end_date,
            a.is_pinned, a.pin_priority, a.impact_scope,
            -- 聚合链接数据: id||url||link_text||is_terms_of_service
            GROUP_CONCAT(DISTINCT CONCAT_WS('||', al.id, al.url, IFNULL(al.link_text, ''), al.is_terms_of_service) SEPARATOR ';;') AS links_data,
            -- 聚合附件数据: id||filename||file_url||file_size||file_type
            GROUP_CONCAT(DISTINCT CONCAT_WS('||', aa.id, aa.filename, aa.file_url, aa.file_size, aa.file_type) SEPARATOR ';;') AS attachments_data
        FROM
            announcements a
        LEFT JOIN
            announcement_links al ON a.id = al.announcement_id
        LEFT JOIN
            announcement_attachments aa ON a.id = aa.announcement_id
    """
    conditions = []
    filter_params = []
    conditions.append("a.publish_date <= CURDATE() + INTERVAL 1 MONTH")
    conditions.append("a.publish_date >= CURDATE() - INTERVAL 6 MONTH")
    conditions.append("a.effective_date <= NOW()")
    conditions.append("(a.end_date IS NULL OR a.end_date >= NOW())")

    if date_filter:
        conditions.append("DATE(a.publish_date) = %s")
        filter_params.append(date_filter)
    if category_filter:
        conditions.append("a.category = %s")
        filter_params.append(category_filter)
    if status_filter:
        conditions.append("a.status = %s")
        filter_params.append(status_filter)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    
    # 排序规则：
    # 1. pin_priority 降序 (2 > 1 > 0)
    # 2. publish_date 降序 (最新发布在前)
    order_clause = "ORDER BY a.pin_priority DESC, a.publish_date DESC" 
    group_clause = "GROUP BY a.id"
    sql = f"{sql_base} {where_clause} {group_clause} {order_clause} LIMIT %s OFFSET %s"
    params = list(filter_params) + [limit, offset]

    try:
        announcements_raw = fetch_user_db(sql, tuple(params))
        # 获取总数 (用于分页，如果需要前端显示总页数)
        count_sql = f"SELECT COUNT(DISTINCT a.id) AS total FROM announcements a {where_clause}"
        total_count_result = fetch_user_db(count_sql, tuple(filter_params), one=True)
        total_announcements = total_count_result['total'] if total_count_result else 0

        formatted_announcements = []
        for ann in announcements_raw:
            # 本地化标题和内容
            title = _get_localized_field(ann, 'title', lang)
            content = _get_localized_field(ann, 'content', lang)
            # 解析 links_data
            links = []
            if ann.get('links_data'):
                for link_str in ann['links_data'].split(';;'):
                    parts = link_str.split('||')
                    if len(parts) == 4:
                        links.append({
                            'id': int(parts[0]),
                            'url': parts[1],
                            'link_text': parts[2] if parts[2] else parts[1], # 如果没有提供链接文本，则使用URL
                            'is_terms_of_service': bool(int(parts[3]))
                        })
            
            # 解析 attachments_data
            attachments = []
            if ann.get('attachments_data'):
                for att_str in ann['attachments_data'].split(';;'):
                    parts = att_str.split('||')
                    if len(parts) == 5:
                        attachments.append({
                            'id': int(parts[0]),
                            'filename': parts[1],
                            'file_url': parts[2],
                            'file_size': int(parts[3]),
                            'file_type': parts[4]
                        })
            
            # 解析 impact_scope (JSON 字符串)
            impact_scope_data = None
            if ann.get('impact_scope') and ann['impact_scope'] != 'null': # 确保不是 None 或 'null'字符串
                try:
                    impact_scope_data = json.loads(ann['impact_scope'])
                except (json.JSONDecodeError, TypeError):
                    impact_scope_data = str(ann['impact_scope']) # 转换为字符串作为回退

            # 读取已读统计与用户头像（最多5个）
            try:
                read_count_row = fetch_user_db(
                    'SELECT COUNT(*) AS cnt FROM user_announcement_read_status WHERE announcement_id = %s',
                    (ann['id'],), one=True
                )
                read_count = read_count_row['cnt'] if read_count_row else 0
            except Exception as _e:
                logger.warning(f"Read count fetch failed for ann {ann['id']}: {_e}")
                read_count = 0

            try:
                readers = fetch_user_db(
                    '''
                    SELECT u.uid, u.display_name AS name, u.avatar_url
                    FROM user_announcement_read_status r
                    JOIN users u ON r.user_id = u.id
                    WHERE r.announcement_id = %s
                    ORDER BY r.read_at DESC
                    LIMIT 5
                    ''',
                    (ann['id'],)
                ) or []
                read_by_users = [
                    {
                        'uid': row.get('uid'),
                        'name': row.get('name') or 'User',
                        'avatar_url': row.get('avatar_url')
                    }
                    for row in readers
                ]
            except Exception as _e:
                logger.warning(f"Read users fetch failed for ann {ann['id']}: {_e}")
                read_by_users = []

            formatted_announcements.append({
                'id': ann['id'],
                'title': title,
                'content': content,
                'category': ann['category'],
                'status': ann['status'],
                'publish_date': ann['publish_date'].isoformat() if ann['publish_date'] else None,
                'effective_date': ann['effective_date'].isoformat() if ann['effective_date'] else None,
                'end_date': ann['end_date'].isoformat() if ann['end_date'] else None,
                'is_pinned': bool(ann['is_pinned']),
                'pin_priority': ann['pin_priority'],
                'impact_scope': impact_scope_data,
                'links': links,
                'attachments': attachments,
                'read_count': read_count,
                'read_by_users': read_by_users
            })

        return success({
            'announcements': formatted_announcements,
            'total': total_announcements,
            'page': page,
            'limit': limit
        })

    except Exception as e:
        logger.error(f"Error fetching announcements: {e}", exc_info=True)
        return error("Failed to fetch announcements.", 500)


@app.route('/api/announcement/<int:announcement_id>/read', methods=['POST'])
@login_required
def mark_announcement_read(announcement_id):
    """Mark an announcement as read by the current user.
    Creates or updates a record in user_announcement_read_status.
    Returns updated read_count and, if needed, basic user info.
    """
    try:
        exists = fetch_user_db('SELECT id FROM announcements WHERE id = %s', (announcement_id,), one=True)
        if not exists:
            return error('Announcement not found', 404)

        sql = (
            'INSERT INTO user_announcement_read_status (user_id, announcement_id, read_at) '
            'VALUES (%s, %s, NOW()) '
            'ON DUPLICATE KEY UPDATE read_at = VALUES(read_at)'
        )
        execute_user_db(sql, (g.user_id, announcement_id))

        count_row = fetch_user_db(
            'SELECT COUNT(*) AS cnt FROM user_announcement_read_status WHERE announcement_id = %s',
            (announcement_id,), one=True
        )
        read_count = count_row['cnt'] if count_row else 0

        me = fetch_user_db('SELECT uid, display_name AS name, avatar_url FROM users WHERE id = %s', (g.user_id,), one=True)

        return success({
            'announcement_id': announcement_id,
            'read_count': read_count,
            'user': {
                'uid': me.get('uid') if me else None,
                'name': me.get('name') if me else None,
                'avatar_url': me.get('avatar_url') if me else None,
            }
        }, 'Marked as read')
    except Exception as e:
        logger.error(f"Error marking announcement {announcement_id} as read: {e}", exc_info=True)
        return error('Failed to mark as read', 500)

@app.route('/api/announcement', methods=['POST'])
def create_announcement():
    """
    创建一个新的公告。
    如果只提供了 title_zh_cn 和 content_zh_cn，则会使用 DeepSeek 自动翻译。
    """
    data = request.get_json()

    title_cn = data.get('title_zh_cn')
    content_cn = data.get('content_zh_cn')

    if not title_cn or not content_cn:
        return error("Fields 'title_zh_cn' and 'content_zh_cn' are required.", 400)

    # 自动翻译逻辑
    # 只有当目标语言字段未提供时，才进行翻译，这允许手动覆盖。
    if not data.get('title_en_us'):
        data['title_en_us'] = translate_with_chatgpt(title_cn, 'en-us')
    if not data.get('content_en_us'):
        data['content_en_us'] = translate_with_chatgpt(content_cn, 'en-us')
    if not data.get('title_zh_tw'):
        data['title_zh_tw'] = translate_with_chatgpt(title_cn, 'zh-tw')
    if not data.get('content_zh_tw'):
        data['content_zh_tw'] = translate_with_chatgpt(content_cn, 'zh-tw')
    if not data.get('title_zh_hk'):
        data['title_zh_hk'] = translate_with_chatgpt(title_cn, 'zh-hk')
    if not data.get('content_zh_hk'):
        data['content_zh_hk'] = translate_with_chatgpt(content_cn, 'zh-hk')
    try:
        sql = """
            INSERT INTO announcements (
                title_zh_cn, content_zh_cn,
                title_en_us, content_en_us,
                title_zh_tw, content_zh_tw,
                title_zh_hk, content_zh_hk,
                category, status, publish_date, effective_date, end_date,
                is_pinned, pin_priority, impact_scope
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            data.get('title_zh_cn'), data.get('content_zh_cn'),
            data.get('title_en_us'), data.get('content_en_us'),
            data.get('title_zh_tw'), data.get('content_zh_tw'),
            data.get('title_zh_hk'), data.get('content_zh_hk'),
            data.get('category'), data.get('status', 'new'), # 默认值
            data.get('publish_date'), data.get('effective_date'), data.get('end_date'),
            data.get('is_pinned', False), data.get('pin_priority', 0),
            json.dumps(data.get('impact_scope')) if data.get('impact_scope') else None 
        )
        new_announcement_id = execute_user_db(sql, params, get_last_id=True) # 

        # 插入announcement_links和announcement_attachments表
        links_data = data.get('links')
        if links_data and new_announcement_id:
            for link in links_data:
                link_sql = "INSERT INTO announcement_links (announcement_id, url, link_text, is_terms_of_service) VALUES (%s, %s, %s, %s)"
                execute_user_db(link_sql, (new_announcement_id, link.get('url'), link.get('link_text'), link.get('is_terms_of_service', False)))
        attachments_data = data.get('attachments')
        if attachments_data and new_announcement_id:
            for attachment in attachments_data:
                att_sql = "INSERT INTO announcement_attachments (announcement_id, filename, file_url, file_size, file_type) VALUES (%s, %s, %s, %s, %s)"
                execute_user_db(att_sql, (new_announcement_id, attachment.get('filename'), attachment.get('file_url'), attachment.get('file_size'), attachment.get('file_type')))
        return success({'id': new_announcement_id, 'message': 'Announcement created successfully with DeepSeek auto-translations.'}, 201)
    except Exception as e:
        logger.error(f"Error creating announcement: {e}", exc_info=True)
        return error("Failed to create announcement.", 500)


@app.route('/api/announcement/<int:announcement_id>', methods=['PUT'])
def update_announcement(announcement_id):
    """
    更新一个已存在的公告。
    如果 title_zh_cn 或 content_zh_cn 被修改，会自动重新翻译。
    """
    data = request.get_json()
    # 检查简体中文内容是否有变动，如果有则触发重新翻译
    title_cn_updated = 'title_zh_cn' in data
    content_cn_updated = 'content_zh_cn' in data
    if title_cn_updated and data['title_zh_cn']:
        title_cn = data['title_zh_cn']
        logger.info(f"Re-translating title for announcement {announcement_id} using DeepSeek.")
        data['title_en_us'] = translate_with_chatgpt(title_cn, 'en-us')
        data['title_zh_tw'] = translate_with_chatgpt(title_cn, 'zh-tw')
        data['title_zh_hk'] = translate_with_chatgpt(title_cn, 'zh-hk')
    if content_cn_updated and data['content_zh_cn']:
        content_cn = data['content_zh_cn']
        logger.info(f"Re-translating content for announcement {announcement_id} using DeepSeek.")
        data['content_en_us'] = translate_with_chatgpt(content_cn, 'en-us')
        data['content_zh_tw'] = translate_with_chatgpt(content_cn, 'zh-tw')
        data['content_zh_hk'] = translate_with_chatgpt(content_cn, 'zh-hk')
    try:
        update_fields = []
        params = []
        all_db_columns = {
            'title_zh_cn', 'content_zh_cn', 'title_en_us', 'content_en_us',
            'title_zh_tw', 'content_zh_tw', 'title_zh_hk', 'content_zh_hk',
            'category', 'status', 'publish_date', 'effective_date', 'end_date',
            'is_pinned', 'pin_priority', 'impact_scope'
        }
        for key, value in data.items():
            if key in all_db_columns:
                # 特殊处理 impact_scope，需要转为 JSON 字符串
                if key == 'impact_scope' and value is not None:
                    update_fields.append(f"{key} = %s")
                    params.append(json.dumps(value))
                elif key in ['publish_date', 'effective_date', 'end_date'] and value is not None:
                    # 假设你的数据库驱动可以处理 ISO 格式字符串直接转换为日期时间
                    update_fields.append(f"{key} = %s")
                    params.append(value) # 保持 ISO 格式
                else:
                    update_fields.append(f"{key} = %s")
                    params.append(value)
        if not update_fields:
            return error("No valid fields to update.", 400)   
        params.append(announcement_id)
        sql = f"UPDATE announcements SET {', '.join(update_fields)} WHERE id = %s"
        
        execute_user_db(sql, tuple(params))
        return success({'id': announcement_id, 'message': 'Announcement updated successfully with DeepSeek auto-translations.'})

    except Exception as e:
        logger.error(f"Error updating announcement {announcement_id}: {e}", exc_info=True)
        return error(f"Failed to update announcement {announcement_id}.", 500)

@app.route('/api/announcement/dates', methods=['GET'])
def get_announcement_dates():
    """
    获取所有公告的唯一发布日期列表，用于时间轴。
    """
    try:
        sql = "SELECT DISTINCT DATE(publish_date) AS date FROM announcements ORDER BY publish_date DESC"
        dates_raw = fetch_user_db(sql)
        # 将 date 对象转换为 YYYY-MM-DD 字符串
        dates = [d['date'].strftime('%Y-%m-%d') for d in dates_raw]
        return success({'dates': dates})
    except Exception as e:
        logger.error(f"Error fetching announcement dates: {e}", exc_info=True)
        return error("Failed to fetch announcement dates.", 500)


# ==============================================================================
#                               TRADE (交易/市集) MODULE
# ==============================================================================

# 辅助: 生成交易分享码 (格式: CGBGEAR + TS + PublishTS + Random6)
def generate_trade_share_code(publish_ts_obj=None):
    if not publish_ts_obj:
        publish_ts_obj = datetime.datetime.now()
    
    current_ts = str(int(time.time() * 1000))
    publish_ts = str(int(publish_ts_obj.timestamp() * 1000))
    
    random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    
    # 组合密文
    return f"CGBGEAR{current_ts}{publish_ts}{random_str}"

# 创建交易 (出物/收物)
@app.route('/api/trade/create', methods=['POST'])
@login_required
def create_trade_item():
    data = request.get_json()
    
    # 必填校验
    required = ['type', 'title', 'region', 'contact_info']
    if not all(k in data for k in required):
        return error("Missing required fields", 400)
    
    item_type = data['type'] # 'sell' or 'buy'
    if item_type not in ['sell', 'buy']:
        return error("Invalid trade type", 400)
        
    try:
        now = datetime.datetime.now()
        share_code = generate_trade_share_code(now)
        
        # 插入主表
        insert_sql = """
            INSERT INTO trade_items 
            (share_code, user_id, type, title, description, price, budget_min, budget_max, 
             condition_level, region, country, contact_info, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        # 提取数据
        price = data.get('price', 0) if item_type == 'sell' else 0
        b_min = data.get('budget_min', 0) if item_type == 'buy' else 0
        b_max = data.get('budget_max', 0) if item_type == 'buy' else 0
        contact_json = json.dumps(data['contact_info']) # Expect dict: {xianyu:..., wechat:...}
        
        params = (
            share_code, g.user_id, item_type, data['title'], data.get('description', ''),
            price, b_min, b_max, 
            data.get('condition', ''), data['region'], data.get('country', ''), 
            contact_json, now
        )
        
        item_id = execute_user_db(insert_sql, params)
        
        if not item_id:
            return error("Failed to create trade item", 500)
            
        # 插入图片 (如果有)
        images = data.get('images', []) 
        if images:
            for idx, img_url in enumerate(images):
                is_primary = (idx == 0)
                execute_user_db(
                    "INSERT INTO trade_images (trade_item_id, image_url, is_primary) VALUES (%s, %s, %s)",
                    (item_id, img_url, is_primary)
                )
        
        return success({"share_code": share_code}, "发布成功")

    except Exception as e:
        logger.error(f"Error creating trade: {e}", exc_info=True)
        return error(f"发布失败: {str(e)}", 500)


# 3. 获取交易列表 (筛选&地图数据)
@app.route('/api/trade/market_items', methods=['GET'])
def get_trade_market_items():
    try:
        # 获取参数
        t_type = request.args.get('type') # sell, buy
        region = request.args.get('region')
        time_filter = request.args.get('time') # today, month
        price_min = request.args.get('price_min')
        price_max = request.args.get('price_max')
        
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        offset = (page - 1) * limit
        
        # 构建 SQL
        where_clauses = ["t.status = 'active'"]
        params = []
        
        if t_type and t_type != 'all':
            where_clauses.append("t.type = %s")
            params.append(t_type)
            
        if region and region != 'all':
            # 支持模糊匹配，例如 "North America"
            where_clauses.append("t.region = %s")
            params.append(region)
            
        if time_filter:
            if time_filter == 'today':
                where_clauses.append("t.created_at >= CURDATE()")
            elif time_filter == 'month':
                where_clauses.append("t.created_at >= DATE_SUB(NOW(), INTERVAL 1 MONTH)")
        
        if price_min:
            where_clauses.append("(t.price >= %s OR t.budget_min >= %s)")
            params.extend([price_min, price_min])
            
        where_sql = " WHERE " + " AND ".join(where_clauses)
        
        # 主查询
        sql = f"""
            SELECT t.id, t.share_code, t.type, t.title, t.price, t.budget_min, t.budget_max, 
                   t.region, t.country, t.created_at, t.view_count, t.want_count,
                   (SELECT image_url FROM trade_images WHERE trade_item_id = t.id AND is_primary = 1 LIMIT 1) as main_image,
                   u.avatar_url as user_avatar, u.display_name, u.true_name
            FROM trade_items t
            JOIN users u ON t.user_id = u.id
            {where_sql}
            ORDER BY t.created_at DESC
            LIMIT %s OFFSET %s
        """
        query_params = params + [limit, offset]
        items = fetch_user_db(sql, tuple(query_params))
        
        # 格式化返回
        formatted_items = []
        for item in items:
            username = item['display_name']
            formatted_items.append({
                "id": item['id'],
                "share_code": item['share_code'],
                "type": item['type'],
                "title": item['title'],
                "price": float(item['price']),
                "budget_min": float(item['budget_min']),
                "budget_max": float(item['budget_max']),
                "region": item['region'],
                "main_image": item['main_image'],
                "view_count": item['view_count'],
                "want_count": item['want_count'],
                "created_at": item['created_at'].isoformat(),
                "author": {"username": username, "avatar": item['user_avatar']}
            })
            
        map_stats = []
        if not region or region == 'all':
            stats_sql = "SELECT region, COUNT(*) as count FROM trade_items WHERE status='active' GROUP BY region"
            stats_raw = fetch_user_db(stats_sql)
            map_stats = stats_raw 
            
        return success({"items": formatted_items, "map_stats": map_stats})

    except Exception as e:
        logger.error(f"Trade list error: {e}", exc_info=True)
        return error("Failed to fetch market items", 500)


# 获取交易详情
@app.route('/api/trade/item_details/<share_code>', methods=['GET'])
@jwt_optional # 详情页允许游客访问
def get_trade_details(share_code):
    try:
        # 缓冲浏览量
        item_data = fetch_user_db("SELECT id FROM trade_items WHERE share_code = %s", (share_code,), one=True)
        if not item_data:
            return error("Item not found", 404)
            
        item_id = item_data['id']
        buffered_views = increment_view_count_optimized('trade_items', 'id', item_id)
        
        # 获取详情
        sql = """
            SELECT t.*, u.uid, u.display_name, u.avatar_url, u.level
            FROM trade_items t
            JOIN users u ON t.user_id = u.id
            WHERE t.id = %s
        """
        item = fetch_user_db(sql, (item_id,), one=True)
        
        # 获取图片
        img_sql = "SELECT image_url FROM trade_images WHERE trade_item_id = %s ORDER BY is_primary DESC"
        imgs = fetch_user_db(img_sql, (item_id,))
        images = [row['image_url'] for row in imgs]
        
        # 获取留言
        comment_sql = """
            SELECT c.content, c.created_at, u.display_name, u.avatar_url
            FROM trade_comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.trade_item_id = %s
            ORDER BY c.created_at DESC
        """
        comments_raw = fetch_user_db(comment_sql, (item_id,))
        comments = [{
            "content": c['content'],
            "created_at": c['created_at'].isoformat(),
            "username": c['display_name'], 
            "avatar": c['avatar_url']
        } for c in comments_raw]
        
        # 检查当前用户是否已点过"我想要"
        has_wanted = False
        if g.user_id:
            w_check = fetch_user_db("SELECT 1 FROM trade_wants WHERE trade_item_id=%s AND user_id=%s", (item_id, g.user_id), one=True)
            if w_check: has_wanted = True

        result = {
            "id": item['id'],
            "share_code": item['share_code'],
            "type": item['type'],
            "title": item['title'],
            "description": item['description'],
            "price": float(item['price']),
            "budget_min": float(item['budget_min']),
            "budget_max": float(item['budget_max']),
            "condition": item['condition_level'],
            "region": item['region'],
            "country": item['country'],
            "contact_info": json.loads(item['contact_info']) if item['contact_info'] else {},
            "view_count": item['view_count'] + buffered_views,
            "want_count": item['want_count'],
            "created_at": item['created_at'].isoformat(),
            "images": images,
            "comments": comments,
            "author": {
                "uid": item['uid'],
                "username": item['display_name'],
                "avatar": item['avatar_url'],
                "level": item.get('level', 1)
            },
            "has_wanted": has_wanted
        }
        
        return success(result)

    except Exception as e:
        logger.error(f"Detail error: {e}", exc_info=True)
        return error("Error fetching details", 500)


# 点击 "我想要"
@app.route('/api/trade/want', methods=['POST'])
@login_required
def toggle_trade_want():
    data = request.get_json()
    share_code = data.get('share_code')
    
    try:
        item = fetch_user_db("SELECT id, user_id, title FROM trade_items WHERE share_code = %s", (share_code,), one=True)
        if not item: return error("Item not found", 404)
        
        item_id = item['id']
        
        # 检查是否已点
        exists = fetch_user_db("SELECT id FROM trade_wants WHERE trade_item_id=%s AND user_id=%s", (item_id, g.user_id), one=True)
        
        if exists:
            # 取消想要
            execute_user_db("DELETE FROM trade_wants WHERE id=%s", (exists['id'],))
            execute_user_db("UPDATE trade_items SET want_count = want_count - 1 WHERE id=%s", (item_id,))
            msg = "已取消"
        else:
            # 添加想要
            execute_user_db("INSERT INTO trade_wants (trade_item_id, user_id) VALUES (%s, %s)", (item_id, g.user_id))
            execute_user_db("UPDATE trade_items SET want_count = want_count + 1 WHERE id=%s", (item_id,))
            msg = "已添加到我想要"
            
            # 这里的 item['user_id'] 是发布者
            # 如果不是自己点的，可以发通知 (逻辑省略)
        
        return success({"message": msg})

    except Exception as e:
        return error(str(e), 500)


# 发布留言
@app.route('/api/trade/comment', methods=['POST'])
@login_required
def post_trade_comment():
    data = request.get_json()
    share_code = data.get('share_code')
    content = data.get('content')
    
    if not content: return error("Content required", 400)
    
    try:
        item = fetch_user_db("SELECT id FROM trade_items WHERE share_code = %s", (share_code,), one=True)
        if not item: return error("Item not found", 404)
        
        execute_user_db(
            "INSERT INTO trade_comments (trade_item_id, user_id, content) VALUES (%s, %s, %s)",
            (item['id'], g.user_id, content)
        )
        
        return success({"message": "Comment posted"})
    except Exception as e:
        return error(str(e), 500)

# ----------------------------------------------------------------
# 图片上传路由
# ----------------------------------------------------------------

# 位置: /photo
# 命名: 随机26位
@app.route('/api/upload', methods=['POST'])
@login_required
@limiter.limit("10 per minute") # Redis限流辅助
def upload_general_image():
    if 'file' not in request.files:
        return error("No file part", 400)
    file = request.files['file']
    if file.filename == '' or not allowed_file(file.filename):
        return error("Invalid file", 400)

    try:
        target_dir = os.path.join(IMG_ROOT_PATH, 'photo')
        # 生成26位随机文件名
        random_name = generate_random_filename_26()
        
        # 处理流程
        final_name = process_upload_workflow(file, target_dir, random_name)
        
        if final_name:
            full_url = f"{IMAGE_SERVER_BASE_URL}/photo/{final_name}"
            return success({"url": full_url}, "上传成功")
        else:
            return error("图片压缩处理失败", 500)
            
    except Exception as e:
        logger.error(f"General upload error: {e}", exc_info=True)
        return error(f"上传失败: {str(e)}", 500)


# 交易图片上传
@app.route('/api/trade/upload_image', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def upload_trade_image_route():
    if 'file' not in request.files:
        return error("No file part", 400)
    file = request.files['file']
    if file.filename == '' or not allowed_file(file.filename):
        return error("Invalid file", 400)
    
    try:
        target_dir = os.path.join(IMG_ROOT_PATH, 'photo')
        random_name = generate_random_filename_26()
        
        final_name = process_upload_workflow(file, target_dir, random_name)
        
        if final_name:
            full_url = f"{IMAGE_SERVER_BASE_URL}/photo/{final_name}"
            return success({"url": full_url})
        else:
            return error("图片处理失败", 500)
            
    except Exception as e:
        logger.error(f"Trade upload error: {e}", exc_info=True)
        return error("Image upload failed", 500)

# 用户头像上传
# 位置: /avatars/{uid}/
# 命名: 时间戳 (timestamp)
@app.route('/api/user/avatar/upload', methods=['POST'])
@login_required
@limiter.limit("5 per minute")
def upload_avatar():
    if 'avatar' not in request.files:
        return error("请求中没有文件", 400)
    file = request.files['avatar']
    if file.filename == '' or not allowed_file(file.filename):
        return error("无效的文件格式", 400)

    # 检查用户CGB点数是否足够
    COST_CGB_POINTS = 15
    try:
        user_data = fetch_user_db('SELECT cgb_points FROM users WHERE id = %s', (g.user_id,), one=True)
        if not user_data or user_data['cgb_points'] < COST_CGB_POINTS:
            return error(f"CGB 点数不足 {COST_CGB_POINTS} 点，无法修改头像", 403)
    except Exception as e:
        logger.error(f"Error checking user points: {e}", exc_info=True)
        return error("系统错误", 500)

    try:
        # 获取用户UID 
        user_uid = g.uid
        if not user_uid:
            return error("无法获取用户信息", 401)
            
        # 创建用户专属目录
        user_avatar_dir = os.path.join(IMG_ROOT_PATH, 'avatars', str(user_uid))
        if not os.path.exists(user_avatar_dir):
            os.makedirs(user_avatar_dir, exist_ok=True)
            
        # 生成时间戳文件名
        timestamp_name = str(int(time.time()))
        
        # 处理流程
        final_name = process_upload_workflow(file, user_avatar_dir, timestamp_name)
        
        if final_name:
            # 拼接完整 URL
            avatar_url = f"{IMAGE_SERVER_BASE_URL}/avatars/{user_uid}/{final_name}"
            
            # 更新数据库头像URL
            execute_user_db('UPDATE users SET avatar_url = %s WHERE id = %s', (avatar_url, g.user_id))
            
            # 扣除点数并记录日志
            update_user_cgb_points(g.user_id, -COST_CGB_POINTS, "修改个人头像", related_type='user_action')
            add_activity_log(g.user_id, 'updated_avatar', actor_uid=g.uid, description=f"修改了个人头像")

            return success({"avatar_url": avatar_url}, f"头像上传成功，已扣除 {COST_CGB_POINTS} CGB")
        else:
            return error("头像处理失败", 500)

    except Exception as e:
        logger.error(f"Avatar upload failed: {e}", exc_info=True)
        return error(f"头像上传失败: {str(e)}", 500)

@app.route('/api/server_time_proxy', methods=['GET'])
def get_syiban_time():
    target_url = "http://time.syiban.com/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    TARGET_DATE_STR = "2026年2月17日"
    
    # 默认值
    scraped_time_str = dt.now().strftime("%H:%M:%S")
    is_event_date = False
    source = "local"

    print("--- Time Sync Triggered ---") # 强制控制台打印

    try:
        response = requests.get(target_url, headers=headers, timeout=3)
        if response.status_code == 200:
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 1. 检查日期
            ymdw_div = soup.find('div', id='ymdw')
            ymdw_text = ymdw_div.text.strip() if ymdw_div else ""
            print(f"Scraped Date Text: {ymdw_text}")

            # 2. 检查时间
            hms_div = soup.find('div', id='hms')
            if hms_div:
                scraped_time_str = hms_div.text.strip()
                source = "syiban"
                print(f"Scraped Time Text: {scraped_time_str}")

            # 判定逻辑：如果爬取到的页面包含目标日期，或者是你本地环境已经是2月17日
            local_now = dt.now()
            if TARGET_DATE_STR in ymdw_text or (local_now.month == 2 and local_now.day == 17):
                is_event_date = True
                print("Event Date Validated: TRUE")
            else:
                print(f"Event Date Validated: FALSE (Target was {TARGET_DATE_STR})")

    except Exception as e:
        print(f"Scraping Error: {e}")
        # 报错时，根据本地时间兜底
        local_now = dt.now()
        scraped_time_str = local_now.strftime("%H:%M:%S")
        if local_now.month == 2 and local_now.day == 17:
            is_event_date = True

    return jsonify({
        "current_time": scraped_time_str,
        "is_event_date": is_event_date,
        "source": source
    })

@app.route('/api/claim_new_year_gift', methods=['POST'])
@login_required
def claim_new_year_gift():
    logger.info(f"User {g.uid} is attempting to claim New Year gift.")
    
    # 定义活动标识，防止重复领取
    GIFT_ACTIVITY_TYPE = 'new_year_gift_2026' 
    REWARD_POINTS = 8888

    try:
        # 检查是否已经领取过
        check_sql = "SELECT id FROM activity_log WHERE user_id = %s AND activity_type = %s"
        exists = fetch_user_db(check_sql, (g.user_id, GIFT_ACTIVITY_TYPE), one=True)
        
        if exists:
            logger.warning(f"User {g.uid} attempted to double-claim the gift.")
            return error("您已经领取过2026跨年大红包了，明年再来吧！", 400)

        # 发放奖励 (复用你现有的 helper 函数)
        success_update = update_user_cgb_points(
            user_id=g.user_id, 
            points_change=REWARD_POINTS, 
            reason="2026跨年倒计时红包奖励",
            related_type='event'
        )

        if not success_update:
            return error("奖励发放失败，请联系管理员", 500)

        # 标记“已领取”
        add_activity_log(
            user_id=g.user_id, 
            activity_type=GIFT_ACTIVITY_TYPE, # 关键：用于上方 check_sql 判断
            actor_uid=g.uid, 
            description=f"成功领取了跨年红包 {REWARD_POINTS} CGB",
            points_change=0 # 分数变化已经在 update_user_cgb_points 里记过了，这里记0或者不传
        )
        
        logger.info(f"User {g.uid} successfully claimed {REWARD_POINTS} CGB.")
        return success({"points": REWARD_POINTS}, f"新年快乐！已成功入账 {REWARD_POINTS} CGB！")
    
    except Exception as e:
        logger.error(f"Error checking/claiming gift for {g.uid}: {e}", exc_info=True)
        return error("服务器繁忙，领取失败", 500)


# ======================================================================
#                           Extra: Bing Photos
#   说明：额外接口，放在功能接口之外的位置，避免干扰主要业务路由
# ======================================================================


@app.route('/api/bings', methods=['GET'])
@limiter.limit("20 per minute; 200 per hour")
def get_bing_today_photo():
    """
    获取 Bing 今日壁纸并重定向至实际图片 URL（不返回 base64）。
    - 使用 Bing JSON 接口获取当日图片元数据
    - 拼出图片直链后直接 302 跳转
    """
    try:
        meta_api = "https://www.bing.com/HPImageArchive.aspx?format=js&idx=0&n=1"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
        }

        # 1) 获取元数据 JSON
        resp = requests.get(meta_api, headers=headers, timeout=5)
        resp.raise_for_status()
        data = resp.json()

        images = data.get("images") or []
        if not images:
            return error("未获取到今日壁纸元数据", 502)

        rel = images[0].get("url") or ""
        if not rel:
            return error("返回数据缺少图片 URL", 502)

        img_url = ("https://www.bing.com" + rel) if rel.startswith("/") else rel
        logger.info(f"Bing Today Image URL: {img_url}")
        # 控制台输出，便于调试或日志抓取
        print(img_url)

        # 根据查询参数决定行为：?img -> 302 图片直链；?text -> 返回版权文字；默认同 ?img
        want_img = 'img' in request.args
        want_text = 'text' in request.args

        if want_img or (not want_img and not want_text):
            # 2) 直接重定向到图片 URL
            return redirect(img_url, code=302)

        if want_text:
            copyright_text = images[0].get("copyright") or ""
            if not copyright_text:
                return error("返回数据缺少版权信息", 502)
            # 直接返回纯文本
            return copyright_text, 200, {"Content-Type": "text/plain; charset=utf-8"}

    except requests.exceptions.RequestException as e:
        logger.error(f"Bing photo network error: {e}", exc_info=True)
        return error("获取 Bing 今日壁纸失败（网络错误）", 502)
    except Exception as e:
        logger.error(f"Bing photo unexpected error: {e}", exc_info=True)
        return error("获取 Bing 今日壁纸失败（服务器错误）", 500)