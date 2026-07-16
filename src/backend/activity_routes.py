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

from flask import Blueprint, request, g
import random
import logging
from functools import wraps
from .app import limiter, redis_client, update_user_cgb_points, add_activity_log, login_required
from .db import fetch_user_db, execute_user_db
from .utils.response import success, error

logger = logging.getLogger(__name__)
activity_bp = Blueprint('activity', __name__, url_prefix='/api/activity')

# =============================================================================
#                               马年转盘活动接口
# =============================================================================

# 转盘奖品配置
WHEEL_PRIZES = [
    {"id": 1, "type": "cgb", "val": 88, "name": "88 CGB点", "weight": 40},
    {"id": 2, "type": "cgb", "val": 188, "name": "188 CGB点", "weight": 30},
    {"id": 3, "type": "cgb", "val": 888, "name": "888 CGB点", "weight": 5},
    {"id": 4, "type": "booster", "val": 1, "name": "双倍速率卡(24h)", "weight": 10},
    {"id": 5, "type": "badge", "val": "dragon_horse_badge", "name": "稀有龙马勋章", "weight": 2},
    {"id": 6, "type": "beta", "val": "beta_access", "name": "灰度测试资格", "weight": 3},
    {"id": 7, "type": "cgb", "val": 18, "name": "18 CGB (安慰奖)", "weight": 10},
    {"id": 8, "type": "cgb", "val": 2026, "name": "2026 CGB大奖", "weight": 0.1}
]

@activity_bp.route('/lucky_wheel/spin', methods=['POST'])
@login_required
@limiter.limit("6 per 5 minute")
def spin_lucky_wheel():
    if redis_client:
        lock_key = f"lock:wheel:{g.uid}"
        if not redis_client.set(lock_key, "1", nx=True, ex=5):
            return error("操作过于频繁，请稍候", 429)
        
    logger.info(f"User {g.uid} is spinning the wheel.")
    
    COST = 66 
    user_data = fetch_user_db('SELECT cgb_points, display_name FROM users WHERE id = %s', (g.user_id,), one=True)
    
    if user_data['cgb_points'] < COST:
        return error("CGB点数不足，无法开启转盘", 403)

    try:
        update_user_cgb_points(g.user_id, -COST, "马年转盘抽奖消耗", related_type='wheel_cost')

        ids = [p['id'] for p in WHEEL_PRIZES]
        weights = [p['weight'] for p in WHEEL_PRIZES]
        
        selected_id = random.choices(ids, weights=weights, k=1)[0]
        prize = next(p for p in WHEEL_PRIZES if p['id'] == selected_id)

        log_desc = f"转盘中奖：{prize['name']}"
        
        if prize['type'] == 'cgb':
            update_user_cgb_points(g.user_id, prize['val'], "转盘中奖", related_type='wheel_win')
            
        elif prize['type'] == 'booster':
            execute_user_db('UPDATE users SET cgb_booster_active = TRUE WHERE id = %s', (g.user_id,))
            add_activity_log(g.user_id, 'item_received', actor_uid=g.uid, description="获得了双倍速率卡", related_type='booster')

        elif prize['type'] == 'badge':
            add_activity_log(g.user_id, 'badge_awarded', actor_uid=g.uid, description=f"抽中了 {prize['name']}", related_type='wheel_badge')
            
        elif prize['type'] == 'beta':
            add_activity_log(g.user_id, 'beta_access_granted', actor_uid=g.uid, description="获得了灰度测试资格", related_type='permission')

        new_balance_data = fetch_user_db('SELECT cgb_points FROM users WHERE id = %s', (g.user_id,), one=True)
        
        return success({
            "prize": prize,
            "cost": COST,
            "balance": new_balance_data['cgb_points']
        }, "抽奖成功")

    except Exception as e:
        logger.error(f"Spin wheel error: {e}", exc_info=True)
        update_user_cgb_points(g.user_id, COST, "转盘故障退款", related_type='system_refund')
        return error("转盘似乎卡住了，积分已退回", 500)

# ==============================================================================
#                               红包雨活动接口
# ==============================================================================

@activity_bp.route('/red_packet/claim', methods=['POST'])
@login_required
@limiter.limit("120 per minute")
def claim_red_packet_score():
    """
    处理红包雨抢到的CGB点数入账
    """
    try:
        if redis_client:
            lock_key = f"lock:red_packet:{g.uid}"
            if not redis_client.set(lock_key, "1", nx=True, ex=2):
                 return error("点太快了，歇一歇", 429)

        data = request.get_json()
        amount = data.get('amount')

        if amount is None:
            return error("金额不能为空", 400)
        
        try:
            amount = float(amount)
        except ValueError:
            return error("金额格式错误", 400)

        if amount <= 0 or amount > 8888:
            logger.warning(f"User {g.uid} attempted to claim suspicious amount: {amount}")
            return error("金额数据异常", 400)

        success_update = update_user_cgb_points(
            user_id=g.user_id,
            points_change=amount,
            reason="新春红包雨活动奖励",
            related_id=None,
            related_type='red_packet_rain' 
        )

        if success_update:
            new_total_data = fetch_user_db('SELECT cgb_points FROM users WHERE id = %s', (g.user_id,), one=True)
            new_total = new_total_data['cgb_points'] if new_total_data else 0
            
            return success({
                "added": amount,
                "total_cgb": new_total
            }, "领取成功")
        else:
            return error("入账失败", 500)

    except Exception as e:
        logger.error(f"Error claiming red packet for {g.uid}: {e}", exc_info=True)
        return error("服务器繁忙", 500)
