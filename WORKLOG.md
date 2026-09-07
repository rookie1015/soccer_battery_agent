# Football Lottery Agent Worklog

日期：2026-06-16

## 项目位置

```text
E:\codex\football-lottery-agent
```

## 当前目标

构建一个用于中国大陆足球彩票「14场胜平负」和「任选9场」的信息采集、分析、推荐、推送工具。

定位：信息辅助与策略参考，不保证中奖。

## 2026-09-07 工作记录

- 按用户确认仅修改预算决策前三点：覆盖率优先、开放单/双/全包重新分配、接近概率的敏感性检验。原有预算容差与统计口径保持现状。
- 新增穷举七种非空子集的最优性校验、升为全包、概率标签置换、零概率、历史审计恢复、对冲锁定及容差回归测试；全量 `249 passed, 11 subtests passed`。
- 技术回放覆盖 26105、26106、26108、26109、26110、26111、26119，分别使用 500/1000 元预算和原有 50 元容差。保存于 `artifacts/26119_phone_audit/budget_regression.json`；没有更改任何历史原始报告。
- 26119 新版十四场票面成本 972 元、理论联合覆盖率约 0.3582%，实际赛果覆盖 9/14；此期快照晚于售彩截止，不作严格回测或上线效果承诺。
- Android 0.5.1（15）Debug 构建成功。构建机缺少 Python 3.11，Chaquopy 跳过构建期 pyc 预编译，打包 Python 源码；手机内置运行时仍是配置的 Python 3.11。
- Android API 36.1 模拟器确认本机引擎可用；26119 与 26110 的全部票面、原始建议、概率、预算和任九结果均与桌面端一致。玩法切换、敏感场次提示、历史恢复、冷启动及错误期号提示正常；崩溃缓冲和当前进程日志未发现 FATAL、Python traceback 或 ANR。

## 2026-09-04 工作记录

### 已完成：平局独立校准与 v5 实验闭环

- 新增独立平局校准层，使用平赔变化、亚洲浅盘、大小球水平和大小球降盘构造市场结构残差，单场平局对数概率位移限制在 `±0.055`。
- Dixon-Coles 的低比分平局质量与拟合联赛平局率只用于缩放市场结构修正的可信度，不再作为第二份数学证据相加。
- 生产预测、CLI、Android 内置 Python 引擎、移动 API、历史恢复及严格按期走步实验已接通平局校准系数和逐场审计字段。
- 模型版本升级为 `market-residual-1x2-v5`；旧版本实验和激活参数不会被 v5 读取。
- 已刷新 v5 实验：历史共 56 场，其中严格赛前样本 0 场、探索样本 42 场、排除样本 14 场，状态为 `collecting`，没有执行参数晋级。
- 已用第 26117 期生成 v5 Markdown/HTML 报告，逐场包含平局校准方向、幅度和证据说明。
- Android 版本升级为 `0.5.0`（versionCode `14`）。

### 当前验证

- Python 全量测试：`242 passed`。
- v5 实验报告：`reports/experiments/20260904T112356Z-market-residual-1x2-v5.md`。
- v5 实盘报告：`artifacts/latest_v5_draw_report.md`、`artifacts/latest_v5_draw_report.html`。
- Android Debug APK 使用 JDK 17 构建成功并覆盖安装到 API 36.1 模拟器。
- 模拟器冷启动、第 26117 期完整在线分析、v5 平局校准明细、拟合式 Dixon-Coles 审计、`0/168` 严格样本提示和历史恢复均通过，未发现 App FATAL 或 Python traceback。
- 设置页确认显示 `App 版本 0.5.0（14） · 市场残差与拟合式 Dixon-Coles`。
- 发布 APK：`football-lottery-agent-v0.5.0-debug.apk`；SHA-256：`D1D0870821310A83A769C65B4C2ECEC0A333B43439E66C2E437EAB96A5608B8D`。
- 严格效果验证仍需重新积累训练 84 场、独立测试 84 场，并覆盖至少 6 个测试期；该项不能用赛后或旧结构数据替代。

## 2026-09-03 工作记录

### 已完成：第三点，拟合式 Dixon-Coles

