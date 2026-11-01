# 启动参数同步与回滚

只在目标黑苹果上执行；在另一台真 Mac 上执行会改到那台 Mac。EFI 路径也必须指向实际用于启动的那一份。

先读取当前生效参数、NVRAM 值，以及已经修改好的配置：

```bash
sysctl kern.bootargs
nvram boot-args
/usr/libexec/PlistBuddy -c 'Print :NVRAM:Add:7C436110-AB2A-4BBB-A880-FE41995C9F82:boot-args' /Volumes/1401/EFI/OC/config.plist
```

卷名不一定叫 1401。确认磁盘后替换为自己的路径，保存旧的 boot-args。下面工具使用结构化参数写 NVRAM，不执行参数中的 shell 内容，默认只预览：

```bash
python3 tools/sync_boot_args.py /path/to/EFI
sudo python3 tools/sync_boot_args.py /path/to/EFI --apply
```

它仅限 macOS，要求用户显式选择 `--apply`、管理员权限，并要求配置与当前 NVRAM 的差异只涉及本仓库使用的 `nvrmacpibl=1`、`alcid=<数字>`、`keepsyms=1`。如果其他参数也不同，停止并人工检查是否选错 EFI。

原值记录在 EFI 同级 `yaoshi-backups/` 的私有文本文件中。该备份不要公开上传。写入后需要重新启动才能改变 `sysctl kern.bootargs`。

如果无法启动：

1. 对于 NVIDIA 背光初始化问题，优先尝试 OpenCore 中 1401 的 **Start once without NVIDIA driver** 入口。
2. 如果不能进入系统，把启动盘接到另一台电脑，恢复 `--apply` 前的 EFI。
3. NVRAM 值需要另外恢复。可在目标机器恢复环境的终端中查看 `nvram boot-args`，按保存的原值设置。不要把目标机器的原参数写到救援用真 Mac 上。
4. 不建议为单个参数盲目 Reset NVRAM：它会影响其他设置，还可能触发 Windows BitLocker 恢复要求。本次修复没有依赖 Reset NVRAM。

本仓库不提供清空 NVRAM、删除磁盘或重装系统的自动化命令。
