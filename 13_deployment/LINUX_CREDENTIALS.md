# Linux systemd 数据库密钥凭据（Synthetic Demo）

## 范围与平台选择

此切片仅为合成数据 school_tenant 提供密钥读取适配，不授权真实学生数据、生产部署、数据库迁移或写入。
KeyProvider 的 active_version / get_key / versions 及 Fernet 密文契约保持不变。

- Windows：继续使用现有 WindowsDpapiKeyProvider 和显式 DATABASE_KEY_FILE；DPAPI 实现未改。
- Linux POSIX：使用 LinuxSystemdCredentialKeyProvider，只读 systemd 注入的凭据。
- 其他系统：school_tenant 拒绝启动。Linux 凭据缺失、无效或无法读取时也拒绝启动。
- legacy_demo 保留现有开发 provider；school_tenant 的错误不会回退到它，也不回退到内存临时密钥、普通 .env、明文配置文件或云端。

## 运行时输入与校验

CREDENTIALS_DIRECTORY 必须由服务管理器显式提供。应用不猜测目录，不展开 ~，不搜索凭据库。
DATABASE_KEY_FILE 在 Linux 分支中表示单个凭据名称，省略时为 database-keys.json。
名称限 1–128 个 ASCII 字符，首字符为字母或数字，其余仅字母、数字、点、下划线、连字符，且不能包含 ..。
绝对文件路径、子目录、斜杠、反斜杠和空值均被拒绝；这与 Windows 的文件路径语义不同。
CREDENTIALS_DIRECTORY 和 DATABASE_KEY_FILE 只携带位置或名称，不承载密钥值。

读取器执行以下检查：

- 必须同时满足 os.name == posix 和 sys.platform == linux。
- 目录为绝对路径，不能为根目录或包含 ..；从根目录逐层使用目录描述符、O_DIRECTORY、O_NOFOLLOW、O_CLOEXEC 打开。
  目录及全部祖先均不能为符号链接；凭据按严格 basename 相对于该目录描述符打开，因此被限制在该目录内，不通过 resolve 跟随链接。
- 最终凭据目录必须由当前有效 UID 所有，权限只能为 0500 或 0700。
- 文件必须由同一有效 UID 所有，权限只能为 0400 或 0600，必须为普通文件，nlink 必须为 1，大小为 1–65536 字节。
  不接受其他 UID 的 root-owned 特例；root 所有权仅在进程自身有效 UID 为 0 时匹配。服务应使用独立非 root 用户。
- 文件打开包含 O_NOFOLLOW、O_CLOEXEC 和 O_NONBLOCK；FIFO 等非普通文件被拒绝。
  读取最多 65537 字节，核对读取长度及前后文件元数据，发现权限、属主、链接数、大小或修改时间变化时拒绝；读取期间目录权限或属主变化也被拒绝。
- UTF-8 JSON 顶层必须恰有 active_version 与 keys。active_version 必须为非空字符串且存在于非空 keys 中。
  每个版本名必须为非空字符串，每个值必须为规范 URL-safe Base64 编码的 32 字节 Fernet 密钥。
  拒绝任意层级重复 JSON 字段、额外顶层字段、错误类型、不可用活动版本及任何无效旧版本密钥。

provider 只读取和关闭描述符，不创建、chmod、修复或覆写文件，不在导入时生成密钥。
读取后的密钥保留在服务进程内存中供现有 Fernet 实现使用。provider 初始化时只读取一次，不监控更新或自动生成密钥；凭据更新需由运维流程重启服务。
所有公开读取失败均为 EncryptionKeyUnavailable，消息固定为：

> Linux systemd encryption credential is unavailable or invalid

消息不含路径、版本、密钥或底层异常，且抑制异常链展示。不得通过调试器、局部变量转储或 traceback 的 show-locals 模式导出密钥。

## 注入方式与静态加密

运维人员须先在独立授权的流程中制作 JSON 密钥包，并使用 systemd-creds encrypt 生成加密凭据。
JSON 形状如下，括号内文字仅为占位说明，不能作为有效密钥使用：

~~~json
{"active_version":"v1","keys":{"v1":"<规范的 Fernet 密钥，仅通过安全输入流提供>"}}
~~~

以下为服务配置片段，需与已有启动命令和合成环境配置合并审核；本文件不安装或启动服务：

~~~ini
[Service]
User=psynova-synthetic
Group=psynova-synthetic
UMask=0077
LoadCredentialEncrypted=database-keys.json:/etc/credstore.encrypted/psynova-database-keys.cred
Environment=DATABASE_KEY_FILE=database-keys.json
NoNewPrivileges=yes
LimitCORE=0
~~~

