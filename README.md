# Football Lottery Agent

面向中国大陆足球彩票「14场胜平负」和「任选9场」的分析辅助项目。

定位：自动整理比赛信息、估算胜平负概率、生成 14 场和任 9 的投注参考报告。它不是保赚工具，只做信息和策略辅助。

## 当前能力

- 读取一期 14 场赛程 JSON
- 自动采集新浪胜负彩当前期赛程、主客队、近况
- 自动搜索赛前新闻、伤停、历史交锋线索
- 支持用 CSV 补充欧赔/平均赔率
- 用基础启发式模型估算胜 / 平 / 负概率
- 基于胜平负概率反推 Top3 比分倾向
- 输出每场推荐：单选、双选、三选、风险等级、理由
- 自动推荐任选9保留场次和剔除场次
- 生成 Markdown 报告
- 支持通过飞书或企业微信群机器人推送报告
- 内置示例数据，可直接跑通

## 快速开始

不想敲命令时，直接双击项目目录里的：

```text
start_ui.bat
```

浏览器会打开“足球彩票助手控制台”。在页面里填期号，点击“生成分析报告”即可。赛果出来后，复盘默认会自动从新浪拉取赛果；如果自动赛果没更新，再把比分粘到复盘框里手工生成。

控制台顶部还提供“单场比分预测”。手动输入主队和客队即可获得首选比分、两个备选比分、胜平负概率、置信度和风险。若比赛不在当前采集期中，可选填主胜、平局、客胜三项欧洲赔率以提高参考价值。

如需自动推送，在控制台勾选“每次生成后自动发送到飞书”，并填写飞书群机器人的 Webhook。Webhook 不会写入项目文件；也可以预先设置 `FEISHU_WEBHOOK_URL` 环境变量后将输入框留空。

如果是给手机 App 使用，直接双击：

```text
start_mobile_backend.bat
```

这个窗口会自动列出手机 App 设置里应该填写的后端地址。保持窗口打开，手机和电脑连同一个 Wi-Fi，在 App 设置里粘贴地址后点“测试连接”。

本次版本的完整功能变化见 [CHANGELOG.md](CHANGELOG.md)。

如果你熟悉命令行，也可以继续使用下面的命令方式。

```powershell
cd football-lottery-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m football_lottery_agent run --input data\sample_issue.json --output reports\sample_report.md
```

## 推送到飞书或企业微信

推荐使用群机器人 webhook。

飞书：

```powershell
$env:FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/你的token"
python -m football_lottery_agent send-report --channel feishu --report reports\sample_report.md
```

企业微信：

```powershell
$env:WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key"
python -m football_lottery_agent send-report --channel wechat --report reports\sample_report.md
```

也可以生成报告后立刻发送：

```powershell
python -m football_lottery_agent run --input data\sample_issue.json --output reports\sample_report.md --send feishu
```

如果你不想建虚拟环境，也可以直接：

```powershell
cd football-lottery-agent
python -m football_lottery_agent run --input data\sample_issue.json --output reports\sample_report.md
```

## 数据格式

## 自动采集

采集当前胜负彩期号和 14 场赛程，并自动补充新浪欧赔均值、历史交锋、伤停、情报线索：

```powershell
python -m football_lottery_agent collect --output data\collected_issue.json
```

### 国外主流 bookmaker 赔率