- 采集层不再只保存近20场平均值；新快照保存逐场日期、联赛、对手、主客场、比分、可用 xG 和中立场状态。
- 对已安全匹配的 FotMob 联赛，额外抓取当前与上一赛季的完整比赛池，避免用两支球队自身的高低比分误代整个联赛环境。
- 使用无第三方数值依赖的正则化 Poisson 拟合，联合估计联赛进球环境、联赛主场优势、球队进攻强度和防守脆弱度；对手强弱由同一比赛网络共同估计。
- 历史比赛使用 120 天半衰期，非同联赛和友谊赛降权；小样本球队、联赛效应及主场效应均向先验收缩。
- Dixon-Coles `rho` 根据历史低比分结构拟合；中立场取消主场优势。杯赛次回合继续走既有独立赛制修正，不在数学层重复计权。
- 旧快照或逐场数据不足时继续使用聚合回退；球队身份未安全匹配时不套用其他球队历史。
- 模型版本升级为 `market-residual-1x2-v4`，快照结构升级为 v2；旧 v3 实验和旧结构快照不能让 v4 晋级。

### 验证结果

- Python 全量测试：`236 passed`。
- Android Debug APK 使用 JDK 17 构建成功。
- APK：`android/FootballLotteryAndroid/app/build/outputs/apk/debug/app-debug.apk`；SHA-256：`8095428CAA9A25097FC8E747E332CEF651F3CF68346B99261C200C698770394B`。
- 使用26113执行真实采集、拟合和报告生成链路；快照约1.55MB，报告成功生成。
- 真实链路中英超、德甲、西甲已匹配场次分别取得约300至370场去重联赛/球队历史：6场完整拟合、1场小样本拟合、7场身份未匹配安全回退。
- 26113验证发生在赛后，只用于确认工程链路和数据过滤，不作为新模型命中率证据。
- 验证产物：`artifacts/26113_v4_validation_issue.json`、`artifacts/26113_v4_validation_report.md`、`artifacts/26113_v4_validation_report.html`。

### 后续要求

- v4 必须从新的快照结构重新积累严格赛前样本；当前旧严格样本不能证明拟合模型优于市场基线。
- 达到训练84场、独立测试84场且至少6个测试期之前，不自动激活新参数。

## 2026-09-02 工作记录

### 已完成：第七点，生产模型与回测口径统一

- App、生产预测与实验状态统一绑定当前模型版本，不再把旧线性校准结果当成市场残差模型的验证结果。
- 新增当前模型状态构建逻辑；实验缺失、损坏、版本不符或复盘更新后会自动刷新候选实验，但不会自动晋级生产参数。
- 严格晋级样本要求明确为训练 84 场 + 独立测试 84 场，共 168 场，并要求至少 6 个测试期。
- Android 文案改为展示市场残差模型、严格赛前样本和修正强度，不再把权重误称为线性占比。
- 修复 Android 历史报告从 Markdown 重建后丢失模型状态的问题；历史卡片现在也会附加同一份版本校验状态。

### 已完成：第四点，消除重复计权

- 模型架构升级为 `market-residual-1x2-v3`；旧 v2 实验和激活参数不会被 v3 读取。
- 市场、基本面和 Dixon-Coles 只进行一次融合。第二选项、预算压缩、战术平局及对冲候选排序直接使用最终综合概率，不再把相同证据重新加权。
- xG 不再写入战意；伤停和赛程只归基本面层，不再二次调整 Dixon-Coles 的预期进球。
- 当前阵容评分和缺席惩罚不再进入数学层，避免与伤停信号重复；数学层仅保留不含可用度影响的纸面阵容强度。
- 有真实 xG/进失球时，近期状态、低比分和平局率归数学层所有；基本面保留原始值供审计，但对应有效可靠度归零。
- 删除最终融合后的独立主客场近期胜率修正，避免同一批近期比赛样本再次改变概率。

### 验证结果

