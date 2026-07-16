# Web 服务器配置说明

## 目标
让 `https://cgbgear.cn/down/xxx.xxx` 直接访问 `backend/tmpfile` 目录中的文件

---

## Nginx 配置

在你的 Nginx 配置文件中添加以下 location 块：

```nginx
location /down/ {
    alias /websites/backend/tmpfile/;
    autoindex off;
    expires 1d;
    add_header Cache-Control "public, immutable";
}
```

完整示例：
```nginx
server {
    listen 80;
    server_name cgbgear.cn;
    
    # 其他配置...
    
    # 文件下载路径
    location /down/ {
        alias /websites/backend/tmpfile/;
        autoindex off;
        expires 1d;
        add_header Cache-Control "public, immutable";
    }
    
    # Flask 应用
    location /api/ {
        proxy_pass http://127.0.0.1:5000;
        # 其他 proxy 配置...
    }
}
```

配置后重启 Nginx：
```bash
sudo nginx -t
sudo systemctl reload nginx
```

---

## Apache 配置

如果使用 Apache，在虚拟主机配置或 `.htaccess` 中添加：

```apache
# 在主配置文件中
Alias /down /websites/backend/tmpfile
<Directory "/websites/backend/tmpfile">
    Options -Indexes +FollowSymLinks
    AllowOverride None
    Require all granted
</Directory>
```

或者在 `.htaccess` 中（如果支持）：
```apache
RewriteEngine On

# 允许直接访问 /down 路径
RewriteCond %{REQUEST_URI} ^/down/
RewriteRule ^down/(.*)$ /websites/backend/tmpfile/$1 [L]
```

配置后重启 Apache：
```bash
sudo apachectl configtest
sudo systemctl reload apache2
```

---

## 测试

1. 上传一个文件通过 `/api/admin/upload_file`
2. 获取返回的 URL，例如：`https://cgbgear.cn/down/abc123.jpg`
3. 在浏览器中访问该 URL，应该能直接下载文件

---

## 安全建议

1. 定期清理 `tmpfile` 目录中的旧文件
2. 限制文件大小和类型
3. 考虑添加访问频率限制
