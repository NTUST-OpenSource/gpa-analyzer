<div align="center">
<a href="https://gpa.ntust.org">
  <img width="2000" src=".github/assets/banner.png" alt="GPA Analyzer Banner"/>
</a>
<br>

[![License](https://img.shields.io/github/license/NTUST-OpenSource/gpa-analyzer?style=for-the-badge)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.14-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)

 **繁體中文** | [English](README-en.md)

</div>

## 總覽

GPA Analyzer 是一個可以自行架設的成績可視化與分析工具

帳號密碼由使用者瀏覽器加密儲存，伺服器不儲存帳號密碼

### **成績計算**
- 每學期 / 整體 **GPA**
- 修習學分、已實得學分、修習中學分
- 二次退選 / 抵免

### **互動式圖表**
- 每學期 GPA 折線圖
- 各等第學分數堆疊圖，查看成績分佈

### **排名與課程**
- 班排、系排與歷年累計排名
- 完整課程清單，含課號、學分、成績、通識向度，可依學期篩選
- 自適應視窗大小

<br/>

## 快速開始

### Docker（建議）

```bash
# 產生 session 加密金鑰
SECRET_KEY=$(docker run --rm ghcr.io/ntust-opensource/gpa-analyzer:latest \
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

docker run -d --name gpa-analyzer \
  -p 8000:8000 \
  -e SECRET_KEY="$SECRET_KEY" \
  -v gpa-analyzer-cache:/data \
  ghcr.io/ntust-opensource/gpa-analyzer:latest
```

映像檔支援 `linux/amd64` 與 `linux/arm64`。

> [!IMPORTANT]
> 若要使用非加密的 `http://` 測試，請加上 `-e COOKIE_SECURE=false`

### Docker Compose

```yaml
services:
  gpa-analyzer:
    image: ghcr.io/ntust-opensource/gpa-analyzer:latest
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      SECRET_KEY: ${SECRET_KEY:?set SECRET_KEY in .env}
      # Address of the reverse proxy in front of this service, so client IPs are
      # read from X-Forwarded-For. Leave unset if nothing proxies to it.
      FORWARDED_ALLOW_IPS: ${FORWARDED_ALLOW_IPS:-127.0.0.1}
    volumes:
      - cache:/data

volumes:
  cache:
```

### 從原始碼執行

需要 [uv](https://docs.astral.sh/uv/) 與 Python 3.14。

```bash
git clone https://github.com/NTUST-OpenSource/gpa-analyzer.git
cd gpa-analyzer

cp .env.example .env
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# 把輸出填進 .env 的 SECRET_KEY，本機測試再把 COOKIE_SECURE 設為 false

uv sync
uv run python -m gpa_analyzer.app
```

開啟 <http://localhost:8000>，用學號與 Moodle 密碼登入。

<br/>

## 設定

所有設定都透過環境變數，可寫在 `.env`（參考 [`.env.example`](.env.example)）

讀取優先序為 **shell 環境變數 > `.env`**，已在 shell 匯出的值不會被 `.env` 覆蓋

| 變數 | 預設值                                      | 說明 |
|---|---------------------------------------------|---|
| `SECRET_KEY` | 無，**必填**                                | Fernet 金鑰，用來加密 session cookie。未設定時服務不會啟動 |
| `COOKIE_SECURE` | `true`                                      | session cookie 是否只走 HTTPS。設為 `true` 時 cookie 會加上 `__Host-` 前綴 |
| `HOST` / `PORT` | `0.0.0.0` / `8000`                          | 監聽位址與埠號 |
| `CACHE_DIR` | `.cache`（容器內為 `/data`）                | 爬蟲快取存放位置 |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1`                                 | 信任 `X-Forwarded-For` 的來源 IP，**請填實際反向代理的位址** |
| `TRUSTED_ORIGINS` | 空                                          | 額外接受的 Origin 主機名稱，以逗號分隔。僅在反向代理會改寫 `Host` 時需要 |
| `LOGIN_FAILURE_LIMIT` | `5`                                         | 每 5 分鐘、每帳號允許的登入失敗次數 |
| `LOGIN_ATTEMPT_LIMIT` | `10`                                        | 每 5 分鐘、每 IP 允許的登入嘗試次數 |
| `API_RATE_LIMIT` | `10`                                        | 每 5 分鐘、每帳號允許的 API 請求次數 |
| `NTUST_USERNAME` / `NTUST_PASSWORD` | 無                                          | 僅供命令列模式使用，Web 服務不會讀取 |

> [!NOTE]
> 若遇到登入會被 403 阻擋，可能是反向代理沒有保留原始 `Host` 標頭，請設定 `TRUSTED_ORIGINS`

### 命令列

不啟動 Web 服務，直接輸出 JSON：

```bash
uv run python -m gpa_analyzer.analyzer <學號> <密碼>

# 在 .env 中設定 NTUST_USERNAME / NTUST_PASSWORD
uv run python -m gpa_analyzer.analyzer
```

<br/>

## 安全性

這個服務會處理你的學校帳號密碼，設計上做了以下處理：

| 項目 | 作法                                                                                                                                  |
|---|---------------------------------------------------------------------------------------------------------------------------------------|
| **憑證儲存** | 以 Fernet（AES-128-CBC + HMAC）加密後存在瀏覽器 cookie，伺服器不保存資料庫。cookie 為 `HttpOnly` + `SameSite=Strict`，預設 7 天後失效 |
| **為何需要保存密碼** | 學校成績系統沒有 API 或長效 token，每次查詢都必須重新登入，因此密碼必須可還原                                                         |
| **TLS** | 對學校系統的連線會完整驗證憑證鏈、有效期限與主機名稱                                                                                  |
| **Cookie 快取** | 學校的 session cookie 索引快取 30 分鐘                                                                                                |
| **暴力破解** | 登入失敗每帳號限 5 次 / 5 分鐘；登入嘗試每 IP 限 10 次 / 5 分鐘；API 每帳號限 10 次 / 5 分鐘                           |
| **XSS** | 嚴格 CSP、無 CDN                                                                                                                      |
| **CSRF** | `SameSite=Strict` cookie，登入與登出皆檢查 Origin，登出只接受 POST                                                                    |

> [!CAUTION]
> 發現安全問題請透過 [GitHub Security Advisory](https://github.com/NTUST-OpenSource/gpa-analyzer/security/advisories/new) 回報，請勿開公開 issue

<br/>

## 開發

```bash
uv sync --all-groups

uv run pytest              # 測試
uv run ruff check .        # 靜態檢查
uv run ruff format .       # 格式化
```

前端樣式由 Tailwind CSS 產生，修改 `templates/` 或 `static/app.js` 的 class 之後要重新建置：

```bash
npm install
npm run build              # 產出 static/vendor/tailwind.css
```

CI 會檢查 `static/vendor/tailwind.css` 是否為最新

### 專案結構

```
gpa_analyzer/app.py       FastAPI 應用：登入、session、API 端點
gpa_analyzer/analyzer.py  爬蟲、HTML 解析與 GPA 計算
templates/                Jinja2 樣板
static/                   前端資源（app.js 與自架的 vendor/）
assets/tailwind.css       Tailwind 原始樣式
tests/                    pytest 測試
```

<br/>

## 授權

Copyright (C) 2026 NTUST-OpenSource contributors

本專案採用 **GNU Affero General Public License v3.0 或更新版本** 授權，完整條款見 [LICENSE](LICENSE)

<br/>

## 免責聲明

本專案與國立臺灣科技大學無官方關聯。使用者需自行負責遵守學校的資訊系統使用規範