外盘赔率使用 [The Odds API](https://the-odds-api.com/) 聚合国外 bookmaker 的 `h2h` 赔率，也就是足球 1X2：主胜 / 平 / 客胜。

先设置 API Key：

```powershell
$env:THE_ODDS_API_KEY="你的_api_key"
```

采集时启用外盘：

```powershell
python -m football_lottery_agent collect --output data\collected_issue.json --foreign-odds
```

指定地区：

```powershell
python -m football_lottery_agent collect --output data\collected_issue.json --foreign-odds --foreign-odds-regions uk,eu
```

指定 bookmaker：

```powershell
python -m football_lottery_agent collect --output data\collected_issue.json --foreign-odds --foreign-odds-bookmakers pinnacle,betfair,unibet,williamhill
```

指定 The Odds API sport key：

```powershell
python -m football_lottery_agent collect --output data\collected_issue.json --foreign-odds --foreign-odds-sports soccer_fifa_world_cup
```

如果某场匹配成功，`odds` 会优先使用国外 bookmaker 均值，并在 `sources.foreign_odds` 保留 bookmaker 数量、匹配赛事、sport key 等信息。没有 API Key 或匹配失败时，会自动退回新浪欧赔均值。

### 球队实力模型

启用 FotMob 球队实力模型：

```powershell
python -m football_lottery_agent collect --output data\collected_issue.json --strength-model
```

模型会从 FotMob 读取：

- 过去 20 场结果
- 主场 / 客场胜率
- 场均进球 / 失球
- 最近若干场 xG / xGA
- FotMob 当日赛程匹配到的球队 id

默认只抓最近 8 场 `matchDetails` 来计算 xG，避免请求过多。你可以改成 20 场：

```powershell
python -m football_lottery_agent collect --output data\collected_issue.json --strength-model --strength-xg-matches 20
```

如果某队自动匹配失败，可以用 `data\team_ids.example.csv` 的格式维护映射：

```powershell
python -m football_lottery_agent collect --output data\collected_issue.json --strength-model --strength-team-ids data\team_ids.csv
```

### 一键日常流程

一条命令完成采集当前期、生成报告：

```powershell
python -m football_lottery_agent daily --strength-model
```

生成后直接推送飞书或企业微信：

```powershell
python -m football_lottery_agent daily --strength-model --send feishu
```

默认输出：

```text
data\collected_issue.json
reports\collected_report.md
reports\collected_report.html
reports\history\index.html
```

也可以指定输出位置：

```powershell
python -m football_lottery_agent daily --issue-output data\today.json --report-output reports\today.md
```

生成报告：

```powershell
python -m football_lottery_agent run --input data\collected_issue.json --output reports\collected_report.md
```

同时生成可视化 HTML：

```powershell
python -m football_lottery_agent run `
  --input data\collected_issue.json `
  --output reports\collected_report.md `
  --html-output reports\collected_report.html
```

一键采集、生成、推送飞书：

```powershell
python -m football_lottery_agent collect --output data\collected_issue.json
python -m football_lottery_agent run --input data\collected_issue.json --output reports\collected_report.md --send feishu
```

默认会使用新浪指数页的欧赔均值。如果你更信任自己整理的赔率，按 `data\odds.example.csv` 的格式保存：

```csv
seq,home,draw,away
1,1.62,4.10,5.20
```

然后采集时带上：

```powershell
python -m football_lottery_agent collect --output data\collected_issue.json --odds data\odds.csv
```

如果新浪源失效，或者你想手工指定 14 场，用 `data\seed_matches.csv`：

```powershell
python -m football_lottery_agent collect --seed data\seed_matches.csv --output data\collected_issue.json --offline
```

一期数据是 JSON，核心结构：

```json
{
  "issue": "sample-001",
  "matches": [
    {
      "seq": 1,
      "kickoff": "2026-06-20T22:00:00+08:00",
      "league": "英超",
      "home": "曼城",
      "away": "热刺",
      "odds": {"home": 1.62, "draw": 4.1, "away": 5.2},
      "signals": {
        "home_form": 0.78,
        "away_form": 0.61,
        "home_motivation": 0.72,
        "away_motivation": 0.65,
        "home_injury_impact": 0.08,
        "away_injury_impact": 0.18,
        "schedule_pressure_home": 0.22,
        "schedule_pressure_away": 0.15
      },
      "notes": ["主队主场稳定", "客队后防有伤停"]
    }
  ]
}
```

`signals` 里的数值范围是 0 到 1。初版先用人工、半自动或后续采集器填充这些信息。

## 推荐含义

- `3`：主胜
- `1`：平
- `0`：客胜
- `3/1`、`1/0` 等：双选防守
- `3/1/0`：三选，风险高或信息混乱

## 比分预测

报告中的“比分倾向”会展示每场 Top3 比分，例如：

```text
1-0 14%，1-1 12%，2-0 11%
```

当前比分模型会先用赔率和基本面生成胜 / 平 / 负概率，再反推预期进球并用 Poisson 分布估算常见比分。它适合辅助判断比赛节奏和防守方向，不等同于精确比分投注模型。

## 赛后复盘

准备赛果 CSV，推荐格式：

```csv
seq,score
1,2-1
2,1-1
3,0-2
```

也支持：

```csv
seq,home_goals,away_goals
1,2,1
2,1,1
3,0,2
```

生成复盘报告：

```powershell
python -m football_lottery_agent review --issue data\collected_issue.json --output reports\review_report.md
```

默认会按 issue 期号从新浪胜负彩页面自动拉取赛果。若自动源还没有更新，或你想手工指定结果，可以加 `--results`：

```powershell
python -m football_lottery_agent review --issue data\collected_issue.json --results data\results.csv --output reports\review_report.md
```

`review` 默认也会生成可视化 HTML：

```text
reports\review_report.html
reports\history\index.html
```

也可以显式指定：

```powershell
python -m football_lottery_agent review `
  --issue data\collected_issue.json `
  --results data\results.csv `
  --output reports\review_report.md `
  --html-output reports\review_report.html
```

复盘会统计：

- 胜平负命中率
- 单选命中率
- 比分 Top1 / Top3 命中率
- 任九保留场命中率
- 任九剔除是否有效避开错误

## 历史中心

生成 HTML 报告时，系统会默认把当次分析/复盘存入历史中心：

```text
reports\history\index.html
reports\history\index.json
reports\history\items\
```

历史中心保留最近 52 条记录。即使 `reports\collected_report.html` 或 `reports\review_report.html` 被下一次运行覆盖，`reports\history\items\` 中的历史副本仍会保留。

打开历史中心后，可以用下拉框或左侧列表切换历史分析/复盘页面。

如果某次不想存入历史：

```powershell
python -m football_lottery_agent daily --no-history
```

也可以指定历史目录：

```powershell
python -m football_lottery_agent daily --history-dir reports\history
```

## 项目结构

```text
football-lottery-agent/
  data/                  示例输入
  football_lottery_agent/ 核心代码
  reports/               输出报告目录
  tests/                 单元测试
```

## 下一步可接入

- 真实赛程来源
- 欧赔 / 亚盘 / 赔率变化采集
- 伤停新闻和官方阵容
- 大模型新闻摘要
- 历史复盘数据库
- Web 页面或微信/飞书推送
