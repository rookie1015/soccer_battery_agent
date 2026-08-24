# 2026-08-22 至 2026-08-23 未上传修改记录

记录时间：2026-08-24（Asia/Shanghai，含 8 月 24 日复盘后修复）

本文件用于以后一次性提交、推送和发布。当前只做记录，没有执行新的 Git 提交、标签或远端推送。

## 一、Git 状态快照

- 当前分支：`android`
- 远端跟踪分支：`origin/android`
- 远端当前提交：`059accf`（`v0.3.0`）
- 本地当前提交：`4bff609`（`v0.3.4`）
- 分支关系：本地比远端领先 4 个提交。
- 除 4 个本地提交外，还有 v0.3.5 的未提交工作区修改。
- 当前版本保持：Python/Android `0.3.5`，Android versionCode `11`。

## 二、已提交但尚未推送的 4 个版本

| 版本 | 提交 | 日期 | 主要内容 |
| --- | --- | --- | --- |
| v0.3.1 | `05a6a5e` | 2026-08-22 19:17 +08:00 | 主票与独立小预算平局对冲、预算删平复盘、辅助信源核验、Android 完整分析错误提示。 |
| v0.3.2 | `12f9ac9` | 2026-08-22 19:56 +08:00 | 多平独立线路组合、平局配额、线路级复盘、Android/iOS/API/报告展示。 |
| v0.3.3 | `96e7f79` | 2026-08-22 20:17 +08:00 | 修复历史记录恢复线路组合及金额错误，支持旧报告解析。 |
| v0.3.4 | `4bff609` | 2026-08-22 21:17 +08:00 | 精简 Android 线路展示，不再展开数百条线路，保留内部组合和复盘数据。 |

以上 4 个提交已有本地标签：`v0.3.1`、`v0.3.2`、`v0.3.3`、`v0.3.4`；尚未推送到远端。

## 三、尚未提交的 v0.3.5 修改

### 1. Android 网络容错和诊断

- DBpedia 球队别名查询属于可选增强源；Java `SocketTimeoutException` 等 Android 网络异常不再中止整份分析。
- 别名服务失败时回退到内置别名、赛程上下文和已有球队身份数据。
- Android 本机保存最近一次原始 Python 分析堆栈，App 对用户仍只显示清理后的中文错误。
- 相关文件：
  - `football_lottery_agent/bilingual_identity.py`
  - `football_lottery_agent/strength_model.py`
  - `android/FootballLotteryAndroid/app/src/main/python/android_bridge.py`
  - `android/FootballLotteryAndroid/app/src/main/java/com/example/footballlottery/MainActivity.kt`
  - 对应测试文件。

### 2. 十四场正规复式计价修复

- 删除“抽取若干独立单式线路后，将各场赛果并集合并显示为低价复式”的错误执行路径。
- 实际十四场票面改为矩形正规复式：14 场每场选择数相乘得到注数，再乘每注 2 元。
- “模型建议”只保留预算压缩前的分析范围；只有“预算票面”参与出票计价。
- 预算使用精确动态规划，在离散的单选/双选/全包乘积中寻找不超预算的方案。
- 26111 在 1000 元上限下验证为 384 注、768 元。

### 3. 任九独立模型优化

- 任九与十四场共享同一套赛前基础概率，但不再按十四场建议覆盖率简单排序。
- 任九独立联合优化：从 14 场选择恰好 9 场，同时确定每场单选、双选或全包。
- 使用精确动态规划最大化预算内理论联合覆盖率。
- 任九拥有独立票面、注数、成本和独立预算上限；若与十四场同时购买，两项金额必须相加。
- API 新增 `choose9` 结构，同时保留兼容字段 `choose9_keep`、`choose9_drop`。
- Markdown、HTML、Android、飞书文本和历史解析展示任九独立票面、成本及理论覆盖率。
- 复盘改为按任九自己的票面统计命中，不再使用十四场预算票面代替。
- Android API 36.1 模拟器实际生成 26111：任九 486 注、972 元；冷启动后历史恢复结果一致。

### 4. 主客方向与球队身份污染修复

- 26110 复盘定位到“巴黎 vs 雷恩”主客方向污染：运行时身份曾错误学习为“巴黎=Rennes、雷恩=PSG”，并把新浪主胜/客胜赔率镜像写入。
- 唯一联赛与开球时间不再用于猜测两个未知球队的主客方向；只有已有球队证据能够明确方向时才持久化别名。
- 已内置巴黎圣日耳曼、雷恩的核验别名，并在加载身份库时自动清除与种子身份冲突的旧 kickoff-only 别名及供应商 ID。
- 期次专属辅助赔率若确认主源为主客镜像，会自动交换主胜/客胜；其他严重冲突改用已验证的期次专属辅助赔率，不再只提示后继续采用冲突主源。
- 已清理根目录 `team_identity.json` 中污染的巴黎/雷恩映射，并增加对应回归测试。

### 5. 版本、文档和测试

