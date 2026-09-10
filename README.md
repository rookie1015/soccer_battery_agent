# Football Lottery Agent

面向中国大陆足球彩票「14 场胜平负」和「任选 9 场」的分析辅助工具。项目提供独立 Android App、Python 命令行和本地浏览器控制台。

> 本项目只用于信息整理、概率分析和策略研究，不保证中奖。请控制预算，理性购彩。

## 当前版本

- Android：`0.5.4`（versionCode `18`）
- 更新日期：`2026-09-10`
- Python：`3.10+`
- 自动测试：`253` 项，另含 `11` 个子测试

## Android App

Android App 已通过 Chaquopy 内置完整 Python 分析引擎，不需要电脑后端，也不需要填写服务器地址。手机在分析当前期次时仍需联网获取赛程、赔率和球队资料。

目前包含四个页面：

1. **分析**：输入期号和最高购彩金额，生成 14 场及任九建议。
2. **复盘**：自动获取赛果或使用手工 CSV，对照指定的历史分析快照。
3. **奖金**：按日历显示十四场与任九中奖情况，并自动补算手机中的旧复盘记录。
4. **设置**：保存 The Odds API Key、可选的 football-data.org 免费 Token，查看 API 用量并测试手机内置分析引擎。

历史分析报告支持长按删除：长按期号卡片删除该期全部分析，展开后长按单条记录只删除该记录；删除前会再次确认，复盘记录不受影响。

分析运行期间，主按钮会切换为“取消分析”。点击后界面立即恢复，后台采集在当前网络请求结束后停止，并且不会保存本次报告或新增历史记录。

### 手机分析的默认行为

- 不再提供“简单 / 完整”模式选择，只执行完整分析。
- 球队增强样本固定为最近 `20` 场，不由用户调整。
- App 只执行完整分析；当约三分之二比赛的多个关键资料源同时发生请求失败、供应商错误或赛程标识缺失时，停止分析并用中文提示具体问题，不生成不完整报告。
- 网络导致完整分析无法执行时，App 会用中文列出发生问题的关键资料类型，并明确本次没有生成分析报告。
- 单个来源没有数据、未匹配球队或确认无伤停，不会被误判为全局网络故障。
- 14 场实际出票使用正规复式计价：各场“预算票面”的选择数量相乘得到注数，再按每注 2 元计算总成本。
- 最高购彩金额是成本上限；优化器在上限内联合选择单选、双选和全包，离散的复式乘积不保证恰好花满预算。
- “模型建议”保留预算压缩前的判断范围，仅“预算票面”参与实际出票和成本计算；不再把抽样的独立单式线路合并成一张多选复式票。
- 标准分析报告展示推荐、胜平负概率、置信度和分析依据，不再展示风险等级及比分倾向。
- 比分模型仍在内部保留，供单场预测和赛后复盘使用。

### 构建 APK

在 Windows PowerShell 中运行：

```powershell
cd android\FootballLotteryAndroid
.\gradlew.bat assembleDebug
```

生成位置：

```text
android\FootballLotteryAndroid\app\build\outputs\apk\debug\app-debug.apk
```

安装后可在第四页确认版本号。新版设置页应显示：

```text
App 版本 0.5.4（18） · 旧复盘奖金自动补算
```

## 数据来源

| 来源 | 主要用途 | 是否直接影响概率 |
| --- | --- | --- |
| 中国体彩网官方接口 | 期号、开售时间、购彩截止时间 | 用于期次校验，不直接调概率 |
| 新浪胜负彩与新浪数据网关 | 14 场赛程、欧赔、初盘/即盘、亚洲让球、伤停、交锋、赛前情报、赛果 | 结构化且有效时参与 |
| FotMob | 近期比赛、进失球、阵容、球员状态、球队实力 | 匹配成功且样本有效时参与 |
| SofaScore | 补充比赛级 xG/xGA 和缺失球队数据 | 作为 FotMob 的补充来源 |
| 500网 / 中国足彩网 | 逐场赛程、公开欧赔和亚洲让球交叉核验 | 不覆盖正常新浪数据；新浪欧赔缺失时才补缺 |
| football-data.org | 免费 Token 覆盖范围内的赛程时间与比赛状态 | 可选辅助核验，不直接调概率 |
| DBpedia | 中文俱乐部简称与英文实体名称桥接 | 仅用于验证并保存球队身份，不直接改变概率 |
| The Odds API | 国外 bookmaker 的 1X2、让球和大小球 | 匹配成功时参与 |
| ESPN / BBC Sport / Sky Sports | 主流媒体标题 | 仅展示，不通过关键词改变概率 |
| Google News / GDELT / DuckDuckGo | 新闻搜索与资料线索 | 仅展示，不通过关键词改变概率 |
| Polymarket | 预测市场背景信息 | 仅展示，不直接改变概率 |

所有来源都可能出现无数据、球队名称不一致、地区限制或临时不可用。完整分析会为每场保存资料审计状态，区分：可用、确认无记录、未匹配、请求失败和供应商错误。

## 判断流程

一次完整分析大致按以下顺序执行：

