# 测试预期、实际结果、失败与限制

## 当前结论

Python3.11.9 / Windows环境，71项自动化测试通过，22/22个离线场景通过。真实DeepSeek未配置密钥、未运行。指标描述工程守卫及确定性Mock路径，不可换算为真实模型成功率或用户创作质量。

可复现命令：

```powershell
python scripts/test.py
python scripts/evaluate.py --model mock
node --check src/video_script/web_assets/app.js
```

[测试实际日志](../examples/test-results.txt)、[场景汇总](../examples/mock/summary.json)、[构建检查](../examples/build-check.txt)为执行产物；tests/test_transport.py使用HTTP响应桩，未访问真实模型。

## 必验覆盖及反例

下面链接指向每个场景的实际输入、数据、输出和Trace所在目录；各目录output.json含完整实际状态，trace.json含动作参数、返回摘要、实际返回、后续动作和短依据。

| 要求 | 场景/材料 | 预期 | 实际 |
| --- | --- | --- | --- |
| 正常生成 | [normal](../examples/mock/normal/) | 完整脚本且≤45秒 | completed；38秒；4镜；P01引用 |
| 缺关键输入 | [missing_information](../examples/mock/missing_information/) | 请求目标时长 | needs_information，具体缺target_seconds |
| 缺受众/风格 | [missing_audience](../examples/mock/missing_audience/) / [missing_style](../examples/mock/missing_style/) | 不默认填值 | 请求各自缺失字段 |
| 无素材 | [no_materials](../examples/mock/no_materials/) | 补检索后仍不足，停止编写 | needs_materials，2轮检索，final_script为空 |
| 资料外主题 | [unrelated_theme](../examples/mock/unrelated_theme/) | 不凭空补产品能力 | needs_materials |
| 工具失败 | [tool_failure](../examples/mock/tool_failure/) | 明确估时失败，保留已成功步骤 | failed；已读P01，已生成1稿，未交付通过脚本 |
| 其他工具失败 | [search_failure](../examples/mock/search_failure/) / [read_failure](../examples/mock/read_failure/) / [rules_failure](../examples/mock/rules_failure/) | 不将失败作通过 | 均failed，保留相应错误 |
| 超时修订 | [duration_revision](../examples/mock/duration_revision/) | 38→28秒，重新规则检查 | completed；2版，9步 |
| 无法满足 | [impossible_duration](../examples/mock/impossible_duration/) | 尝试精简和去停顿仍失败 | 38→28→8→5秒；constraints_unmet，缺口3秒 |
| 查询改写 | [query_rewrite](../examples/mock/query_rewrite/) | 首查为空，换术语补查 | “画面配字”→“字幕”；读取P01后生成 |
| 品牌修订 | [rule_revision](../examples/mock/rule_revision/) | 去掉新增禁词并重检 | 规则False→True，38→28秒 |
| 无依据主张 | [unsupported_claim](../examples/mock/unsupported_claim/) | 拦截带ID的80%主张 | 事实不符+禁词风险；safe_copy后28秒，不含80% |
| 规则无法满足 | [rule_unmet](../examples/mock/rule_unmet/) | 不绕过禁词 | 最简仍风险，constraints_unmet |
| 极短目标 | [minimal_script](../examples/mock/minimal_script/) / [trim_pauses](../examples/mock/trim_pauses/) | 随10/5秒限制调整 | 8/5秒通过，后者确实去停顿 |
| 替换语速 | [slow_speech](../examples/mock/slow_speech/) | 按新规则重算并再次精简 | 49→35→13秒，最终3镜 |
| 替换事实 | [source_changed](../examples/mock/source_changed/) | 不再输出支持字幕 | 支持片段裁剪，39→29秒，版本与指纹同步变化 |
| 不支持平台 | [unsupported_platform](../examples/mock/unsupported_platform/) | 请求改选，不默改 | needs_information |
| 达到步数上限 | [step_limit](../examples/mock/step_limit/) | incomplete并保留部分状态 | 3步后已有P01原文，无通过脚本 |

## 分镜与来源逐一核对

[duration_revision/output.json](../examples/mock/duration_revision/output.json)中精简版S01=7、S02=8、S03=5、S04=8秒，合计28。S03旁白及字幕“支持字幕”引用P01:F01，素材原文“产品支持字幕。”，日期2026-01-01，原文指纹以692cd1d2ac2b5019开头。其余镜头是已列明中性文案，不冒充产品事实。

测试核对逐镜合计、每条引用在原文、引用ID确属对应镜头，以及更换事实后的文案变化；不是只检查状态字段或预期字符串。

## 浏览器实际验证

见 [浏览器检查记录](../examples/web/verification.md)、[原始运行](../examples/web/browser-run.json)、[拒绝的编辑](../examples/web/edit-rejected.json)、[通过的编辑](../examples/web/edit-approved.json)、[实际下载JSON](../examples/web/downloaded-script.json)。截图只是辅助，不能代替代码和Trace。

实际点击后获得38→28；新增“效率提升80%”立即撤销批准，服务端拒绝；恢复后首镜停留+2秒，服务端重新算30秒并成功下载。人工编辑输出manual_validation，与原始Agent结果分开。HTTP测试另覆盖素材变化后拒绝旧运行校验、越过目标覆盖、时长31秒拒绝、旧检查失效和无依据标题/画面/字幕。

## 失败、修正及已知限制

- 主动注入的素材读取、估时、规则工具失败是必验场景，不称为成功生成；实际错误和已完成内容保留。
- 审查模型适配时发现原复用传输层未覆盖HTTP协议异常，已加入HTTPException处理并用BadStatusLine桩验证显式未完成、无敏感响应泄漏。
- 首稿无依据80%是测试专用生成故障注入，文件保留错误草稿与真实规则检查，不把它当真实模型生成证据。
- 当前无真实模型采样、调用成本或延迟数据；后续须配置密钥至少跑正常、超时、空检索/工具失败路径，再记录实际模型名、动作和结果。调用可能产生费用，应由配置密钥的使用者自行执行并核对。
- 词法检索与有限术语扩展不能覆盖开放域表达；三种模板不保证丰富创意，风格/受众只保留元数据。
- 事实核验依赖人工整理的合成事实卡，仅查原文逐字对应，不证明原文事实在现实成立，也不是通用语义蕴含。新自由文案可能被误拒。
- 估时非TTS/成片测量；字符数、阅读速度、停顿是近似假设。跨语言和实际剪辑节奏需要额外评估。
- 未验证生产负载、认证、权限、真实素材授权、云部署；CI已配置，CI远端执行状态不代替本地已记录验证结果。