- Python 全量测试：`231 passed`。
- Android Debug APK 构建成功，使用 JDK 17。
- Android API 36.1 模拟器冷启动、历史加载及完整在线分析均成功，无应用崩溃。
- 模拟器重新生成第 26113 期报告：`20260902154659-26113-analysis`。
- 模拟器确认模型为 `market-residual-1x2-v3`，状态为 `collecting`，严格样本 `14/168`，仍使用默认修正强度。
- 新报告确认存在“直接使用最终综合概率，未再次累计各证据层”，不存在旧二次加权文案和“同场地近期表现”二次修正。
- The Odds API 未配置 Key；本次完整分析按既有逻辑使用新浪等现有来源完成。
- APK：`android/FootballLotteryAndroid/app/build/outputs/apk/debug/app-debug.apk`
- APK SHA-256：`1072099C7745E911C423B1ED673A9B551F8841D98AE6BCE77BE84959AE4DA7FE`
- 模拟器截图：`artifacts/emulator-v3-no-double-weight.png`

### 下次继续

- 当前修改尚未提交 Git、未打版本标签、未发布正式安装包。
- 剩余算法改进项尚未继续实施；下次从此前改进清单中的未完成项继续。
- v3 必须继续积累严格赛前快照和真实赛果，达到样本外门槛后才能考虑显式晋级。

## 已完成能力

### 1. 基础分析流水线

- 支持读取一期 14 场 JSON。
- 输出胜 / 平 / 负概率。
- 输出单选 / 双选 / 三选推荐。
- 输出风险等级。
- 自动推荐任选9保留 9 场、剔除 5 场。
- 生成 Markdown 报告。

常用命令：

```powershell
python -m football_lottery_agent run --input data\sample_issue.json --output reports\sample_report.md
```

### 2. 飞书 / 企业微信推送

- 支持飞书群机器人 webhook。
- 支持企业微信群机器人 webhook。
- 支持生成报告后直接发送。

命令：

```powershell
$env:FEISHU_WEBHOOK_URL="你的飞书 webhook"
python -m football_lottery_agent send-report --channel feishu --report reports\sample_report.md
```

```powershell
$env:WECOM_WEBHOOK_URL="你的企业微信 webhook"
python -m football_lottery_agent send-report --channel wechat --report reports\sample_report.md
```

### 3. 自动采集当前胜负彩赛程

当前使用新浪胜负彩页作为赛程源。

可采集：

- 当前期号
- 14 场赛程
- 联赛
- 开赛时间
- 主队 / 客队
- 主客队近期 W/D/L 状态

命令：

```powershell
python -m football_lottery_agent collect --output data\collected_issue.json
```

### 4. 新浪详情数据

已接入新浪移动端数据接口。

可采集：

- 欧赔均值
- 历史交锋
- 伤停信息
- 情报利好 / 不利因素

数据会进入：

```text
data\collected_issue.json
```

并在报告详细理由中展示。

### 5. 国外主流 bookmaker 赔率

已接入 The Odds API。

用途：聚合国外主流 bookmaker 的 1X2 赔率，例如 Pinnacle、Betfair、Unibet、William Hill 等。

需要 API Key：

```powershell
$env:THE_ODDS_API_KEY="你的_api_key"
```

命令：

```powershell
python -m football_lottery_agent collect --output data\collected_issue.json --foreign-odds
```

可选参数：

```powershell
--foreign-odds-regions uk,eu
--foreign-odds-bookmakers pinnacle,betfair,unibet,williamhill
--foreign-odds-sports soccer_fifa_world_cup
```

匹配成功时：

```text
sources.odds = foreign_bookmakers
sources.foreign_odds = {...}
```

如果没有 API Key 或匹配失败，会自动退回新浪欧赔均值。

### 6. FotMob 球队实力模型

已接入 FotMob `/api/data` 接口。

可采集 / 计算：

- 过去 20 场表现
- 胜 / 平 / 负率
- 主场胜率
- 客场胜率
- 场均进球
- 场均失球
- 最近 N 场 xG / xGA
- FotMob team id 自动匹配
- 综合实力评分

命令：

```powershell
python -m football_lottery_agent collect --output data\collected_issue.json --strength-model
```

调整 xG 样本：

```powershell
python -m football_lottery_agent collect --output data\collected_issue.json --strength-model --strength-xg-matches 20
```

实测当前期 14 场全部匹配到 FotMob 赛事和 team id。

实力模型会写回 `signals.home_form` / `signals.away_form`，因此会实际影响胜平负预测。

### 7. 线上专家推荐采集

已移除。

原因：公开专家推荐源长期不可稳定获取，实际运行中经常无法采集到公开、可验证的方案；为了避免维护无效数据源和干扰报告阅读，已删除该功能、CLI 参数和报告区块。

