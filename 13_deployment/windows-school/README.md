# PsyNova 2.0 Windows 空库预览

适合学校信息管理员在 Windows x64 上检查安装及账号、班级业务流程。安装器下载 Python、Node.js、PowerShell 和 MySQL 到当前用户的安装目录。业务库只建立一个空学校和一个管理员，公网注册入口关闭。

## 安装与登录

1. 下载该预览发布中的 `PsyNova-School-Windows-x64-Preview.exe`，用对应的 `SHA256SUMS.txt` 核对文件。
2. 在可以访问官方软件源的 Windows 电脑上双击安装程序。程序创建独立 MySQL 实例，启动本机服务并打开登录页。MySQL 依赖 [Microsoft Visual C++ 运行库](https://dev.mysql.com/doc/refman/8.4/en/windows-installation.html)，检查学校电脑上已安装该组件。
3. 用安装时的 Windows 用户在 PowerShell 执行下面的命令，查看初始管理员账号和密码。
4. 打开 [本机登录](http://127.0.0.1:4178/login)，登录后进入“账号管理”。使用合成名单测试导入与分班。

```powershell
$root = Join-Path $env:LOCALAPPDATA 'PsyNova/school-v2-preview'
$app = Join-Path $root 'app'
$workspace = Join-Path $root '.StudentMentalHealthAI-school-install-20261123-v2-preview'
& "$app/09_backend/.venv/Scripts/python.exe" "$app/13_deployment/school_empty_bootstrap.py" --workspace $workspace --show-initial-admin
```

安装和数据位于 `%LOCALAPPDATA%\PsyNova\school-v2-preview`。重复运行安装程序可启动原工作区。管理员凭据和数据库密钥由 Windows 加密，保留安装时的 Windows 用户身份。

## 适用范围

当前预览通过本机地址访问，使用内置合成 CAT 样例开展安装验收。EXE 未加代码签名，下载后请核对 SHA256。可以用 `--prepare-qwen` 下载并校验 Qwen 2.5 7B 和 Ollama，需额外约 6.2 GB 下载流量及解压空间。该选项准备模型文件。校内 HTTPS、本地 Qwen 推理、资料检索和安全服务的完整联调属于正式安装版的验收范围。

## 从源码构建

在学校版分支检出对应发布提交。Windows 自带的 .NET Framework C# 编译器会将源码和安装引导程序打包到一个 EXE。

```powershell
pwsh -File 13_deployment/windows-school/Build-Setup.ps1 -OutputDirectory ./out
```
