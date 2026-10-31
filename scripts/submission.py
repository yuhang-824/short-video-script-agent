"""Create submission text from actual clean HEAD and checked-in evidence."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "runtime/submission.txt")
    args = parser.parse_args()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
        print("Commit all changes before generating final submission text.")
        return 2
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    summary = json.loads((ROOT / "examples/mock/summary.json").read_text(encoding="utf-8"))
    log = (ROOT / "examples/test-results.txt").read_text(encoding="utf-8")
    count = re.search(r"Ran (\d+) tests", log).group(1)
    text = f"""选择题号：第4题——短视频脚本 Agent

GitHub仓库：
https://github.com/yuhang-824/short-video-script-agent

最终commit SHA：
{sha}

一、实现内容
使用Python3.11标准库实现CLI和本机可编辑验证页面，提供素材检索、原文读取、受限分镜生成、时长估算、事实及品牌检查、修订、补充请求和停止工具。
模型接口采用DeepSeek原生tool_calls，实现选择动作、执行工具、观察实际返回、再次决策的有界循环；另提供明确标记的离线Mock。默认32步，耗尽时返回未完成状态并保留已有结果。
脚本含标题、分镜、旁白、字幕、逐镜与总预计时长、素材ID、原文、版本日期、内容指纹、风险及任务状态。只有当前版本时长和规则均通过才交付通过脚本。

二、复现步骤
Python3.11及以上；离线运行和测试无需第三方运行依赖或密钥。
git clone https://github.com/yuhang-824/short-video-script-agent.git
cd short-video-script-agent
python scripts/test.py
python scripts/evaluate.py --model mock
python scripts/ask.py --input examples/mock/duration_revision/input.json --output runtime/demo.json

启动界面：python scripts/web.py
浏览器访问：http://127.0.0.1:8767

三、实际验证结果
{count}项自动化测试通过，{summary['passed']}/{summary['total']}个离线场景通过，覆盖正常生成、缺关键信息、无素材、工具失败、超时修订或明确失败五项必验。
典型路径：30秒目标实际估算首稿38秒，选择压缩后重新计算28秒并检查规则；2秒目标经38→28→8→5秒后仍无法满足，明确返回缺口3秒。时间来自实际文案字符和逐镜停留计算，不是检查工具预填结果。
首检索无结果时改写“画面配字”为“字幕”补查。规则风险触发安全修订和重检。替换原文为“支持片段裁剪”后文案、来源指纹及时长随之改变，不继续输出“支持字幕”。
浏览器实测：增加无依据“效率提升80%”会撤销批准并被事实/品牌检查拒绝；恢复后首镜停留增加2秒，重新校验得到30秒并实际下载。人工编辑校验与原始Agent记录分开。
实际材料见examples/test-results.txt、examples/mock/summary.json、各场景input/data/output/trace，以及examples/web/verification.md和编辑/下载JSON。

四、模型与范围边界
当前完成离线工程验证，DeepSeek接入代码和HTTP桩测试已实现，但未配置密钥、未执行真实模型验收；Mock不证明真实模型决策或创作质量。真实接口入口及后续验证步骤见README。
脚本采用三种受限模板、固定中性文字卡和产品事实原文；新自由文案会保守拒绝并标记待审查。风格和受众目前只保留为元数据，不声称通用语义核验或丰富个性化。预计时长不等于成片时长，目标定义为上限。
未完成真实TTS/视频渲染、开放域素材检索、真实产品真实性核查、生产认证和线上部署，不接真实发布。

五、交付与AI使用披露
仓库包含README、src、tests、examples、data、五份要求文档、依赖文件、.env.example和CI配置。
本人提供题目并确定开展第四题；Codex辅助方案、仓库、代码、合成资料、测试、文档、界面、实际离线验证及提交。通用模型HTTP适配、本机HTTP外壳和基础样式复用前一题；本题分镜、事实追溯、时长修订和编辑校验独立实现。
个人代码修改和个人独立复验尚未另行记录，不把AI生成内容表述为本人独立编写。实际AI辅助会话用时见docs/05-retrospective.md。
全部业务资料为合成示例，未提交真实密钥、隐私数据或模型内部思维过程。
"""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(text)
    print("Saved to:", args.output)
    return 0


if __name__ == "__main__": raise SystemExit(main())
