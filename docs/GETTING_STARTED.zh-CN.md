# 安装与离线检查

[项目概览](../README.zh-CN.md) · [完整复现说明](reproduction.zh-CN.md)

从仓库根目录运行：

```bash
bash setup-local.sh
make verify-project
```

安装脚本创建项目自己的 `.venv`。检查入口运行项目测试、公开证据审计和文档链接检查，不调用模型 API，也不需要原始轨迹。

macOS 上双击根目录的 `运行本地验证.command`，可以查看 T01–T05 的确定性演示。这五个固定场景用于检查实现，预设动作不代表模型学会了恢复。

实现与结果从项目概览进入；逐项检查、原生 benchmark 设置及验证边界见完整复现说明。
