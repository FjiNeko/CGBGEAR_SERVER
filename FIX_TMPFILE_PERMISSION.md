# 修复文件上传权限问题

## 问题
上传文件时出现权限错误：`Permission denied: '/websites/backend/tmpfile/xxx.json'`

## 解决方案

在服务器上执行以下命令来修复权限：

```bash
# 1. 创建 files 目录（如果不存在）
mkdir -p /www/wwwroot/cgbgear.cn/files

# 2. 设置目录所有者为 Web 服务器用户
# 对于宝塔面板，通常是 www
sudo chown -R www:www /www/wwwroot/cgbgear.cn/files

# 3. 设置目录权限
sudo chmod -R 775 /www/wwwroot/cgbgear.cn/files
```

## 宝塔面板快速修复

1. 进入文件管理
2. 找到 `/www/wwwroot/cgbgear.cn/files` 目录
3. 右键 -> 权限 -> 设置为 `775`
4. 右键 -> 所有者 -> 设置为 `www`

## 验证

执行命令后，尝试再次上传文件测试。
