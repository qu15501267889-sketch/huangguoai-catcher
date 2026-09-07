# 黄果短剧 AI成人短剧 自动下载器 (v3)

全量爬取 `huangguoai.com` **AI成人短剧**分类，每部剧分集（mp4）增量自动下载，跑在 **NAS Docker** 里，开机常驻。

## v3 架构（模块化重构）

从 900+ 行单文件拆成**多模块包 `hgcatcher/`**，职责单一、可测试、易扩展：

```
hgcatcher/
├── cli.py           # 入口(薄壳)：argparse + 组装
├── config.py        # 配置加载/校验/环境变量覆盖
├── logging_utils.py # 日志(控制台+滚动文件)
├── http.py          # 线程安全Session + 限流 + 重试fetch
├── parsers.py       # 站点解析器(抽象BaseParser + 工厂)
├── crypto.py        # 图床AES解密 + 封面抓取
├── downloaders.py   # 下载器(抽象BaseDownloader + 注册表)
├── metadata.py      # 封面/简介/.nfo 并发写
├── orchestrator.py  # 编排(枚举/discover/并发调度) + Hook事件
├── watchdog.py      # 健康检查/主动提醒/垃圾清理
└── utils.py         # ffmpeg/ffprobe/manifest原子写/字节格式化
```

## 升级接口（预留扩展）

| 接口 | 用途 |
|---|---|
| `BaseParser` + 注册表 | 站点改版/新增站点 → 实现一个新 parser 并 `register("名")` |
| `BaseDownloader` + `DOWNLOADERS` | 新下载方式(yt-dlp等) → 继承并 `register_downloader(cls)` |
| `Hook` 事件 | `on_series_enum`/`on_episode_done`/`on_run_done` → 接数据库/自定义通知 |
| `config.json` + 环境变量 `HG_*` | 纯环境变量跑 Docker，或文件配置 |

## 性能优化

- **正则全部模块级预编译**（不再每次解析重 compile）
- 请求复用连接（线程安全 Session）
- chunked 分片 `done` **攒批落盘**（每 16 片一次，减少 IO）
- discover/meta 并发化，全量首跑不再串行等待

## 特性

- 全量枚举 + 抗断页（连续2空页才中止）
- 逐集无漏（manifest 集合 diff）
- 增量下载 + 每集原子落盘
- 下载完 ffprobe 校验时长
- 改版自动检测 + webhook 提醒（bark/serverchan/wecom/webhook）
- 垃圾自动清理（.part.ts/.ep*/.tmp，不误删）
- ffmpeg / chunked 双下载模式

## 输出结构

```
<OUT>/
└── <剧名>(id<剧id>)/
    ├── poster.jpg
    ├── <剧名>.nfo
    ├── info.txt
    ├── ep01.mp4
    └── ...
```

## Docker 部署

```bash
cd /vol1/docker/huangguoai-catcher
docker compose up -d --build
docker logs -f huangguoai-catcher
```

## 本机跑

```bash
pip install -r requirements.txt
python -m hgcatcher --config config.json --out 输出 --manifest 状态.json --with-meta
```

## 测试

```bash
pip install pytest
python -m pytest test_huangguoai.py -v
```