1. 获取并校验期号、14 场赛程与截止时间。
2. 收集新浪结构化资料，并用500网、中国足彩网及可选 football-data.org 对赛程和公开赔率进行辅助核验。
3. 获取 FotMob / SofaScore 最近 20 场球队数据、xG 和阵容信息。
4. 如果设置了 The Odds API Key，查询国外 1X2、让球和大小球数据。
5. 对公司欧赔去除水位，计算市场共识、离散度以及初盘到即盘变化。
6. 以去水后的多公司赔率概率为市场锚点；缺少有效资料时，其他层不会使用中性默认值强行改变市场判断。
7. 数学模型使用带时间衰减的拟合式 Dixon-Coles，联合估计联赛环境、主场优势和球队攻防；逐场历史不足时才回退到收缩后的聚合模型。
8. 平局独立校准根据平赔变化、浅盘和大小球结构做有上限的残差修正；低比分质量与联赛平局率只控制可信度，不重复叠加数学证据。
9. 主选、第二选项、预算压缩和对冲排序都直接使用同一个最终综合概率，不再二次累计市场、基本面或数学证据。
10. 十四场在预算及已配置容差内最大化整票理论联合覆盖率，每场都可重新分配单选、双选或全包，不受原始模型建议范围限制；强制单选只在覆盖率相同时参与取舍。任九共享基础概率，但独立联合优化 9 个场次及票面，两种玩法分别计价。
11. 保存本次赛前 JSON 快照、分析报告和历史记录，供赛后复盘与严格回测使用。

十四场逐场依据增加预算稳定性检验：固定本场选择数量，在任意两项间转移 0.5/1.0 个百分点且保持总概率不变，记录换选场景数。它只说明局部排序对小幅变化是否敏感，不是错误概率或置信区间，也不重新分配整票预算；目前不据此修改胜平负权重或固定优先平局。原有默认 50 元预算容差保持不变。

### 关于平局

平局不是固定第二选项。系统会综合考虑：

- 去水后的平局概率及公司共识；
- 主客两项概率差距；
- Dixon-Coles 低比分相关性；
- 双方近期平局率、进球能力和防守强度；
- 亚洲让球、大小球和赔率变化；
- 伤停、阵容、赛程及结构化赛前情报。

当多个选项概率接近时，完整分析会使用这些证据决定第二项。没有可靠证据时保持保守，不会用默认中性数值冒充已采集资料。

每期最多产生一场“战术单平”。它要求真实市场、质量达标的数学模型，以及赔率结构或低比分/平局倾向信息共同支持；战术单平始终标记为高风险，不等同于 60% 门槛的稳胆单选。没有场次达标时不会强行指定。

## The Odds API

The Odds API 是可选外盘来源。没有 Key 时系统仍可使用新浪等来源完成分析；有 Key 且成功匹配时，国外 bookmaker 数据会进入赔率判断。

在 Android 第四页填写并保存 Key 后，可以查看：

- Key 是否有效；
- 剩余额度；
- 当前周期累计已用额度；
- 本次用量查询消耗；
- 当前开放的体育项目数量。

用量刷新调用官方 `/v4/sports` 接口，本身不消耗赔率额度。“刷新 API 用量”和“测试本机引擎”是两个独立功能。

每次分析报告顶部还会记录：

- 本次是否真实联网调用；
- 是否使用 5 分钟缓存；
- 请求次数与成功次数；
- 外盘赛事匹配数；
- Key 无效、额度耗尽、请求受限或调用成功但未匹配等原因；
- API 响应头返回的剩余、累计使用和本次赔率请求消耗。

外盘失败时会自动回退到新浪等现有赔率来源，不会让整期分析直接中断。

## 免费辅助信源

500网和中国足彩网无需配置，完整分析会各请求一次对应期号的14场数据。它们的定位是新浪辅助源：

- 新浪数据正常时，只记录赔率方向是否一致以及明显差异，不覆盖新浪；
- 新浪欧赔缺失时，才使用已匹配辅助源的公开欧赔均值补缺；
- 辅助源请求失败不会中断完整分析，报告快照会保存每个来源的获取和匹配状态；
- 国内聚合站可能延迟更新赛程，延期或取消仍应以赛事组织方、俱乐部和国家体彩中心公告为准。

football-data.org 免费档需要申请 Token，且只覆盖其免费方案包含的赛事。在 App 设置页填写后，它会补充核验开球时间和比赛状态；不填写时明确记录为“未配置”，不会报错。命令行也可使用环境变量：

```powershell
$env:FOOTBALL_DATA_API_KEY="你的免费Token"
```

命令行使用方式：

```powershell
$env:THE_ODDS_API_KEY="你的_api_key"
python -m football_lottery_agent collect `
  --output data\collected_issue.json `
  --foreign-odds `
  --foreign-odds-regions uk,eu
```

也可以限定 bookmaker 或 sport key：

```powershell
python -m football_lottery_agent collect `
  --output data\collected_issue.json `
  --foreign-odds `
  --foreign-odds-bookmakers pinnacle,betfair,unibet,williamhill `
  --foreign-odds-sports soccer_fifa_world_cup
