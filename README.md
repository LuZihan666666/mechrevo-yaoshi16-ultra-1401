# 机械革命耀世 16 Ultra · 1401 黑苹果修复方案

**Core Ultra 9 275HX + RTX 5070 Ti Laptop · Intel AX211 · Realtek ALC274**

基于 1401 / OpenCore 的同机型修复记录与补丁工具。2026-11-02 在一台实机上完成安装，机主确认亮度、内置扬声器、HDMI 外屏和触控板基本操作正常。

这里提供可复核的修改步骤和默认只预览的工具。**请先用 1401 为自己的机器生成 EFI，再按实际故障应用对应补丁。** 仓库不提供带个人 SMBIOS 的整包 EFI，也不包含 macOS 镜像或第三方驱动二进制。

## 实机与验证范围

| 项目 | 本次实机 |
|---|---|
| 机型 / 主板 | MECHREVO 耀世 16 Ultra / YAOSHI SERIES-X6AR55XY |
| BIOS | `N.1.33MRO62` |
| Display Mode | 独显直连（Discrete / dGPU），由机主确认 |
| CPU | Intel Core Ultra 9 275HX，24 核 / 24 线程 |
| 独显 | RTX 5070 Ti Laptop，`10DE:2F18`，12GB |
| 核显 | Intel Graphics，`8086:7D67`；本方案未启用 |
| 内屏 | BOE `NE160QDM-NZL`，2560×1600；验证时运行 240Hz |
| 无线 | AX211，`8086:7F70`；itlwm 2.3.0 + HeliPort |
| 板载有线 | RTL8125；本次未接网线实测 |
| 音频 | ALC274，`10EC:0274`；HDA 主控 `8086:7F50` |
| 触控板 | `UNIW0001 / PNP0C50`，`\_SB.PC02.I2C3.TPAD`；I2C3 `8086:7F4F` |
| 系统 | macOS Tahoe 26.7.2，`25G332`，x86_64 |
| 引导 / 显卡驱动 | OpenCore DEBUG 1.0.9；1401 / NullMoth NVIDIA 2.6.6 |
| 外屏 | 系统识别为 Mi Monitor；机主称应为红米 A27Q，具体版本未核实 |

即使产品名相同，BIOS、触控板、屏幕和端口布线也可能不同。下面“已验证”均指这台机器，不代表整个系列的所有批次。

| 功能 | 结果 / 限制 |
|---|---|
| macOS 启动 | APIC 修复后通过原先 `EXITBS:START` 卡点 |
| NVIDIA 加速 | 系统识别 12GB VRAM 和 Metal 3；未做完整专业软件性能认证 |
| 内屏亮度 | `nvrmacpibl=1` 后，滑块及实际明暗变化由机主确认正常 |
| 内置扬声器 | AppleALC + SimpleHDA + `alcid=28`，机主确认正常 |
| 触控板 | 修正 I²C 适配的 IOClass 后，机主反馈正常；完整手势与睡眠唤醒未逐项测试 |
| HDMI 外屏 | **保持 HDMI 连接开机**后，2560×1440、120Hz，双屏同时在线 |
| HDMI 热插拔 | 首次热插拔失败；本方案未修复该驱动行为，不保证拔插后仍正常 |
| 左侧 / 后置 Type-C 外屏 | 同一根 USB-C 线直连均未出画面；本方案未解决 |
| 雷电 / USB4 | 能看到 `8086:7EC2` 主控，但系统报告没有雷电驱动 |
| USB | 左侧 USB-A 扩展坞可用；端口映射未完成，曾出现运行时读不到启动 U 盘 |
| 3.5mm / 麦克风 | 系统已出现内置输入和输出；耳机切换及实际录音尚未验证 |
| 睡眠 / 续航 / 蓝牙 | 不在本次完成验证的范围内 |

## 使用前

