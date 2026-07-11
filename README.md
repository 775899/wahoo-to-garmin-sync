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

### 2. 创建 Dropbox 应用凭据

推荐使用 **Refresh Token**（长期有效），不建议用 Access Token（约 4 小时过期）。

1. 访问 [Dropbox App Console](https://www.dropbox.com/developers/apps)
2. 点击 **Create app**
3. 选择：
   - API: **Scoped access**
   - Access type: **Full Dropbox** 或 **App folder**
   - Name: `wahoo-garmin-sync`
4. 在 Permissions 标签页，勾选：
   - `files.content.read`
   - `files.content.write`
5. 记下 **App key** 和 **App secret**（在 Settings 页面）
6. 生成 Refresh Token（任选一种方式）：
   - **方式一（推荐，命令行）**：
     ```bash
     # 替换 YOUR_APP_KEY 和 YOUR_APP_SECRET
     curl -X POST https://api.dropbox.com/oauth2/token \
       -d grant_type=authorization_code \
       -d code=YOUR_AUTH_CODE \
       -u "YOUR_APP_KEY:YOUR_APP_SECRET"
     ```
     其中 `YOUR_AUTH_CODE` 需先在浏览器访问以下 URL 获取（登录 Dropbox 授权后拿到 code）：
     ```
     https://www.dropbox.com/oauth2/authorize?client_id=YOUR_APP_KEY&token_access_type=offline&response_type=code
     ```
   - **方式二**：使用 [Dropbox OAuth Token Generator](https://dropbox.github.io/dropbox-api-v2-explorer/) 生成

### 3. Fork 本仓库并配置 Secrets

1. Fork 本仓库到你的 GitHub 账号
2. 进入仓库 → **Settings** → **Secrets and variables** → **Actions**
3. 添加以下 Repository secrets（敏感信息）：

| Secret 名称 | 说明 | 示例 |
|------------|------|------|
| `GARMIN_EMAIL` | Garmin Connect 登录邮箱 | `your@email.com` |
| `GARMIN_PASSWORD` | Garmin Connect 登录密码 | `yourpassword` |
| `DROPBOX_REFRESH_TOKEN` | Dropbox Refresh Token（长期有效） | `a-long-token-string` |
| `DROPBOX_APP_KEY` | Dropbox App Key | `abc123xyz` |
| `DROPBOX_APP_SECRET` | Dropbox App Secret | `def456uvw` |

4. 添加以下 Repository variables（非敏感配置，在 **Variables** 标签页添加，不是 Secrets）：

| Variable 名称 | 说明 | 默认值 | 示例 |
|---------------|------|--------|------|
| `DROPBOX_FOLDER` | Wahoo 上传路径 | `/Apps/Wahoo Fitness` | `/Apps/Wahoo Fitness` |
| `GARMIN_REGION` | Garmin 区域 | `international` | `china` |

**注意事项：**
- 国区 Garmin 账号（`connect.garmin.cn`）设置 `GARMIN_REGION=china`
- 国际区账号（`connect.garmin.com`）设置 `GARMIN_REGION=international`
- Dropbox 路径默认是 `/Apps/Wahoo Fitness`，如果 Wahoo 使用了不同路径请修改
- 如果你只有短期 Access Token 也可以用 `DROPBOX_ACCESS_TOKEN`（放到 Secrets），但约 4 小时后过期，推荐用 Refresh Token

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
- 如果用 Access Token：确认未过期（约 4 小时有效期），过期后需重新生成
- 推荐切换到 Refresh Token 方式（长期有效，不会过期）
- 检查令牌/凭据是否有 `files.content.read` 和 `files.content.write` 权限

**Q: Garmin 登录失败？**
- 确认邮箱密码正确
- Garmin 可能启用了两步验证，需要在账号设置中生成应用专用密码
- 国区账号和国际区账号不能混用
- **国区用户注意**：Garmin 国区 (`garmin.cn`) 使用 Cloudflare 保护，标准 Python HTTP 库会被拦截。本项目使用 `curl_cffi` 进行 Chrome TLS 指纹伪装来绕过 Cloudflare，无需额外配置

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
export DROPBOX_REFRESH_TOKEN="your-refresh-token"
export DROPBOX_APP_KEY="your-app-key"
export DROPBOX_APP_SECRET="your-app-secret"
export GARMIN_REGION="china"

# 运行
python sync.py
```

Windows PowerShell:
```powershell
$env:GARMIN_EMAIL="your@email.com"
$env:GARMIN_PASSWORD="yourpassword"
$env:DROPBOX_REFRESH_TOKEN="your-refresh-token"
$env:DROPBOX_APP_KEY="your-app-key"
$env:DROPBOX_APP_SECRET="your-app-secret"
$env:GARMIN_REGION="china"
python sync.py
```

## 自定义配置

可以在仓库根目录创建 `.env` 文件用于本地测试：

```env
GARMIN_EMAIL=your@email.com
GARMIN_PASSWORD=yourpassword
DROPBOX_REFRESH_TOKEN=your-refresh-token
DROPBOX_APP_KEY=your-app-key
DROPBOX_APP_SECRET=your-app-secret
DROPBOX_FOLDER=/Apps/Wahoo Fitness
GARMIN_REGION=china
```

**注意：** `.env` 文件已加入 `.gitignore`，不会被提交到 GitHub。

## 更新日志

- **2026-07-07**: 初始版本，支持 Dropbox → Garmin 自动同步
- **2026-07-11**: 修复 Garmin 国区登录（改用 `is_cn` 参数）；状态持久化改用 actions/cache；README 更新 Refresh Token 说明
- **2026-07-11**: 国区登录改用 `curl_cffi`（Chrome TLS 指纹）绕过 Cloudflare 保护；国区上传改用 session-based `/gc-api/` 代理；增加完整错误堆栈输出

## 许可证

MIT License - 自由使用和修改

## 贡献

欢迎提交 Issue 和 PR！

---

**有问题？** 查看 [Issues](../../issues) 或提交新的问题。
