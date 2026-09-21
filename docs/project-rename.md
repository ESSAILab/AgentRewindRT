# AgentRewindRT 项目名称与仓库地址配置

项目统一使用 `AgentRewindRT`。GitLab 的项目显示名称与仓库路径需要分别修改；本地代码中的名称修正不会自动更新 GitLab 设置。

## 1. 修改 GitLab 显示名称

在现有项目中进入 **Settings → General**，将 **Project name** 修改为 `AgentRewindRT`，保存更改。需要项目 Maintainer、Owner 或管理员权限。

## 2. 修改仓库路径

在 **Settings → General → Advanced** 中找到 **Change path**，将项目路径修改为 `AgentRewindRT` 并确认。旧版 GitLab 的对应区域可能标为 **Rename repository**。命名空间保持不变。

如果项目位于 `wangbo` 命名空间，修改后路径应为 `wangbo/AgentRewindRT`。请从修改后的项目页面复制实际克隆地址，以页面显示的大小写、协议和端口为准。

上述步骤依据 [GitLab 项目管理文档](https://docs.gitlab.com/user/project/working_with_projects/#rename-a-repository)。

## 3. 更新各本地副本的远程地址

完成 GitLab 路径修改后，在每个已有仓库副本中执行以下命令，将示例地址替换为实际的新克隆地址：

```bash
git remote set-url origin https://gitlab.example.com/wangbo/AgentRewindRT.git
git remote -v
git ls-remote origin refs/heads/main
```

最后一条命令用于验证新地址及访问权限。部署服务器、开发机器与其他已有克隆副本需要分别更新；本地目录名不必与远程项目名一致。`upstream` 若指向独立的上游项目，无需因本项目更名而修改。

如另行配置过推送地址，先通过 `git config --get-all remote.origin.pushurl` 检查，再将其同步修改为新的推送地址。CI/CD、Webhook 或外部部署脚本若保存了旧仓库 URL，也应同步更新。

## 4. 更新已部署页面

名称修正提交并同步到部署服务器后，在原项目目录中保留部署环境变量，重新构建 Web UI：

```bash
./scripts/agentguard-compose build web-ui
./scripts/agentguard-compose up -d --force-recreate web-ui
```

刷新浏览器，确认页面标题、页内项目名称与 Web UI API 文档标题均为 `AgentRewindRT`。浏览器仍显示旧名称时，执行强制刷新。

此次更名仅修正项目名称。已有 `AGENTGUARD_*`、`DEEPXDR_*` 配置项、Compose 服务与数据卷名称仍按当前代码使用；不要因项目更名而删除数据卷或移动工作区和快照目录。