```

## 赛后复盘与学习

手机上的历史结果不会仅因为“已经存在”就自动改变模型。只有执行复盘后，赛果才会与对应的赛前快照关联并进入实验样本。

复盘和学习遵循以下规则：

- 每次分析保存独立赛前快照，避免同一期最后一次采集覆盖旧判断。
- 同一期存在多次分析时，复盘会要求选择具体分析记录。
- 回测按完整期号向前走，训练集只能使用测试期之前的数据，避免未来信息泄漏。
- 旧数据或采集时间不完整的数据只能进入探索轨道，不能直接启用新模型。
- 概率权重与单选/双选/全包策略分别通过样本外门槛后，才会写入生产配置。
- 未通过 Brier、Log Loss、Top1、平局召回和冷门召回等门槛时，继续使用默认模型。
- App 展示的模型状态与生产预测统一使用当前 `market-residual-1x2-v5` 实验；数学层使用带时间衰减、联赛环境、球队攻防强度、对手校正和中立场处理的拟合 Dixon-Coles，每类证据只进入一个负责层；旧线性混合校准只保留作历史兼容，不会作为生产参数。
- v5 的平局独立校准只用市场结构产生残差修正，默认对数概率位移上限为 `0.055`；Dixon-Coles 的低比分结构和联赛平局率仅用于缩放可信度。校准系数只有通过相同的严格按期走步门槛后才会激活。
- 升级模型版本或新增复盘后，App 会自动刷新当前版本的候选实验，但不会自动晋级；晋级仍需显式请求并通过全部样本外门槛。

命令行复盘：

```powershell
python -m football_lottery_agent review `
  --issue data\collected_issue.json `
  --output reports\review_report.md
```

如果自动赛果尚未更新，可使用 CSV：

```csv
seq,score
1,2-1
2,1-1
3,0-2
```

```powershell
python -m football_lottery_agent review `
  --issue data\collected_issue.json `
  --results data\results.csv `
  --output reports\review_report.md
```

运行纯胜平负走步回测：

```powershell
python -m football_lottery_agent experiment --work-dir .
```

手工请求晋级仍会执行全部门槛，不会强制覆盖生产模型：

```powershell
python -m football_lottery_agent experiment --work-dir . --promote
```

## Python 快速开始

创建环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

使用示例数据生成报告：

```powershell
python -m football_lottery_agent run `
  --input data\sample_issue.json `
  --output reports\sample_report.md `
  --html-output reports\sample_report.html
```

一键采集当前期并生成报告：

```powershell
python -m football_lottery_agent daily --strength-model
```

完整采集命令示例：

```powershell
python -m football_lottery_agent collect `
  --output data\collected_issue.json `
  --strength-model `
  --strength-lookback 20 `
  --strength-xg-matches 20
```

如果更信任自己整理的赔率，可提供 CSV：

```csv
seq,home,draw,away
1,1.62,4.10,5.20
```

```powershell
python -m football_lottery_agent collect `
  --output data\collected_issue.json `
  --odds data\odds.csv
```

球队匹配会优先使用已确认的 FotMob / SofaScore 球队 ID，再使用共享别名和完整赛程的联赛、开球时间与主客队组合。同联赛同时间只有一场候选时会直接反推双方身份；仍有多场候选时，使用 DBpedia 中英文足球俱乐部实体作桥接，并且只有主客两队共同唯一指向同一场供应商赛事时才会绑定。确认的新别名和球队 ID 会写入缓存目录旁的 `team_identity.json`，下次分析和 App 升级后继续使用；低置信度或歧义候选只写入采集诊断，不会自动绑定。国家成年队、青年队和女足不会仅凭名称包含关系互相匹配。

如果仍有未匹配球队，可参考 `data/team_ids.example.csv` 手工指定 FotMob ID。该文件继续作为紧急覆盖入口。

## 本地浏览器控制台

Windows 可直接双击：

```text
start_ui.bat
```

或运行：

```powershell
python -m football_lottery_agent ui
```

控制台支持分析、复盘、单场预测，以及飞书 / 企业微信群机器人推送。Webhook 建议通过环境变量配置：

```powershell
$env:FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/你的token"
$env:WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key"
```

## 测试

运行 Python 测试：

```powershell
python -m pytest -q
```

构建 Android：

```powershell
cd android\FootballLotteryAndroid
.\gradlew.bat assembleDebug
```

## 项目结构

```text
football-lottery-agent/
  android/FootballLotteryAndroid/  Android 独立客户端
  data/                            示例输入和映射模板
  docs/                            接口说明
  football_lottery_agent/          Python 核心分析代码
  ios/                             iOS 客户端草稿
  reports/                         本地生成的报告与历史记录（不提交）
  tests/                           自动测试
  CHANGELOG.md                     更新记录
```

## 推荐符号

- `3`：主胜
- `1`：平局
- `0`：客胜
- `3/1`、`1/0` 等：双选防守
- `3/1/0`：三项全包

更多版本变化见 [CHANGELOG.md](CHANGELOG.md)。