## 推荐的一键日常流程

```powershell
cd E:\codex\football-lottery-agent

python -m football_lottery_agent collect `
  --output data\collected_issue.json `
  --strength-model

python -m football_lottery_agent run `
  --input data\collected_issue.json `
  --output reports\collected_report.md
```

如果有 The Odds API Key：

```powershell
python -m football_lottery_agent collect `
  --output data\collected_issue.json `
  --strength-model `
  --foreign-odds
```

生成并推送飞书：

```powershell
python -m football_lottery_agent run `
  --input data\collected_issue.json `
  --output reports\collected_report.md `
  --send feishu
```

## 主要代码文件

```text
football_lottery_agent\cli.py
football_lottery_agent\collectors.py
football_lottery_agent\predictor.py
football_lottery_agent\strategy.py
football_lottery_agent\report.py
football_lottery_agent\notifier.py
football_lottery_agent\foreign_odds.py
football_lottery_agent\strength_model.py
football_lottery_agent\history.py
football_lottery_agent\html_report.py
football_lottery_agent\web_ui.py
```

## 测试状态

最后一次测试：

```text
26 tests OK
```

命令：

```powershell
python -m unittest discover -s tests
```

## 已知问题 / 后续方向

1. SofaScore 暂未接入
   - SofaScore API 直接请求返回 403。
   - 当前使用 FotMob 做球队实力模型。

2. FotMob xG 请求量
   - 默认只抓最近 8 场 matchDetails。
   - `--strength-xg-matches 20` 会更慢。
   - 建议日常先用 8，重要期再拉到 20。

3. 国外 bookmaker 赔率需要 API Key
   - The Odds API 未设置 key 时会自动跳过。
   - 后续可考虑缓存 quota、展示 bookmaker 分歧度。

4. 预测模型仍是启发式模型
   - 当前模型混合赔率、基础面、实力评分。
   - 后续可以加入历史回测、参数优化、冷门识别模型。

## 明天建议优先做

1. 增加一键命令，例如：

```powershell
python -m football_lottery_agent daily --strength-model --send feishu
```

已完成（2026-06-17）：

- 新增 `daily` 命令，一次完成采集当前期、生成报告、可选推送。
- 默认输出 `data\collected_issue.json` 和 `reports\collected_report.md`。
- 支持复用采集参数，例如 `--strength-model`、`--foreign-odds`、`--offline`、`--seed`、`--odds`。
- 支持 `--issue-output` 和 `--report-output` 自定义输出位置。
- 新增 CLI 单元测试。

常用命令：

```powershell
python -m football_lottery_agent daily --strength-model
python -m football_lottery_agent daily --strength-model --send feishu
```

另已完成比分预测增强（2026-06-17）：

- `Prediction` 新增 `scorelines`，每场输出 Top3 比分倾向。
- 比分模型基于胜平负概率反推预期进球，再用 Poisson 分布估算常见比分。
- 报告总表新增“比分倾向”列。
- 每场详细理由新增“比分倾向”说明。
- 新增测试覆盖比分输出与报告渲染。

另已完成可视化报告增强（2026-06-17）：

- 新增静态 HTML dashboard 输出，保留 Markdown 用于留档和推送。
- 分析 dashboard 展示摘要卡片、任九保留/剔除、逐场推荐、概率条、比分 Top3、风险徽标。
- 复盘 dashboard 展示命中率进度条、逐场命中状态、比分命中、任九取舍。
- `run` 支持 `--html-output`。
- `daily` 默认输出 `reports\collected_report.html`。
- `review` 默认输出 `reports\review_report.html`。
- 已生成示例：`reports\sample_score_report.html`、`reports\sample_review_report.html`。
- 已用本地浏览器检查桌面和手机宽度布局。

另已完成 52 周历史中心（2026-06-17）：

