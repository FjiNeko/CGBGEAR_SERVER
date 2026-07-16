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

import mysql.connector
from mysql.connector import pooling
import os
import logging
from flask import g
from datetime import datetime, timezone # 【

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------
# 用户数据库连接池
# ----------------------------------------------------------------
USER_POOL = pooling.MySQLConnectionPool(
    pool_name="cgbgear_user_pool",
    pool_size=5,
    host=os.getenv("DB_HOST", ""),
    port=int(os.getenv("DB_PORT", 3306)),
    user=os.getenv("DB_USER", ""),
    password=os.getenv("DB_PASSWORD", ""),
    database=os.getenv("DB_NAME", ""),
    charset="utf8mb4",
    use_unicode=True
)

def get_user_db_connection():
    """
    获取用户数据库的连接，并存储在 Flask 的 g 对象中。
    如果连接已存在，则返回现有连接。
    """
    if 'user_db_conn' not in g:
        g.user_db_conn = USER_POOL.get_connection()
    return g.user_db_conn

def close_user_db_connection(e=None):
    """
    关闭用户数据库连接。此函数用于 Flask 的 app.teardown_appcontext 回调。
    """
    user_db_conn = g.pop('user_db_conn', None)
    if user_db_conn is not None:
        user_db_conn.close()

# --- 数据库操作函数 ---

def fetch_user_db(query, args=(), one=False):
    """
    【修改】执行 SQL 查询 (SELECT)。
    现在会自动将返回结果中的 naive datetime 对象转换为 aware UTC datetime 对象。
    """
    conn = get_user_db_connection()
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, args)
        results = cursor.fetchall()
        
        if results:
            for row in results:
                for key, value in row.items():
                    # 检查值是否为 datetime 对象且没有时区信息
                    if isinstance(value, datetime) and value.tzinfo is None:
                        # 附加 UTC 时区信息
                        row[key] = value.replace(tzinfo=timezone.utc)
        
        return (results[0] if results else None) if one else results
    except Exception as e:
        logger.error(f"Failed to fetch from DB: {e}", exc_info=True)
        raise e
    finally:
        if cursor:
            cursor.close()

def execute_user_db(sql, params=None, commit=True, fetchone=False, fetchall=False):
    """
    执行 INSERT, UPDATE, DELETE 等写操作。
    此函数不需要修改，因为我们写入时已经使用了带有时区的 datetime 对象。
    """
    connection = get_user_db_connection()
    try:
        with connection.cursor() as cursor:
            logger.debug(f"Executing SQL: {sql} with params: {params}")
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)

            if commit:
                connection.commit()
                logger.debug("Transaction committed.")
            else:
                logger.debug("Transaction not committed (commit=False).")

            if sql.strip().upper().startswith('INSERT'):
                last_id = cursor.lastrowid
                logger.debug(f"INSERT statement, lastrowid: {last_id}")
                return last_id

            if fetchone:
                result = cursor.fetchone()
                logger.debug(f"FETCHONE result: {result}")
                return result
            if fetchall:
                result = cursor.fetchall()
                logger.debug(f"FETCHALL result: {len(result)} rows")
                return result
            
            rows_affected = cursor.rowcount
            logger.debug(f"Non-fetching query executed successfully. Rows affected: {rows_affected}")
            return rows_affected
            
    except Exception as e:
        logger.error(f"Database operation failed: {e}. SQL: {sql}, Params: {params}", exc_info=True)
        connection.rollback()
        logger.error("Transaction rolled back.")
        raise