不要手工设置 CREDENTIALS_DIRECTORY；systemd 在激活服务时提供它。
创建加密凭据时应显式指定 --name=database-keys.json，使内嵌凭据名与 LoadCredentialEncrypted 的 ID 一致。
密钥内容应从受控工具经匿名管道或文件描述符送入 systemd-creds 的标准输入；不提供包含真实密钥的命令行示例。
不要把密钥放进 shell 历史、参数、Environment/EnvironmentFile、.env、SetCredential 明文、日志、仓库或打包资源。
本切片未实现运维侧的密钥生成、加密、服务安装、自动轮换或备份工具。

systemd 的 LoadCredentialEncrypted 在服务启动前解密并认证凭据，运行时以明文文件提供，通常位于 /run/credentials/ 下；
服务进程从 CREDENTIALS_DIRECTORY 取路径。可用时，systemd 使用不可交换的内存文件系统并限制服务用户访问。
因此静态加密保护的是持久化加密凭据，并不意味着 /run 中仍是密文。
参见 [systemd.exec 凭据说明](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#Credentials)。

systemd-creds 的加密可基于主机密钥、TPM2 或两者组合，具体保障取决于制作时选择、主机能力和本机 systemd 版本。
主机密钥模式依赖 /var/lib/systemd/credential.secret 的保密；TPM2 绑定可能限制换机恢复。
应明确选定模式并核实目标主机支持，不能把自动选择视为 TPM2 保证。
参见 [systemd-creds 加密机制](https://www.freedesktop.org/software/systemd/man/latest/systemd-creds.html)。

## 威胁模型与操作边界

可信边界包括 systemd 管理器、内核、服务单元、服务专用 UID、凭据制作流程及其静态加密根密钥。
攻击者可尝试修改运行参数、替换凭据路径、加入链接、放宽权限或提供损坏内容；本读取器对这些不合规输入拒绝启动。
根目录及祖先的部署权限、挂载命名空间和服务配置由系统管理员保护。

本读取器不能仅从目录名称、权限或 JSON 内容证明凭据来自 LoadCredentialEncrypted。
同一服务 UID 或 root 若能操控进程环境和私有文件系统，就能构造满足检查的替代目录；这一来源保证由部署配置和访问控制承担。
禁止用手工设置环境变量指向普通磁盘 JSON 来冒充 systemd 加密凭据。
运行时目录须由 systemd 管理，避免给同一 UID 复用其他不可信服务；应用代码、虚拟环境与单元文件不应允许该服务用户修改。
不要为消除启动错误而 chmod 放宽凭据或改用明文 LoadCredential。

服务账户应独立、非交互且非 root，仅赋予所需数据库权限，并按已有部署要求配置命名空间与文件系统访问控制。
root、同 UID 的恶意进程、被攻陷的应用、内存转储和调试能力仍可能读取解密材料。
LimitCORE=0 仅减少常规核心转储风险，不是内存保密保证；/run 的快照、转储、调试日志也必须排除或受控。
本方案不宣称与 Windows 当前用户 DPAPI 的安全属性等价。

备份只收录授权保存的加密凭据及必要非敏感版本信息，不备份 /run 明文目录。
主机密钥模式需要为加密根密钥建立单独受控的恢复方案，避免和加密凭据放在同一未保护备份中。
TPM2 模式须验证换机、系统更新与灾难恢复条件；不能假定复制密文即可恢复。
数据库备份能否恢复还取决于历史 Fernet 版本的可用性：保留仍被密文引用的版本，先验证受控恢复，再考虑退役旧密钥。
这些操作需要独立授权，本次未执行。

## 定向验证

在已有且版本兼容的独立 Python 3.12 环境中，设置 PYTHONPATH 包含 11_database 和 09_backend/src，执行：

~~~text
python -B -m pytest -q -p no:cacheprovider --tb=short 11_database/tests/test_crypto.py 11_database/tests/test_systemd_credentials.py 09_backend/tests/test_database_adapter_startup.py 09_backend/tests/test_database_credential_selection.py 09_backend/tests/test_backend_optional_database_imports.py
~~~

测试不创建数据库连接，不调用迁移或部署。密钥和 payload 只使用测试临时生成的合成材料。
跨平台描述符文件系统 double 覆盖安全拒绝、格式检查、加解密与读取后的描述符关闭；它不证明 Linux 内核的实际访问控制。
native Linux 测试使用真实临时目录验证加解密、权限拒绝、硬链接和符号链接，并在其他系统上明确跳过。
后端测试覆盖 Linux/Windows 选择、其他 OS 拒绝、原 provider 失败不回退、缺少真实环境变量时拒绝以及延迟导入行为。
Windows 现有测试仍验证原 DPAPI provider；运行环境若无法提供当前用户 DPAPI 能力，须记录失败并与未改的 HEAD 基线比较。

真实 Linux + systemd LoadCredentialEncrypted 服务注入、原生 UID 隔离、挂载行为及主机/TPM2 恢复仍需在获准的隔离合成环境验证。
定向测试通过不代表四角色学校平台、生产或测量学已验收。
