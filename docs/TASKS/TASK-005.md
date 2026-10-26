# TASK-005：创建 cooldatasim Git 仓库与安全交接包

## 状态

源代码已提交任务分支并创建PR，Git交接工具已验证；等待人工Review/合并，GitHub远端强制保护受账号方案限制而未启用。该未完成项明确保留，整体业务项目也未标记完成。

## 背景

现有本机项目尚无提交和远端，工作文件包含已实现模块、历史验收记录及未完成项。运行环境、密钥、模型权重、数据库和镜像必须与Git源代码分开。

## 验收标准

- BOOMUN/cooldatasim 为新建私有仓库；完整项目在ai/TASK-005分支，以PR等待人工Review，不直接推main、不自动合并。
- README、AGENTS、ARCHITECTURE、RUNBOOK、任务卡、ADR、AI提示词与真实可执行命令齐全。
- 重新运行本地check，记录实际结果；远端CI和分支保护分别核实，不将不支持或失败项标成完成。
- 所有候选/暂存/历史文件通过敏感文件名、凭证格式及本机实际凭证匹配检查。
- 不包含.env、私钥、客户/员工资料、数据库、outputs、参考克隆、node_modules、.venv或Docker镜像。
- 交付Git bundle和源代码ZIP，包含提交基准、SHA-256和离线恢复说明；离线克隆验证成功。
- 功能未完成项继续明确保留，不将仓库交接称为生产系统验收。

## 允许修改

- `README.md`、`AGENTS.md`、`.gitignore`、`.gitattributes`、`.github/workflows/ci.yml`、`.github/pull_request_template.md`
- `.githooks/pre-push`、`scripts/pre_push.py`、`tests/test_pre_push.py`：本地拒绝主分支直推和非快进改写，不能代替GitHub保护规则。
- `docs/HANDOFF.md`、`docs/RUNBOOK.md`、`docs/ARCHITECTURE.md`、`docs/AI_PROMPTS.md`
- `docs/TASKS/README.md`、`docs/TASKS/TASK-005.md`、`docs/DECISIONS/README.md`
- `scripts/package_git.py`、`scripts/project.py`、`tests/test_package_git.py`、`tests/test_repository.py`
- 若全新CI环境发现实际可重复的兼容性问题，允许最小修复对应测试/构建配置并记录，禁止顺带业务重构。
- `frontend/src/api.ts`：首次暂存diff检查发现末尾多余空行，仅规范文件结尾，不改变功能。

首次源代码快照可包含本机已开发的全部Git可见项目文件；不改写已有业务内容。运行产物仅写入被忽略的outputs/git-handoff。

## 禁止修改

真实.env/SSH凭证、运行数据库、模型电脑、AWS/WhatsApp服务、其他项目和参考克隆；禁止强推、修改已有仓库、自动合并或公开仓库。

## 操作权限

本次明确授权新仓库创建、必要本地Git身份设置、初始项目提交、推送任务分支、创建PR、启用本仓库CI/主分支保护及生成离线Git文件。main仅由GitHub初始化README建立，AI应用改动全部通过任务分支和PR。

## 执行计划

1. 核对Git状态、GitHub身份、仓库名和候选文件。
2. 补齐当前交接状态、下一任务入口和安全打包工具。
3. 完成凭证审计和本地验证后，建立新仓库、提交任务分支和PR。
4. 核查远端CI与分支保护，生成并验证bundle/ZIP，记录真实结果。

## 验证命令

```sh
python scripts/project.py check
python scripts/package_git.py audit
git diff --cached --check
python scripts/package_git.py export
```

远端检查使用gh查询PR、Actions和分支保护。导出命令必须在源代码提交后运行。

## 验证结果

截至2026-10-26的本地准备结果：

- 已创建私有仓库 https://github.com/BOOMUN/cooldatasim ，main由GitHub初始化README。
- 已设置本仓库专用GitHub noreply提交身份，保留既有工作文件。
- 交接脚本6项测试通过，覆盖离线恢复、脏工作区拒绝、已知凭证、不回显密钥、暂存密钥及历史已删除密钥检查。
- 本地pre-push保护及安装上下文8项测试通过；拒绝main/master直推/删除、非快进改写和已有标签改写，保留用户自定义hook；ZIP安装不修改父仓库配置。
- GitHub分支保护API拒绝私有仓库启用，返回“Upgrade to GitHub Pro or make this repository public to enable this feature.”。仓库保持私有，远端强制保护未启用；本地hook不能代替它。
- 初始提交前完整`python scripts/project.py check`通过：55项治理/部署/Git交接测试、122项后端及独立模型接口测试、17项前端测试，类型检查和正式构建通过。随后补充2项ZIP/自定义hook上下文回归，当前治理测试为57项；GitHub官方Actions固定完整提交SHA，应用依赖没有升级。
- 已提交并推送ai/TASK-005，初始源代码提交4f9a44c33da3fa0e8c3f9bf6da85325c5bf39b13；main只保留GitHub初始化内容，未直接推送应用代码。
- 已创建PR https://github.com/BOOMUN/cooldatasim/pull/1 ，保持OPEN供人工Review，未自动合并。
- 初始PR远端CI在Ubuntu及Windows均成功： https://github.com/BOOMUN/cooldatasim/actions/runs/40260156129 。首次push触发的重复运行被PR并发规则取消，不计为验证通过。工作流随后调整为PR、main合并后push及手动触发；最终提交结果以PR当前检查为准。
- 已生成并验证完整Git bundle及源代码ZIP；离线克隆提交一致，入口文件齐全，无真实.env。最终包与提交、SHA-256绑定，位置见交付消息和包内MANIFEST.json。
- 所有代码/暂存/历史文件通过凭证审计。修正frontend/src/api.ts末尾多余空行，未改业务逻辑。

此次没有重新操作数据库、模型电脑、AWS或WhatsApp；历史业务验收日期保持原样。尚未完成的是远端强制保护和PR人工Review/合并，未把这些项目标为完成。

## 人工验收与风险

PR由用户审核后合并。私有仓库的分支保护取决于GitHub账号方案，若API拒绝须明确记录；不自动改为公开仓库。没有运行配置和数据的新克隆不能直接还原现有运行环境，应依RUNBOOK重新初始化。
