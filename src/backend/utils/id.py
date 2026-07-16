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

import string
import random

# 如果你应用程序的其他部分仍然需要生成随机的 UID，可以保留此函数
# 但对于用户注册的 UID，我们将使用 format_sequential_uid
def generate_random_uid(length=16):
    """
    生成指定长度的随机字符串（包含大小写字母+数字）
    """
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def format_sequential_uid(sequence_number: int, length: int = 16) -> str:
    """
    格式化一个序列号为指定长度的字符串，前面补零。
    例如：format_sequential_uid(1, 16) -> "0000000000000001"
    format_sequential_uid(123, 16) -> "0000000000000123"
    """
    if not isinstance(sequence_number, int) or sequence_number < 1:
        raise ValueError("Sequence number must be a positive integer.")
    
    # 使用 f-string 格式化，例如：f"{1:016d}" 会得到 "0000000000000001"
    return f"{sequence_number:0{length}d}"
