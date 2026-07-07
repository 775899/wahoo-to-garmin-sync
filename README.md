# Wahoo → Garmin 自动同步

利用 GitHub Actions 每15分钟自动将 Wahoo 骑行数据同步到 Garmin Connect，**完全免费**。

## 工作原理

1. **Wahoo App** 自动将活动文件（`.fit`）上传到 **Dropbox**
2. GitHub Actions 定时运行，读取 Dropbox 中的新文件
3. 自动上传到 **Garmin Connect**
4. 上传成功后，文件自动移动到已处理文件夹

## 前置要求

- Wahoo 账号（免费）
- Garmin Connect 账号（免费）
- Dropbox 账号（免费，2GB 足够）
- GitHub 账号（免费）

## 快速开始

### 1. 连接 Wahoo 到 Dropbox

1. 打开 **Wahoo Fitness App**（或 ELEMNT Companion App）
2. 进入 **Profile** → **Linked Accounts**
3. 点击 **Dropbox**，完成授权
4. 授权后，Wahoo 会自动将每次活动的 `.fit` 文件上传到 `/Apps/Wahoo Fitness` 文件夹

### 2. 创建 Dropbox Access Token

1. 访问 [Dropbox App Console](https://www.dropbox.com/developers/apps)
2. 点击 **Create app**
3. 选择：
   - API: **Scoped access**
   - Access type: **Full Dropbox** 或 **App folder**
   - Name: `wahoo-garmin-sync`
4. 在 Permissions 标签页，勾选：
   - `files.content.read`
   - `files.content.write`
5. 点击 **Generate access token**，复制生成的令牌

### 3. Fork 本仓库并配置 Secrets

1. Fork 本仓库到你的 GitHub 账号
2. 进入仓库 → **Settings** → **Secrets and variables** → **Actions**
3. 添加以下 Repository secrets：

| Secret 名称 | 说明 | 示例 |
|------------|------|------|
| `GARMIN_EMAIL` | Garmin Connect 登录邮箱 | `your@email.com` |
| `GARMIN_PASSWORD` | Garmin Connect 登录密码 | `yourpassword` |
| `DROPBOX_ACCESS_TOKEN` | Dropbox Access Token | `sl.xxx...` |
| `DROPBOX_FOLDER` | Wahoo 上传路径 | `/Apps/Wahoo Fitness` |
| `GARMIN_REGION` | Garmin 区域 | `international` 或 `china` |

**注意事项：**
- 国区 Garmin 账号（`connect.garmin.cn`）设置 `GARMIN_REGION=china`
- 国际区账号（`connect.garmin.com`）设置 `GARMIN_REGION=international`
- Dropbox 路径默认是 `/Apps/Wahoo Fitness`，如果 Wahoo 使用了不同路径请修改

### 4. 手动测试

1. 进入仓库 → **Actions** 标签页
2. 找到 **Wahoo to Garmin Sync** 工作流
3. 点击 **Run workflow** 手动触发一次
4. 查看运行日志确认是否正常

### 5. 完成一次骑行测试

1. 进行一次骑行，使用 Wahoo 设备记录
2. 确保活动已同步到 Wahoo App
3. 等待 15 分钟（或手动触发 Actions）
4. 检查 Garmin Connect 是否出现该活动

## 同步频率

默认每 **15 分钟** 运行一次，可在 `.github/workflows/sync.yml` 中修改 cron 表达式：

```yaml
# 每15分钟
cron: '*/15 * * * *'

# 每小时
cron: '0 * * * *'

# 每天两次（9点和21点）
cron: '0 9,21 * * *'
```

## GitHub Actions 免费额度

GitHub Actions 每月有 **2000 分钟** 免费额度：
- 每15分钟运行一次 ≈ 每天 96 次
- 每次运行约 1-2 分钟
- 每月约 3000 分钟，**超出免费额度**

**建议：**
- 如果只是骑行后等待同步，改为 **每小时** 运行即可：`0 * * * *`
- 这样每月约 730 次 × 2 分钟 ≈ 1500 分钟，在免费额度内
- 也可以设为 **每30分钟**：`*/30 * * * *`

## 故障排查

### 日志查看

1. 进入仓库 → **Actions**
2. 点击失败的运行记录
3. 查看 **sync** 步骤的日志

### 常见问题

**Q: 文件上传成功但 Garmin 里看不到？**
- 检查 Garmin 区域设置是否正确（国区 vs 国际区）
- 可能是 `.fit` 文件格式问题，尝试手动在 Garmin Connect 网页端上传同一个文件验证

**Q: Dropbox 连接失败？**
- 确认 Access Token 没有过期（Dropbox 长期令牌不会过期，但短令牌需要定期刷新）
- 检查令牌是否有 `files.content.read` 和 `files.content.write` 权限

**Q: Garmin 登录失败？**
- 确认邮箱密码正确
- Garmin 可能启用了两步验证，需要在账号设置中生成应用专用密码
- 国区账号和国际区账号不能混用

**Q: 如何避免重复上传？**
- 脚本内置去重机制，通过文件名记录已同步的活动
- 上传成功后文件会自动移动到 `processed` 文件夹
- 如果手动删除 `sync_state.json`，会导致重复上传

## 数据安全

- 所有敏感信息（密码、Token）都存储在 GitHub Secrets 中，不会泄露
- GitHub Actions 的运行日志会自动隐藏 Secrets 的值
- 代码开源，可自行审计
- 不会存储或传输任何活动数据到第三方服务器，只在你的 GitHub Actions 和 Garmin/Dropbox 之间传输

## 手动同步脚本

如果你想在本地运行（不依赖 GitHub Actions）：

```bash
# 安装依赖
pip install garminconnect dropbox python-dotenv

# 设置环境变量
export GARMIN_EMAIL="your@email.com"
export GARMIN_PASSWORD="yourpassword"
export DROPBOX_ACCESS_TOKEN="sl.xxx..."

# 运行
python sync.py
```

Windows PowerShell:
```powershell
$env:GARMIN_EMAIL="your@email.com"
$env:GARMIN_PASSWORD="yourpassword"
$env:DROPBOX_ACCESS_TOKEN="sl.xxx..."
python sync.py
```

## 自定义配置

可以在仓库根目录创建 `.env` 文件用于本地测试：

```env
GARMIN_EMAIL=your@email.com
GARMIN_PASSWORD=yourpassword
DROPBOX_ACCESS_TOKEN=sl.xxx...
DROPBOX_FOLDER=/Apps/Wahoo Fitness
GARMIN_REGION=international
```

**注意：** `.env` 文件已加入 `.gitignore`，不会被提交到 GitHub。

## 更新日志

- **2026-07-07**: 初始版本，支持 Dropbox → Garmin 自动同步

## 许可证

MIT License - 自由使用和修改

## 贡献

欢迎提交 Issue 和 PR！

---

**有问题？** 查看 [Issues](../../issues) 或提交新的问题。