- Android：versionName `0.3.5`、versionCode `11`。
- Python：`pyproject.toml` 与 `football_lottery_agent/__init__.py` 均为 `0.3.5`。
- 已更新 `CHANGELOG.md`、`README.md`、`docs/mobile-api.md` 和 `docs/releases/0.3.5.md`。
- Python 全量测试：`214 passed`。
- Android：使用 Microsoft JDK 17.0.20 执行 `assembleDebug` 成功。
- Android 模拟器：安装、完整分析、界面金额/票面核对、冷启动历史恢复通过；App FATAL 异常为 0。

## 四、当前未提交的受跟踪文件

以下文件属于 v0.3.5 代码和文档修改，后续应在复核后提交：

- `CHANGELOG.md`
- `README.md`
- `android/FootballLotteryAndroid/app/build.gradle.kts`
- `android/FootballLotteryAndroid/app/src/main/java/com/example/footballlottery/MainActivity.kt`
- `android/FootballLotteryAndroid/app/src/main/python/android_bridge.py`
- `docs/mobile-api.md`
- `football_lottery_agent/__init__.py`
- `football_lottery_agent/bilingual_identity.py`
- `football_lottery_agent/auxiliary_sources.py`
- `football_lottery_agent/html_report.py`
- `football_lottery_agent/mobile_api.py`
- `football_lottery_agent/models.py`
- `football_lottery_agent/report.py`
- `football_lottery_agent/review.py`
- `football_lottery_agent/standalone_api.py`
- `football_lottery_agent/strategy.py`
- `football_lottery_agent/strength_model.py`
- `pyproject.toml`
- `tests/test_bilingual_identity.py`
- `tests/test_auxiliary_sources.py`
- `tests/test_team_identity.py`
- `tests/test_strength_model.py`
- `tests/test_html_report.py`
- `tests/test_mobile_api.py`
- `tests/test_review.py`
- `tests/test_standalone_api.py`
- `tests/test_strategy.py`

新增且应提交：

- `docs/releases/0.3.5.md`
- `docs/unuploaded-changes-2026-08-22-to-2026-08-23.md`

## 五、构建产物与校验

- 最新 APK：`football-lottery-agent-v0.3.5-debug.apk`
- 文件大小：42,983,302 字节。
- SHA-256：`FF506895BAB0326BBCD066F8B58C98C316AF05ECDD17AEEE4E869AA091D8D6E9`
- APK 元数据：versionName `0.3.5`，versionCode `11`，minSdk 26，targetSdk 35。
- 模拟器验证截图：`artifacts/26111-emulator-choose9-validation.png`。
- 模拟器生成报告：`artifacts/26111_emulator_report.md`。

APK 建议作为 GitHub Release 附件上传，不建议直接加入 Git 仓库历史。

## 六、未跟踪文件的上传分类

### 建议纳入代码提交

- `docs/releases/0.3.5.md`
- 本记录文件。
- `team_identity.json`：当前为根目录下 35,338 字节的球队别名和供应商 ID 目录，未发现明显密钥；它看起来是运行时身份匹配数据。正式上传前应再确认是否希望将这类可增长数据纳入版本控制。

### 建议作为发布附件

- `football-lottery-agent-v0.3.5-debug.apk`
- 如需要保留历史安装包，可单独归档到 Release，不要全部加入 Git 仓库。

### 默认不要上传

- `cache/`：当前约 1,489 个未跟踪缓存文件，包含外部服务响应和运行时缓存。
- `artifacts/`：当前约 21 个模拟器 XML、截图和临时验证文件；只在需要保留验证证据时选择性上传截图或报告。
- 根目录的 10 份旧 APK：体积较大，应作为本地归档或 Release 附件处理。
- `reports/`、采集快照和 Android 构建目录：已经由 `.gitignore` 排除，继续保持本地生成。

警告：后续不要直接执行 `git add .`，否则可能把大量缓存、调试 XML、旧 APK 和临时身份数据一起加入提交。

## 七、以后一次性上传的建议顺序

1. 再次运行全量测试与 Android 构建，确认工作区没有新增失败。
2. 查看 `git diff`，确认 v0.3.5 修改和本记录一致。
3. 明确 `team_identity.json` 是否纳入版本控制。
4. 只暂存代码、测试、正式文档和确定需要的身份数据；排除缓存、临时 artifacts 与 APK。
5. 创建 v0.3.5 提交，并在提交后创建本地 `v0.3.5` 标签。
6. 将 `android` 分支一次性推送到 `origin/android`，这会包含 v0.3.1 至 v0.3.5 的代码提交。
7. 推送 `v0.3.1` 至 `v0.3.5` 标签。
8. 创建 GitHub Release，并上传对应 APK 及 SHA-256。
9. 在远端复核分支 HEAD、标签、Release 附件和版本说明。

## 八、上传前最后核对项

- 不上传任何 `.env`、API Key、Webhook、Token 或本机路径配置。
- 检查 `team_identity.json` 只含球队别名和供应商 ID。
- 确认 APK 哈希与本记录一致；若重新构建，必须更新哈希。
- 确认版本仍为 `0.3.5` / versionCode `11`，除非用户明确要求升级。
- 确认十四场和任九分别计价的文案仍然存在。
- 用 1000 元预算复核十四场与任九注数均为各自票面选择数的乘积，且各自不超过上限。
