# 第4题：短视频脚本 Agent

基于合成产品事实生成可编辑分镜，实际估算时长并检查引用和品牌规则；超时或规则不通过时修订、重检，无法满足时保留草稿并说明缺口。

**当前已验证离线Mock：71项测试、22/22个场景通过。DeepSeek原生tool_calls已接入，但未配置密钥、未执行真实模型验收。Mock是确定性测试替身，不证明真实模型决策或创作质量。**

模型选择检索、读取、结构、修订和终止动作；文案采用受限模板，产品事实逐字绑定素材。这不是开放式营销文案生成器，不声称通用语义核验或视频渲染能力。

## 评审入口（约5分钟）

Python3.11+；CLI、离线测试和本机界面无第三方运行依赖，无需密钥。Node只用于可选前端语法检查。

```powershell
git clone https://github.com/yuhang-824/short-video-script-agent.git
cd short-video-script-agent
python scripts/test.py
python scripts/evaluate.py --model mock
python scripts/ask.py --input examples/mock/duration_revision/input.json --output runtime/demo.json
python scripts/web.py
```

打开 <http://127.0.0.1:8767>。默认“超时修订”点击生成后，实际估时**38→28秒**；能查看4个分镜、原文、工具参数和修订记录。

验证编辑：把第三镜旁白改为“支持字幕，效率提升80%”，旧通过状态立即失效，点击“校验我的修改”会被拒绝。恢复原稿，把首镜额外停留从4改为6，重新校验为30秒并允许下载。原始Agent运行与人工编辑校验分别存档。

还可选缺信息、无素材、工具失败、规则修订、替换事实、2秒无法满足等场景。服务仅绑定127.0.0.1，退出用Ctrl+C；换端口：`python scripts/web.py --port 8777`。

## 输入、输出与执行边界

```json
{"request_id":"my-script","theme":"字幕创作","audience":"短视频创作者","platform":"抖音","target_seconds":30,"style":"简洁清晰"}
```

五项创作信息缺失时保留为null并请求补充，不默认填写。时长为1–180的整数，表示**预计总时长上限**。支持平台见data/catalog.json。

输出含status、gaps、全部revisions、editable_draft、实际duration_history、rule_history、fact_inventory和trace。只有本版时长与规则均通过才有final_script，含标题、分镜、旁白、字幕、逐镜时长、总时长、来源ID、原文、日期和内容指纹。

状态：completed / needs_information / needs_materials / failed / constraints_unmet / incomplete。CLI完成退出0，业务未完成退出2，输入/配置错误退出1。预计时长不等于成片时长。

默认32步，可设1–200。达到上限返回incomplete及step_limit_reached，保留已有事实/草稿，不交付通过脚本。

## 实际证据与复现

| 验收内容 | 实际记录 |
| --- | --- |
| 正常生成：45秒上限，38秒通过 | [normal](examples/mock/normal/output.json) |
| 缺目标时长，请求补充 | [missing_information](examples/mock/missing_information/output.json) |
| 无素材：关键词及补检索后请求资料 | [no_materials](examples/mock/no_materials/trace.json) |
| 估时失败，保留草稿且不虚报完成 | [tool_failure](examples/mock/tool_failure/output.json) |
| 超时修订：38→28秒 | [duration_revision](examples/mock/duration_revision/trace.json) |
| 2秒无法满足：38→28→8→5，缺口3秒 | [impossible_duration](examples/mock/impossible_duration/output.json) |
| 品牌风险修订并重新检查 | [rule_revision](examples/mock/rule_revision/trace.json) |
| 替换产品事实后文案、指纹及时长变化 | [source_changed](examples/mock/source_changed/output.json) |

各场景均有input.json、data.json、output.json、trace.json；生成过草稿的另有editable-script.json。文件来自实际执行，不是手写决策日志。

[测试日志](examples/test-results.txt) · [22场景汇总](examples/mock/summary.json) · [浏览器验证](examples/web/verification.md) · [评估与限制](docs/03-evaluation.md)

单独复现故障场景必须同时使用其资料快照，不能只用输入配正常资料：

```powershell
python scripts/ask.py --input examples/mock/tool_failure/input.json --data examples/mock/tool_failure/data.json --output runtime/failure.json
python scripts/ask.py --input examples/mock/duration_revision/input.json --max-steps 3 --output runtime/limited.json
```

上述命令预期退出2，分别表示工具失败和步数耗尽。

## 草稿编辑校验

复制editable-script.json后编辑其标题、旁白、字幕、停留时间或分镜内容，然后运行：

```powershell
python scripts/ask.py --input examples/mock/duration_revision/input.json --check-script examples/mock/duration_revision/editable-script.json --output runtime/edit-check.json
```

这是manual_validation，独立于模型循环。自动放行中性文案白名单、固定文字卡画面及素材事实原文；新的自由文案保守拒绝并标明待审查。必须传草稿JSON，不能直接传带批准字段的final_script或浏览器下载包装。CLI校验读取当前全部有效事实；网页仅使用对应运行实际已读事实，并禁止覆盖原始目标。资料变更后网页要求先重新生成。

## 真实模型入口（尚未实测）

将.env.example复制为本地.env填写密钥，不提交.env。默认MODEL_NAME=deepseek-flash、MODEL_BASE_URL=https://api.deepseek.com，可改为账户可用模型。原生HTTP，无框架或SDK依赖。

```powershell
python scripts/ask.py --model deepseek --input examples/mock/duration_revision/input.json --output runtime/real/duration-revision.json
python scripts/evaluate.py --model deepseek --output-dir runtime/real-evaluation
python scripts/web.py --model deepseek --port 8777
```

真实模式每轮接收一个工具调用，真实返回进入下一轮上下文，不使用Mock动作。API错误/缺密钥不自动退回Mock。关闭thinking，不保存内部思维，只记录短动作依据。真实模型可能选更短首稿，真实评估不要求固定38→28路径；完成结果仍受相同服务端检查约束。

接口核对于2026-10-31：[DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)、[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)。文档核对与HTTP桩测试不是模型验收。

## 交付目录

```text
src/video_script/   模型适配、有界循环、工具、时长/事实检查、本机UI
tests/             业务反例、HTTP接口、模型传输桩测试
data/              合成产品事实和品牌规则
examples/          输入/实际输出/Trace/测试日志/浏览器证据
docs/              需求、方案、评估、AI使用、复盘
scripts/           CLI、界面、测试、评估、提交文本生成入口
.env.example       真实模型可选配置；离线无需配置
```

可选安装：`python -m pip install .`，之后使用video-script、video-script-web；离线直接用scripts无需安装。[工程验证日志](examples/build-check.txt)记录wheel和网页资源包含检查。

[需求](docs/01-requirements.md) · [设计](docs/02-solution.md) · [AI使用](docs/04-ai-usage.md) · [复盘与用时](docs/05-retrospective.md)。全部为合成资料，未接真实产品、发布、渲染或外部业务系统。