1. 从 [1401](https://github.com/nullmoth/1401) 为自己的硬件生成安装 U 盘。
2. 保留能启动 Windows 和恢复原 EFI 的方式；备份自己的 EFI。补丁工具也会在 EFI 同级的 `yaoshi-backups/` 下保存完整备份，**这些备份包含个人配置，不要上传公开仓库**。
3. 在已有 Python **3.9 或更新版本**的电脑上运行工具。所有示例中的 `/path/to/EFI` 都指包含 `OC/config.plist` 的 **EFI 文件夹本身**，不指整块物理磁盘。
4. 先执行不带 `--apply` 的预览命令，确认列出的修改范围，再执行写入命令。工具不分区、不格式化、不自动重启，也不写 NVRAM。

Windows 可将示例中的 `python3` 改成已安装的 Python 命令；路径按自己的盘符填写。macOS 恢复环境未必有可用的 Python，建议在另一台电脑上修改启动盘。

## 1. 没有 VT-d 选项，卡在 EXITBS:START

本机 BIOS 中可见的 **VMX 是 VT-x，不是 VT-d**。VMD 也不是 VT-d；不要为了找 VT-d 随意更改已有 Windows 的存储控制器模式。

当时的 EFI 已有 `DisableIoMapper=true`，也删除了 DMAR；继续重复这些设置没有解决卡点。实机固件的 MADT/APIC 中没有传统 Local APIC 条目，只有 x2APIC 条目。把自己的 MADT 转成传统 LAPIC 记录后成功启动。

### 获取自己的原始 MADT

使用 OpenCore DEBUG，在 `Misc → Debug → SysReport` 开启诊断转储，进入 OpenCore 菜单一次后关机。将 U 盘接到另一台电脑，找到 `SysReport/ACPI/` 中的 APIC 表（例如 `APIC-1.aml`）。不同固件可能有多个候选表，必须先确定实际使用的那一个。

本次固件的识别特征：

- 原表 856 字节，24 个启用、24 个禁用的 type 9 记录；启用 CPU UID 为 0–23。
- 原表 SHA-256：`f44d0f8306f705b041aadcf68dba6114aceac5e9399a524df90cd0b96f3bb6e5`。
- 本次转换后 274 字节，SHA-256：`59bf29c3311e3b682835cdb889d6d037d0638a07a1567f193925acc7aeda19ce`。

这些哈希用于对照本次实机，**不要为了匹配哈希而使用别人的 ACPI 表**。工具会验证自己输入的表的签名、长度、校验和、CPU ID 和记录结构，并拒绝不在本方案范围内的记录。

```bash
python3 tools/patch_efi.py /path/to/EFI --apic /path/to/SysReport/ACPI/APIC-1.aml
python3 tools/patch_efi.py /path/to/EFI --apic /path/to/SysReport/ACPI/APIC-1.aml --apply
```

工具将：

- 保留启用 CPU 的 UID 和 APIC ID，将 type 9 转为 type 0；丢弃本机未启用的插槽记录。
- 转换 x2APIC NMI，保留 IOAPIC 和中断覆盖等其余已支持记录。
- 重算表长度和校验和，生成 `OC/ACPI/APIC-YAOSHI-legacy.aml`。
- 在 `ACPI/Delete` 中按原表签名、长度和 OEM Table ID 精确匹配，再在 `ACPI/Add` 中加载新表。**不按通配方式删除所有 APIC 表。**

转换有额外硬件假设，不是修复所有 `EXITBS` 问题的通用办法。转换后的表及配置仍应使用与自己 OpenCore 版本匹配的 `ocvalidate` 检查，再在实机验证。本次人工配置通过了 plist、表结构及文件比对检查；没有运行配套 1.0.9 的 ocvalidate，不能把本文理解为已通过该项验证。

## 2. 已进桌面，但亮度滑块不能调

确认 NVIDIA 2.6.6 已正确安装，内屏实际连接在 NVIDIA 上后，开启驱动自带的 ACPI 背光支持：

```bash
python3 tools/patch_efi.py /path/to/EFI --brightness
python3 tools/patch_efi.py /path/to/EFI --brightness --apply
```

只在现有 `boot-args` 中追加 `nvrmacpibl=1`，保留其他参数。重启后本机出现 `NVRMBacklightHandler → AppleBacklightDisplay`，日志确认硬件亮度请求成功，机主确认明暗可调。

该选项是上游的 opt-in 功能，某些机器可能在 GPU 初始化时停住。若遇到这种情况，可先从 1401 的 **Start once without NVIDIA driver** 入口启动，再移除该参数并恢复配置。

## 3. Tahoe 内置扬声器无声

本次使用：**Lilu 1.7.3 → AppleALC 1.9.8 → SimpleHDA 1.0.0**，ALC274 初始布局选择 `28`。SimpleHDA 恢复 Tahoe 缺失的 AppleHDA 支持；本方案不修改系统卷，也不安装可选 HAL 插件。

先从上游下载并校验本次使用的两个组件：

```bash
python3 tools/fetch_kexts.py --audio --output downloads
python3 tools/patch_efi.py /path/to/EFI --audio --dependencies downloads
python3 tools/patch_efi.py /path/to/EFI --audio --dependencies downloads --apply
```

工具会将组件放入 `OC/Kexts` 并添加有序的 `Kernel/Add` 条目，仅在没有已有 `alcid` 或 `layout-id` 时追加 `alcid=28`。它保留自己的 SMBIOS、APIC 修复和其他设备属性。

若已有其他 AppleHDA 恢复方案或系统卷补丁，请先人工确认没有重复加载；工具无法替你识别所有第三方方案。不同主板引脚布局可能需要不同 layout，本机可用的 `28` 不能保证适用于其他 ALC274 主板。请分别测试扬声器、耳机插拔和麦克风。

## 4. 触控板驱动未起来：IOClass 不匹配

本机日志明确出现：

```text
Couldn't alloc class "VoodooI2CPCILakeController"
```

EFI 中的 `LegionI2CArrowLake.kext` 指向旧的 Lake 控制器类，而安装的 VoodooI2C 已将 D0 唤醒合并进 `VoodooI2CPCIController`，不再包含旧类。虽然显示的版本号仍是 2.9.1，**构建来源不同，类可能不同**。

```bash
python3 tools/patch_efi.py /path/to/EFI --touchpad
python3 tools/patch_efi.py /path/to/EFI --touchpad --apply
```

本轮仅修改适配文件中一个 `IOClass` 值：

```text
VoodooI2CPCILakeController → VoodooI2CPCIController
```

工具先检查实际 VoodooI2C 二进制：如果仍包含 Lake 类，会拒绝应用这个版本适配。PCI 匹配范围、总线时序与其他 EFI 文件均不改变。原有 `-vi2c-force-polling` 保留；本方案没有增加 Arrow Lake GPIO 中断支持。

该修复要求已安装 VoodooI2C、其依赖插件、VoodooI2CHID、Arrow Lake 适配文件，并且触控板在 ACPI 中处于可见状态。它不负责修复所有 `_CRS`、GPIO 或 HID 描述符问题。重启后本机由机主确认正常。

## 5. Android USB 共享与 AX211 Wi-Fi

安装恢复环境需要联网。本机 Android USB 共享使用了 iKeramat 的 `HoRNDIS` mac-15.5 构建，bundle 版本 9.2。本次随后成功完成安装，但这不是对所有安卓 USB 协议或 Tahoe 版本的兼容保证。

```bash
python3 tools/fetch_kexts.py --android-tether --output downloads
python3 tools/patch_efi.py /path/to/EFI --android-tether --dependencies downloads
python3 tools/patch_efi.py /path/to/EFI --android-tether --dependencies downloads --apply
```

在手机上打开 USB 网络共享；该构建针对 RNDIS，不保证支持只提供其他协议的手机配置。

进入桌面后，已有的 **itlwm 2.3.0** 配合 [HeliPort](https://github.com/OpenIntelWireless/HeliPort/releases) 连接 AX211。itlwm 通常表现为以太网接口，不会因为系统菜单里没有原生 Wi-Fi 就必然代表驱动未加载。不要同时注入 itlwm 和 AirportItlwm。

## 修改 boot-args 后的重要一步

`config.plist` 中的 NVRAM/Add **不一定覆盖已经存在的 NVRAM 值**。如果重启后下面命令中没有新参数，单改 plist 还不够：

```bash
sysctl kern.bootargs
```

在目标黑苹果上确认挂载的是**这次实际启动所用的 EFI**，然后按 [启动参数同步与恢复](docs/boot-args.md) 操作。不要照抄别人的整串参数；保留自己的原值。APIC 和触控板修复本身不需要新增参数。

## HDMI、Type-C 与 USB 端口

HDMI 接入时驱动先读到 0 字节 EDID，初始化了 1024×768 的外屏资源；稍后读到 256 字节 EDID，却没有正常通知 WindowServer。保持显示器开机、选中 HDMI 输入并连接 HDMI 后重启，成功得到 2560×1440、120Hz。

**本文没有修复热插拔。需要外屏时先连好 HDMI 再开机，是本次验证可用的做法。**

原 Windows 硬件扫描显示 Mi Monitor 经 Intel 核显输出；在当前 NVIDIA 配置下，两处 USB-C 直连都无画面。不能通过 USB 端口映射把接在核显上的视频通道改接到独显。核显 `7D67` 已有 [WTLIntelGfx 实验项目](https://github.com/watchthelight-labs/WTLIntelGfx)，本次没有安装和验证该项目，也不声称它能修好本机 Type-C 多屏。

| 位置 | 已记录接口 / 验证 |
|---|---|
| 右侧 | 2 个 USB-A；未逐口建立映射 |
| 左侧 | 1 个 USB-A：连接扩展坞可用；1 个 Type-C：外屏无画面；1 个 3.5mm：待验证 |
| 后侧 | Type-C / 雷电口：外屏无画面；HDMI：带线开机可用 |

USBToolBox + UTBDefault 是现有通用配置，**本仓库没有适用于这台机器的完整 UTBMap**。芯片组控制器运行时只出现前 15 个 USB2 逻辑端口，USB3 部分仍需进一步映射。曾发生 BIOS 可读启动 U 盘、macOS 运行时却读不到的情况；当时将 U 盘接回另一台 Mac 修改 EFI，再放回启动。不要据此断言所有 USB 口或 U 盘都正常。

## 桌面设置与 BetterDisplay

- 时间问题来自 `US/Pacific` 时区。改为 `Asia/Shanghai`、关闭基于定位的自动时区，保留 `time.apple.com` 网络校时后正常；本次没有改 Windows 注册表，也没有证明存在 RTC 故障。
- 鼠标使用 [Scroll Reverser 2.0.2](https://github.com/pilotmoon/Scroll-Reverser/releases/tag/v2.0.2)：鼠标设 Classic，水平滚动 Unchanged，关闭固定步长覆盖；辅助功能权限由用户在系统设置手动授权。系统全局“自然滚动”未改。
- BetterDisplay **5.2.1** 在本机启动时 `EXC_BAD_INSTRUCTION / SIGILL`；内部原因未确定。改用官方 **[4.3.7](https://github.com/waydabber/BetterDisplay/releases/tag/v4.3.7)** 后持续运行。本机没有完成所有显示管理功能验证。

## 回滚与提交问题

每次 `--apply` 前都会在 EFI 同级的 `yaoshi-backups/<时间戳>/EFI` 保存完整副本。关闭目标电脑后，从另一台电脑恢复该备份，并恢复本次手动改过的 NVRAM 参数；**恢复 EFI 文件不会自动恢复 NVRAM**。不要删除 Windows 的 EFI 文件夹。

提交问题请使用 Issue 模板，提供 BIOS、组件版本、故障阶段和去掉个人标识的必要片段。不要上传整份 SysReport、原始 EFI、`MSDM` 表、SMBIOS 序列号、系统 UUID、MAC 地址、Wi-Fi 密码或 SSH 凭据。

## 工具验证

工具代码将本次成功的手动修改整理为可重复执行的步骤，尚未在第二台实机上完成整套安装验证。

```bash
python3 -m unittest discover -s tests -v
```

发布前通过 12 项标准库测试，覆盖 MADT 拓扑与中断保留、损坏表拒绝、默认预览不写文件、重复应用不产生重复条目、SMBIOS 保留、依赖顺序、冲突拒绝和模拟写入失败恢复。另在未公开的原始 EFI 副本上离线组合验证：APIC 输出与本次实机修复后的 SHA-256 完全一致，组合修改可重复运行而不再产生变化；三个固定版本驱动压缩包的哈希及提取也已验证。

离线测试不能证明不同 BIOS、控制器和引脚布局的实机兼容性，也不代替 ocvalidate 和备份后的启动测试。

## 来源与许可

本仓库的原创说明和工具采用 [MIT](LICENSE)。第三方组件遵循各自许可；下载链接不代表本仓库拥有这些组件的版权，也不改变 1401 等上游项目的许可条件。

- [1401](https://github.com/nullmoth/1401) / [NullMoth NVIDIA](https://github.com/nullmoth/nvidia-macos-driver)：基础安装、显卡驱动和背光选项。
- [OpenCore](https://github.com/acidanthera/OpenCorePkg) / [XNU ACPI](https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/i386/acpi.c)：配置及 MADT 调查参考。
- [WTLI2CArrowLake](https://github.com/watchthelight-labs/WTLI2CArrowLake) / [VoodooI2C](https://github.com/VoodooI2C/VoodooI2C/commit/054d5d1297)：新旧控制器类及 D0 唤醒差异。
- [AppleALC](https://github.com/acidanthera/AppleALC) / [SimpleHDA](https://github.com/laobamac/SimpleHDA)：ALC274 和 Tahoe 音频恢复。
- [HoRNDIS fork](https://github.com/iKeramat/HoRNDIS) / [OpenIntelWireless](https://github.com/OpenIntelWireless)：网络相关组件。

实机由仓库所有者提供并确认结果；排查记录整理和工具编写有 AI 协助。没有把一次单机成功描述为全系列兼容认证。