- 新增 `reports\history\index.html` 历史中心页面。
- 新增 `reports\history\index.json` 历史索引。
- 每次生成 HTML 分析/复盘时，会复制一份到 `reports\history\items\`，避免常规输出文件被覆盖后丢失历史。
- 历史中心最多保留最近 52 条记录。
- 历史中心支持下拉框和左侧列表选择历史报告，并在页面内 iframe 预览。
- `run`、`daily`、`review` 新增 `--history-dir` 和 `--no-history`。
- 已用样例生成分析/复盘历史，并用本地浏览器验证下拉切换。

另已完成专家推荐移除与复盘意外提示（2026-06-17）：

- 移除线上专家推荐功能、CLI 参数 `--expert-recs`、报告里的“专家推荐 Top3”区块。
- 删除专家推荐模块和对应测试，避免继续维护不可稳定获取的数据源。
- 复盘 HTML 新增“重大意外”区域。
- 当单选、低风险或置信度不低于 56% 的场次未命中时，会在复盘 HTML 顶部单独展示。

另已完成本地网页控制台（2026-06-17）：

- 新增 `football_lottery_agent\web_ui.py`，提供本地 HTML 控制台。
- 新增 CLI 命令 `python -m football_lottery_agent ui`。
- 新增 `start_ui.bat`，用户可双击启动。
- 控制台支持填期号并点击生成分析报告。
- 控制台支持粘贴赛果 CSV 并点击生成复盘报告。
- 控制台提供打开历史中心、打开 HTML 报告和 Markdown 报告的按钮。
- 已用浏览器验证页面加载、按钮展示和错误提示。

另已完成主流体育媒体线索接入（2026-06-17）：

- 新增 ESPN Soccer RSS。
- 新增 BBC Sport Football RSS。
- 新增 Sky Sports Football RSS。
- The Athletic 无稳定公开 RSS，改用公开搜索 `site:theathletic.com` 获取标题和链接线索。
- 每场新增 `sources.mainstream_media`。
- 报告详细理由新增“主流媒体：...”线索展示。
- 只抓公开标题/链接，不抓付费正文。
- 已用 26087 期重跑，报告中出现 ESPN、BBC Sport、Sky Sports 等线索。

另已完成自动复盘赛果抓取（2026-06-17）：

- `review` 命令的 `--results` 改为可选。
- 不传 `--results` 时，默认按 issue 期号从新浪胜负彩页面读取比分列。
- 网页控制台复盘默认勾选“自动从新浪拉取赛果”。
- 如果新浪页面尚未更新完整赛果，会提示缺少哪些场次。
- 手工粘贴赛果 CSV 仍保留为备用方案。
- 当前 26087 尚未完赛，自动复盘会提示 1-14 场赛果缺失，这是预期行为。

2. 增加复盘功能：

```powershell
python -m football_lottery_agent review --issue data\collected_issue.json --results data\results.csv
```

已完成（2026-06-17）：

- 新增 `review` 命令，可对一期 issue 和赛果 CSV 生成复盘报告。
- 赛果 CSV 支持 `seq,score`，例如 `1,2-1`。
- 赛果 CSV 也支持 `seq,home_goals,away_goals`。
- 复盘报告统计胜平负命中、单选命中、比分 Top1 / Top3 命中、任九保留命中、任九剔除有效性。
- 新增 `data\results.example.csv` 和 `data\sample_results.csv`。
- 新增复盘单元测试和 CLI 测试。

常用命令：

```powershell
python -m football_lottery_agent review `
  --issue data\collected_issue.json `
  --results data\results.csv `
  --output reports\review_report.md
```

## 当前稳定跟踪方式（2026-06-17）

面向非命令行使用，推荐直接双击：

```text
start_ui.bat
```

浏览器会打开“足球彩票助手控制台”，可在页面内完成：

- 填期号并生成赛前分析。
- 默认自动拉取赛果并生成赛后复盘，必要时可粘贴赛果 CSV 兜底。
- 打开 HTML 报告、Markdown 报告和历史中心。

当前已按正在发售的 `26087` 期执行过一次完整分析流程：

```text
data\collected_issue.json
reports\26087_report.md
reports\26087_report.html
reports\history\index.html
```

当前 26087 任九建议：

```text
建议保留：2、3、4、5、6、8、11、12、14
建议剔除：1、7、9、10、13
```

当前测试状态：

```text
26 tests OK
```

3. 把报告里的“任九剔除逻辑”和“胆材候选”讲得更清楚。

4. 如果有 The Odds API Key，实测外盘匹配率和 bookmaker 分歧度。
