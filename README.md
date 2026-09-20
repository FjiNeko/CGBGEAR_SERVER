<h1 align="center">CGBGEAR 论坛原网站源码（后端）</h1>

<p align="center">
  <img src="https://img.shields.io/badge/license-AGPL--3.0-blue.svg" align="absmiddle" alt="license" />
  <img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" align="absmiddle" alt="python" />
  <img src="https://img.shields.io/badge/version-latest-green.svg" align="absmiddle" alt="version" />
  <img src="https://img.shields.io/badge/platform-Linux-lightgrey.svg" align="absmiddle" alt="platform" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/ATTENTION!-yellow.svg" align="absmiddle" alt="attention" />
  本项目已全面清理历史构建归档与泄露风险，请务必基于 .env.example 独立配置私有环境变量，严禁将真实凭证与构建包提交至公开仓库。
</p>

CGBGEAR 论坛系统底层服务端源码仓库（代码代号 SERVER）。

> <img src="https://img.shields.io/badge/DESCRIPTION-0ea5e9.svg" align="absmiddle" alt="description" /> **项目说明**：[@FjiNeko](https://github.com/FjiNeko) 与 @DayingNeko 均为作者本人。项目于2025/11落地立项，历经一年持续全栈独立开发与工程迭代。

## 项目架构矩阵

| 架构节点 | 代号 | 职责定位 | 仓库直达 |
| :--- | :--- | :--- | :--- |
| **服务端** | `SERVER` | RESTful API / 数据库 / 认证 / 缓存（当前仓库） | [FjiNeko/CGBGEAR_SERVER](https://github.com/FjiNeko/CGBGEAR_SERVER) |
| **客户端** | `USER_INTERFACE` | React 19 / Vite / 双端自适应交互界面 | [FjiNeko/CGBGEAR_USER_INTERFACE](https://github.com/FjiNeko/CGBGEAR_USER_INTERFACE) |

## 项目背景与开源声明

CGBGEAR 原网站（cgbgear.cn）系由合伙人提出业务构想，并由作者 [@FjiNeko](https://github.com/FjiNeko) 作为核心开发者统筹全盘研发落地的一款军警战术装备垂直社区。运营期间受限于细分垂直领域受众基数、常态化合规审查边界以及长期运维的算力与资金成本，平台最终终止线上商业化运作。

本项目全套系统——涵盖整体架构蓝图、底层数据建模、RESTful 业务逻辑实现乃至运维部署方案——自始至终均由作者独立开发完成。代码产权清晰完整，不存在第三方商业争议或未厘清的知识产权纠纷。鉴于个人精力有限难以长期独自支撑多端演进，现将全部完整生产级代码无保留开源发布，旨在为垂直社区系统构建、全栈工程落地及极客交互设计提供开箱即用的实战技术沉淀。

## 核心架构流程

```text
+-----------------------------------------------------------------------------------+
|                                 客户端请求 (Client)                               |
+-----------------------------------------+-----------------------------------------+
                                          | (HTTPS / RESTful 接口)
                                          v
+-----------------------------------------------------------------------------------+
|                              Web 网关与反向代理 (Gateway)                         |
+-----------------------------------------+-----------------------------------------+
                                          | (WSGI 协议转发)
                                          v
+-----------------------------------------------------------------------------------+
|                         应用服务容器 (Gunicorn / uWSGI)                           |
|                    [4 个工作进程 x 2 个工作线程 多进程 / 多线程并发处理]          |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                              Flask 核心服务层 (Backend)                           |
|  +-----------------------+  +-----------------------+  +-----------------------+  |
|  |    全局认证与拦截器   |  |   限流与防护 (Limiter)|  |   业务路由分发处理    |  |
|  |   (JWT 鉴权 / 会话)   |  |   (基于 IP 滑动窗口)  |  |   (社区/交易/活动)    |  |
|  +-----------+-----------+  +-----------+-----------+  +-----------+-----------+  |
+--------------|--------------------------|--------------------------|--------------+
               |                          |                          |
               v                          v                          v
+-------------------------+  +-------------------------+  +-------------------------+
|        安全认证模块     |  |       缓存与限流总线    |  |       数据持久化池      |
|  * 图形验证码生成与核验 |  |  * Redis 实例缓存会话   |  |  * MySQL Connector 驱动 |
|  * 自研密码散列与校验   |  |  * 动态流量计数与状态   |  |  * 原生连接池 (PoolSize)|
|  * 限时 Token 签名生命周期|  |  * 内存降级兜底保障     |  |  * UTC 时区感知映射     |
+--------------+----------+  +-------------------------+  +-------------------------+
               |
               v
+-----------------------------------------------------------------------------------+
|                                外部服务扩展管线                                   |
|  +---------------------------------------+ +-----------------------------------+  |
|  |           SMTP 邮件通道               | |           AI 模型接口             |  |
|  |  * 密码重置通知推送                   | |  * 自动化提示词组装与文本转译     |  |
|  +---------------------------------------+ +-----------------------------------+  |
+-----------------------------------------------------------------------------------+
```

## 技术栈

| 分类 | 核心技术 / 库 | 版本 | 说明 |
| :--- | :--- | :--- | :--- |
| **运行时** | Python | `>=3.10` | 服务端核心运行环境 |
| **Web 框架** | Flask / Werkzeug | `3.0.3` | RESTful 接口与应用底层支撑 |
| **数据库驱动** | MySQL Connector | `9.0.0` | 原生连接池管理与数据存取 |
| **缓存与限流** | Redis / Flask-Limiter | `7.1.1` / `4.1.1` | 高频访问限流与验证码缓存 |
| **加密与安全** | 自研算法 (加盐哈希 / 校验) / PyJWT | `2.8.0` | 身份令牌签发、密码散列与验证码生成 |
| **网络与采集** | Requests / BeautifulSoup4 | `2.25.1` / `0.0.2` | 外部服务对接与文本处理 |

## 环境配置与部署步骤

### 1. 克隆与目录就绪

```bash
git clone https://github.com/FjiNeko/CGBGEAR_SERVER.git
cd CGBGEAR_SERVER
```

### 2. 环境变量配置

复制环境模板并配置本地专属密钥与数据库凭据：

```bash
cp .env.example .env
```

核心环境变量说明：

| 配置项 | 类型 / 前缀 | 说明 |
| :--- | :--- | :--- |
| `JWT_SECRET_KEY` | 认证密钥 | 用于签发用户身份令牌的高强度安全密钥 |
| `DB_*` | 数据库连接参数 | 数据库主机、端口、用户名、密码与数据库名称 |
| `REDIS_*` | 缓存连接参数 | Redis 实例连接配置（用于限流与验证码会话） |
| `SMTP_*` | 邮件服务凭据 | 邮件通道连接与授权信息（用于密码重置与通知服务） |
| `FRONTEND_BASE_URL` | 跨域来源配置 | 允许跨域访问的前端交互界面域名白名单 |
| `deepseek_api_key` | 模型接口密钥 | 外部 AI 翻译与文本处理接口凭据 |

> 模型接口仅支持 OpenAI Compatible（兼容）格式调用。

### 3. 安装依赖

推荐使用 uv 极速安装环境：

```bash
# 使用 uv
uv sync

# 或使用标准 pip
pip install -r pyproject.toml
```

### 4. 服务启动

```bash
# 开发模式调试
python -m src.backend.app

# 生产环境 Gunicorn 启动
gunicorn -c gunicorn_conf.py src.backend.app:app

# 生产环境 uWSGI 启动
uwsgi --ini uwsgi.ini
```

## 目录结构概览

```text
CGBGEAR_SERVER/
├── gunicorn_conf.py          # Gunicorn 生产运行配置
├── uwsgi.ini                 # uWSGI 生产运行配置
├── pyproject.toml            # 项目元数据与依赖定义
├── uv.lock                   # 依赖版本锁定
├── WEB_SERVER_CONFIG.md      # Web 服务器动静分离配置指引
├── FIX_TMPFILE_PERMISSION.md # 临时上传目录权限处理说明
├── .env.example              # 环境变量配置模板
├── .gitignore                # Git 忽略安全策略
└── src/
    └── backend/
        ├── app.py            # 主程序入口、全局路由与拦截器
        ├── db.py             # MySQL 连接池与时区调度模块
        ├── activity_routes.py# 社区互动与营销活动路由
        ├── translation.py    # AI 智能翻译服务模块
        ├── fonts/            # 验证码生成专用字体资产
        └── utils/            # 密码哈希、响应封装、ID生成与邮件工具
```

## 开源协议

本项目代码严格遵循 [AGPL-3.0](https://choosealicense.com/licenses/agpl-3.0/) 开源协议。请在遵守协议条款的前提下使用、修改和分发代码。

---

Written by FjiNeko  
Update: 2026/09/20
