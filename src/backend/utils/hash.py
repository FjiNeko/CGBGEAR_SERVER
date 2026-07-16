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

import hashlib
import os

def hash_password(password):
    """
    加盐哈希处理密码。
    """
    salt = os.getenv("PASSWORD_SALT", "") 
    return hashlib.sha256((password + salt).encode()).hexdigest()

def check_password(stored_hash, input_password):
    """验证密码是否正确"""
    return stored_hash == hash_password(input_password)
