from Scripts import integrity_checker
from Scripts.datasets import cpu_data
from Scripts.datasets import kext_data
from Scripts.datasets import os_data
from Scripts.datasets import pci_data
from Scripts.datasets import codec_layouts
from Scripts import utils
import os
import shutil

try:
    long
    unicode
except NameError:
    long = int
    unicode = str

class KextMaestro:
    """
    kexts（内核扩展）管理类，用于管理和配置macOS系统上的内核扩展(kext)
    主要功能包括：
    - PCI ID提取
    - Intel HEDT CPU检测
    - kexts（内核扩展）兼容性检查
    - kexts（内核扩展）安装和配置
    """
    def __init__(self):
        self.utils = utils.Utils()
        self.matching_keys = [
            "IOPCIMatch", 
            "IONameMatch", 
            "IOPCIPrimaryMatch", 
            "idProduct", 
            "idVendor", 
            "HDAConfigDefault"
        ]
        self.ock_files_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "OCK_Files")
        self.kexts = kext_data.kexts
        
    def extract_pci_id(self, kext_path):
        """
        从指定的kext路径中提取PCI ID信息
        
        参数:
            kext_path: kext文件的路径
        
        返回:
            包含PCI ID的列表，格式为["厂商ID-设备ID"]
        """
        if not os.path.exists(kext_path):
            return []

        plist_path = os.path.join(kext_path, "Contents", "Info.plist")
        plist_data = self.utils.read_file(plist_path)

        pci_ids = []

        for personality_name, properties in plist_data.get("IOKitPersonalities", {}).items():
            matching_keys = [key for key in self.matching_keys if key in properties]
            
            if not matching_keys:
                continue
            
            match_key = matching_keys[0]

            if match_key in ["IOPCIMatch", "IOPCIPrimaryMatch"]:
                pci_list = properties[match_key].split(" ")
                for pci_id in pci_list:
                    vendor_id = pci_id[-4:]
                    device_id = pci_id[2:6]
                    pci_ids.append("{}-{}".format(vendor_id, device_id).upper())
            elif match_key == "IONameMatch":
                for pci_id in properties[match_key]:
                    vendor_id = pci_id[3:7]
                    device_id = pci_id.split(",")[1].zfill(4)
                    pci_ids.append("{}-{}".format(vendor_id, device_id).upper())
            elif match_key == "idProduct":
                vendor_id = self.utils.int_to_hex(properties["idVendor"]).zfill(4)
                device_id = self.utils.int_to_hex(properties["idProduct"]).zfill(4)
                pci_ids.append("{}-{}".format(vendor_id, device_id).upper())
            elif match_key == "HDAConfigDefault":
                for codec_layout in properties[match_key]:
                    codec_id = self.utils.int_to_hex(codec_layout.get("CodecID")).zfill(8)
                    pci_ids.append("{}-{}".format(codec_id[:4], codec_id[-4:]))
                pci_ids = sorted(list(set(pci_ids)))

        return pci_ids

    def is_intel_hedt_cpu(self, processor_name, cpu_codename):
        """
        检测CPU是否为Intel HEDT (High-End Desktop) CPU
        
        参数:
            processor_name: CPU处理器名称
            cpu_codename: CPU代号
        
        返回:
            布尔值，表示是否为Intel HEDT CPU
        """
        if cpu_codename in cpu_data.IntelCPUGenerations[45:66]:
            return cpu_codename.endswith(("-X", "-P", "-W", "-E", "-EP", "-EX"))
        
        if cpu_codename in cpu_data.IntelCPUGenerations[66:]:
            return "Xeon" in processor_name
        
        return False

    def check_kext(self, index, target_darwin_version, allow_unsupported_kexts=False):
        """
        检查 kext（内核扩展）是否兼容目标macOS版本
        
        参数:
            index: kext在kexts列表中的索引
            target_darwin_version: 目标Darwin版本号
            allow_unsupported_kexts: 是否允许加载不支持的kext
        """
        kext = self.kexts[index]

        if kext.checked or not (allow_unsupported_kexts or self.utils.parse_darwin_version(kext.min_darwin_version) <= self.utils.parse_darwin_version(target_darwin_version) <= self.utils.parse_darwin_version(kext.max_darwin_version)):
            return

        kext.checked = True

        for requires_kext_name in kext.requires_kexts:
            requires_kext_index = kext_data.kext_index_by_name.get(requires_kext_name)
            if requires_kext_index:
                self.check_kext(requires_kext_index, target_darwin_version, allow_unsupported_kexts)

        if kext.conflict_group_id:
            for other_kext in self.kexts:
                if other_kext.conflict_group_id == kext.conflict_group_id and other_kext.name != kext.name:
                    other_kext.checked = False

    def select_required_kexts(self, hardware_report, macos_version, needs_oclp, acpi_patches):
        """
        根据硬件报告和 macOS 版本选择必要的 kexts（内核扩展）
        
        参数:
            hardware_report: 硬件报告信息
            macos_version: macOS版本号
            needs_oclp: 是否需要OpenCore Legacy Patcher
            acpi_patches: ACPI补丁列表
        
        返回:
            更新后的needs_oclp值
        """
        self.utils.head("选择必要的 kexts（内核扩展）")
        print("")
        print("正在检查必要的 kexts（内核扩展）...")

        for kext in self.kexts:
            kext.checked = kext.required

        selected_kexts = ["UTBDefault"]

        if "Intel" in hardware_report.get("CPU").get("Manufacturer"):
            selected_kexts.extend(("SMCProcessor", "SMCSuperIO"))

        if "Laptop" in hardware_report.get("Motherboard").get("Platform") and not "SURFACE" in hardware_report.get("Motherboard").get("Name"):
            selected_kexts.append("SMCBatteryManager")
            if "DELL" in hardware_report.get("Motherboard").get("Name"):
                selected_kexts.append("SMCDellSensors")
            selected_kexts.append("SMCLightSensor")

        if  not (" Core" in hardware_report.get("CPU").get("Processor Name") and \
                 hardware_report.get("CPU").get("Codename") in cpu_data.IntelCPUGenerations[28:]) or \
            self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("23.0.0"):
            selected_kexts.append("RestrictEvents")

        for codec_properties in hardware_report.get("Sound", {}).values():
            if codec_properties.get("Device ID") in codec_layouts.data:
                if self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("25.0.0"):
                    print("\n\033[1;93m注意:\033[0m 从macOS Tahoe 26 DP2开始，Apple已移除AppleHDA kext并使用Apple T2芯片进行音频管理。")
                    print("要使用AppleALC，您必须回滚AppleHDA。或者，您可以使用VoodooHDA。")
                    print("")
                    print("1. \033[1mAppleALC\033[0m - 需要使用\033[1;93mOpenCore Legacy Patcher\033[0m回滚AppleHDA")
                    print("2. \033[1mVoodooHDA\033[0m - 音质较低，需要手动注入到/Library/Extensions")
                    print("")
                    while True:
                        kext_option = self.utils.request_input("选择系统的音频kext: ").strip()
                        if kext_option == "1":
                            needs_oclp = True
                            selected_kexts.append("AppleALC")
                            break
                        elif kext_option == "2":
                            break
                        else:
                            print("\033[91m无效选择，请重试。\033[0m\n\n")
                else:
                    selected_kexts.append("AppleALC")
        
        if "AMD" in hardware_report.get("CPU").get("Manufacturer") and self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("21.4.0") or \
            int(hardware_report.get("CPU").get("CPU Count")) > 1 and self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("19.0.0"):
            selected_kexts.append("AppleMCEReporterDisabler")

        if self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("22.0.0") and not "AVX2" in hardware_report.get("CPU").get("SIMD Features"):
            selected_kexts.append("CryptexFixup")

        if  "Lunar Lake" not in hardware_report.get("CPU").get("Codename") and \
            "Meteor Lake" not in hardware_report.get("CPU").get("Codename") and \
            hardware_report.get("CPU").get("Codename") in cpu_data.IntelCPUGenerations[:20] and \
            int(hardware_report.get("CPU").get("Core Count")) > 6:
            selected_kexts.append("CpuTopologyRebuild")

        for gpu_name, gpu_props in hardware_report.get("GPU", {}).items():
            if "Integrated GPU" in gpu_props.get("Device Type"):
                if "AMD" in gpu_props.get("Manufacturer"):
                    selected_kexts.append("NootedRed")
                else:
                    selected_kexts.append("WhateverGreen")
            else:
                if "Navi 22" in gpu_props.get("Codename"):
                    selected_kexts.append("NootRX")
                    break

                if gpu_props.get("Codename") in {"Navi 21", "Navi 23"}:
                    print("\n*** 发现{}是AMD {} GPU。".format(gpu_name, gpu_props.get("Codename")))
                    print("")
                    print("\033[91m重要: 黑屏修复\033[0m")
                    print("如果在verbose模式后遇到黑屏:")
                    print("    1. 使用ProperTree打开config.plist")
                    print("    2. 导航到NVRAM -> Add -> 7C436110-AB2A-4BBB-A880-FE41995C9F82 -> boot-args")
                    print("    3. 从boot-args中移除\"-v debug=0x100 keepsyms=1\"")
                    print("")
                    if self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("25.0.0"):
                        recommended_option = 1
                        recommended_name = "NootRX"
                        max_option = 3
                        print("\033[1;93m注意:\033[0m 从macOS Tahoe 26开始，WhateverGreen对AMD {} GPU存在已知的连接器补丁问题。".format(gpu_props.get("Codename")))
                        print("要避免这种情况，您可以使用NootRX或选择不安装GPU kext。")
                        print("")
                        print("1. \033[1mNootRX\033[0m - 使用最新的GPU固件")
                        print("2. \033[1mWhateverGreen\033[0m - 使用原始的Apple固件")
                        print("3. \033[1m不使用任何kext\033[0m")
                    else:
                        recommended_option = 2
                        recommended_name = "WhateverGreen"
                        max_option = 2
                        print("\033[1;93m注意:\033[0m")
                        print("- AMD {} GPU有两个可用的kext选项:".format(gpu_props.get("Codename")))
                        print("- 安装后您可以尝试不同的kext，以找到最适合您系统的一个")
                        print("")
                        print("1. \033[1mNootRX\033[0m - 使用最新的GPU固件")
                        print("2. \033[1mWhateverGreen\033[0m - 使用原始的Apple固件")
                    print("")

                    if any(other_gpu_props.get("Manufacturer") == "Intel" for other_gpu_props in hardware_report.get("GPU", {}).values()):
                        print("\033[91m重要:\033[0m NootRX kext与Intel GPU不兼容")
                        print("由于Intel GPU兼容性，自动选择WhateverGreen kext")
                        print("")
                        self.utils.request_input("按Enter键继续...")
                        continue

                    kext_option = self.utils.request_input("为您的AMD {} GPU选择kext (默认值: {}): ".format(gpu_props.get("Codename"), recommended_name)).strip() or str(recommended_option)
                    
                    if kext_option.isdigit() and 0 < int(kext_option) < max_option + 1:
                        selected_option = int(kext_option)
                    else:
                        print("\033[93m无效选择，使用推荐选项: {}\033[0m".format(recommended_option))
                        selected_option = recommended_option

                    if selected_option == 1:
                        selected_kexts.append("NootRX")
                    elif selected_option == 2:
                        selected_kexts.append("WhateverGreen")
                    
                    continue

                if self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("25.0.0"):
                    print("\n*** 发现{}是AMD {} GPU。".format(gpu_name, gpu_props.get("Codename")))
                    print("")
                    print("\033[1;93m注意:\033[0m 从macOS Tahoe 26开始，WhateverGreen对AMD GPU存在已知的连接器补丁问题。")
                    print("当前建议不使用WhateverGreen。")
                    print("但是，您仍然可以尝试添加它，看看它是否在您的系统上工作。")
                    print("")
                    self.utils.request_input("按Enter键继续...")
                    break

                selected_kexts.append("WhateverGreen")

        if "Laptop" in hardware_report.get("Motherboard").get("Platform") and ("ASUS" in hardware_report.get("Motherboard").get("Name") or "NootedRed" in selected_kexts):
            selected_kexts.append("ForgedInvariant")

        if self.is_intel_hedt_cpu(hardware_report.get("CPU").get("Processor Name"), hardware_report.get("CPU").get("Codename")):
            selected_kexts.append("CpuTscSync")

        if needs_oclp:
            selected_kexts.extend(("AMFIPass", "RestrictEvents"))

        for network_name, network_props in hardware_report.get("Network", {}).items():
            device_id = network_props.get("Device ID")

            if device_id in pci_data.BroadcomWiFiIDs and self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("23.0.0"):
                selected_kexts.append("IOSkywalkFamily")

            if device_id in pci_data.BroadcomWiFiIDs[:15]:
                selected_kexts.append("AirportBrcmFixup")
            elif device_id == pci_data.BroadcomWiFiIDs[15] and self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("19.0.0"):
                selected_kexts.append("AirportBrcmFixup")
            elif device_id in pci_data.BroadcomWiFiIDs[16:18] and self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("20.0.0"):
                selected_kexts.append("AirportBrcmFixup")
            elif device_id in pci_data.IntelWiFiIDs:
                print("\n*** 发现{}是Intel WiFi设备。".format(network_name))
                print("")
                print("\033[1;93m注意:\033[0m Intel WiFi设备有两个可用的kext选项:")
                print("")
                print("1. \033[1mAirportItlwm\033[0m - 使用原生WiFi设置菜单")
                print("   • 提供接力(Handoff)、通用剪贴板(Universal Clipboard)、定位服务(Location Services)、即时热点(Instant Hotspot)支持")
                print("   • 支持企业级安全")

                if self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("24.0.0"):
                    print("   • \033[91m从macOS Sequoia 15开始\033[0m: 可以与OCLP根补丁一起使用，但可能会导致问题")
                elif self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("23.0.0"):
                    print("   • \033[91m在macOS Sonoma 14上\033[0m: 除非使用OCLP根补丁，否则iServices将无法工作")
                
                print("")
                print("2. \033[1mitlwm\033[0m - 整体更稳定")
                print("   • 使用 HeliPort 应用程序代替原生WiFi设置菜单")
                print("   • 没有 Apple 连续性(Apple Continuity)功能和企业级安全")
                print("   • 可以连接到隐藏网络")
                print("")

                recommended_option = 2 if self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("23.0.0") else 1
                recommended_name = "itlwm" if recommended_option == 2 else "AirportItlwm"

                if "Beta" in os_data.get_macos_name_by_darwin(macos_version):
                    print("\033[91m重要:\033[0m 对于macOS Beta版本，仅支持itlwm kext")
                    print("")
                    self.utils.request_input("按Enter键继续...")
                    selected_option = recommended_option
                else:
                    kext_option = self.utils.request_input("为您的Intel WiFi设备选择kext (默认值: {}): ".format(recommended_name)).strip() or str(recommended_option)
                    
                    if kext_option.isdigit() and 0 < int(kext_option) < 3:
                        selected_option = int(kext_option)
                    else:
                        print("\033[91m无效选择，使用推荐选项: {}\033[0m".format(recommended_option))
                        selected_option = recommended_option
                
                if selected_option == 2:
                    selected_kexts.append("itlwm")
                else:
                    selected_kexts.append("AirportItlwm")
                    
                    if self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("24.0.0"):
                        selected_kexts.append("IOSkywalkFamily")
                    elif self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("23.0.0"):
                        print("")
                        print("\033[1;93m注意:\033[0m 从macOS Sonoma 14开始，没有补丁的情况下，AirportItlwm的iServices将无法工作")
                        print("")
                        while True:
                            option = self.utils.request_input("应用OCLP根补丁修复iServices? (yes/No): ").strip().lower()
                            if option == "yes":
                                selected_kexts.append("IOSkywalkFamily")
                                break
                            elif option == "no":
                                break
                            else:
                                print("\033[91m无效选择，请重试。\033[0m\n\n")
            elif device_id in pci_data.AtherosWiFiIDs[:8]:
                selected_kexts.append("corecaptureElCap")
                if self.utils.parse_darwin_version(macos_version) > self.utils.parse_darwin_version("20.99.99"):
                    selected_kexts.append("AMFIPass")
            elif device_id in pci_data.IntelI22XIDs:
                selected_kexts.append("AppleIGC")
            elif device_id in pci_data.AtherosE2200IDs:
                selected_kexts.append("AtherosE2200Ethernet")
            elif device_id in pci_data.IntelMausiIDs:
                selected_kexts.append("IntelMausiEthernet")
            elif device_id in pci_data.RealtekRTL8125IDs:
                selected_kexts.append("LucyRTL8125Ethernet")
            elif device_id in pci_data.RealtekRTL8100IDs:
                selected_kexts.append("RealtekRTL8100")
            elif device_id in pci_data.RealtekRTL8111IDs:
                selected_kexts.append("RealtekRTL8111")
            elif device_id in pci_data.AppleIGBIDs:
                selected_kexts.append("AppleIGB")
            elif device_id in pci_data.BroadcomBCM57XXIDs:
                selected_kexts.append("CatalinaBCM5701Ethernet")
            elif device_id in pci_data.IntelX500IDs:
                selected_kexts.append("IntelLucy")

        if all(network_props.get("Bus Type") == "USB" for network_props in hardware_report.get("Network", {}).values()):
            selected_kexts.append("NullEthernet")

        for bluetooth_name, bluetooth_props in hardware_report.get("Bluetooth", {}).items():
            usb_id = bluetooth_props.get("Device ID")

            if usb_id in pci_data.AtherosBluetoothIDs:
                selected_kexts.extend(("Ath3kBT", "Ath3kBTInjector"))
            elif usb_id in pci_data.BroadcomBluetoothIDs:               
                selected_kexts.append("BrcmFirmwareData")
            elif usb_id in pci_data.IntelBluetoothIDs:
                selected_kexts.append("IntelBluetoothFirmware")
            elif usb_id in pci_data.BluetoothIDs[-1]:
                selected_kexts.append("BlueToolFixup")

        if "Laptop" in hardware_report.get("Motherboard").get("Platform"):
            if "SURFACE" in hardware_report.get("Motherboard").get("Name"):
                selected_kexts.append("BigSurface")
            else:
                if "ASUS" in hardware_report.get("Motherboard").get("Name"):
                    selected_kexts.append("AsusSMC")
                selected_kexts.append("BrightnessKeys")

                for device_name, device_props in hardware_report.get("Input").items():
                    if not device_props.get("Device"):
                        continue

                    device_id = device_props.get("Device")
                    idx = None
                    if device_id in pci_data.InputIDs:
                        idx = pci_data.InputIDs.index(device_id)

                    if "PS/2" in device_props.get("Device Type", "None"):
                        selected_kexts.append("VoodooPS2Controller")
                        if device_id.startswith("SYN"):
                            selected_kexts.append("VoodooRMI")
                        elif idx and 75 < idx < 79:
                            selected_kexts.append("VoodooSMBus")
                    if "I2C" in device_props.get("Device Type", "None"):
                        selected_kexts.append("VoodooI2CHID")
                        if idx:
                            if idx < 76:
                                selected_kexts.append("AlpsHID")
                            elif 78 < idx:
                                selected_kexts.append("VoodooRMI")
        
        for device_name, device_info in hardware_report.get("System Devices", {}).items():
            if device_info.get("Bus Type") == "ACPI" and device_info.get("Device") in pci_data.YogaHIDs:
                selected_kexts.append("YogaSMC")

        if any(patch.checked for patch in acpi_patches if patch.name == "BATP"):
            selected_kexts.append("ECEnabler")

        for controller_name, controller_props in hardware_report.get("SD Controller", {}).items():
            if controller_props.get("Device ID") in pci_data.RealtekCardReaderIDs:
                if controller_props.get("Device ID") in pci_data.RealtekCardReaderIDs[5:]:
                    selected_kexts.append("Sinetek-rtsx")
                else:
                    selected_kexts.append("RealtekCardReader")
        
        for controller_name, controller_props in hardware_report.get("Storage Controllers", {}).items():
            if "NVMe" in controller_name or "NVM Express" in controller_name:
                selected_kexts.append("NVMeFix")
            elif not "AHCI" in controller_name or "AMD" in hardware_report.get("CPU").get("Manufacturer"):
                if self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("20.0.0"):
                    if controller_props.get("Device ID") in pci_data.UnsupportedSATAControllerIDs:
                        selected_kexts.append("CtlnaAHCIPort")
                else:
                    if controller_props.get("Device ID") in pci_data.UnsupportedSATAControllerIDs[15:]:
                        selected_kexts.append("SATA-unsupported")

        for controller_name, controller_props in hardware_report.get("USB Controllers").items():
            device_id = controller_props.get("Device ID")
            if device_id in pci_data.UnsupportedUSBControllerIDs:
                idx = pci_data.UnsupportedUSBControllerIDs.index(device_id)
                if idx == 0:
                    if "Laptop" in hardware_report.get("Motherboard").get("Platform"):
                        selected_kexts.append("GenericUSBXHCI")
                else:
                    selected_kexts.append("XHCI-unsupported")

        if "Sandy Bridge" in hardware_report.get("CPU").get("Codename"):
            selected_kexts.append("ASPP-Override")

        if "Sandy Bridge" in hardware_report.get("CPU").get("Codename") or "Ivy Bridge" in hardware_report.get("CPU").get("Codename"):
            selected_kexts.extend(("AppleIntelCPUPowerManagement", "AppleIntelCPUPowerManagementClient"))

        allow_unsupported_kexts = self.verify_kext_compatibility(selected_kexts, macos_version)

        for name in selected_kexts:
            self.check_kext(kext_data.kext_index_by_name.get(name), macos_version, allow_unsupported_kexts)

        return needs_oclp

    def install_kexts_to_efi(self, macos_version, kexts_directory):
        """
        将选中的 kexts（内核扩展）安装到EFI目录
        
        参数:
            macos_version: macOS版本号
            kexts_directory: EFI中的kexts目录路径
        """
        for kext in self.kexts:
            if kext.checked:
                try:
                    source_kext_path = destination_kext_path = None

                    kext_paths = self.utils.find_matching_paths(self.ock_files_dir, extension_filter=".kext", name_filter=kext.name)
                    for kext_path, type in kext_paths:
                        if "AirportItlwm" == kext.name:
                            version = macos_version[:2]
                            if all((self.kexts[kext_data.kext_index_by_name.get("IOSkywalkFamily")].checked, self.kexts[kext_data.kext_index_by_name.get("IO80211FamilyLegacy")].checked)) or self.utils.parse_darwin_version("24.0.0") <= self.utils.parse_darwin_version(macos_version):
                                version = "22"
                            elif self.utils.parse_darwin_version("23.4.0") <= self.utils.parse_darwin_version(macos_version):
                                version = "23.4"
                            elif self.utils.parse_darwin_version("23.0.0") <= self.utils.parse_darwin_version(macos_version):
                                version = "23.0"
                            
                            if version in kext_path:
                                source_kext_path = os.path.join(self.ock_files_dir, kext_path)
                                destination_kext_path = os.path.join(kexts_directory, os.path.basename(kext_path))
                                break
                        else:
                            main_kext = kext_path.split("/")[0]
                            main_kext_index = kext_data.kext_index_by_name.get(main_kext)
                            if not main_kext_index or self.kexts[main_kext_index].checked:
                                if os.path.splitext(os.path.basename(kext_path))[0] in kext.name:
                                    source_kext_path = os.path.join(self.ock_files_dir, kext_path)
                                    destination_kext_path = os.path.join(kexts_directory, os.path.basename(kext_path))
                    
                    if os.path.exists(source_kext_path):
                        shutil.copytree(source_kext_path, destination_kext_path, dirs_exist_ok=True)
                except:
                    continue

    def process_kext(self, kexts_directory, kext_path):
        """
        处理kext文件，提取必要的信息
        
        参数:
            kexts_directory: kext所在的目录
            kext_path: kext的相对路径
        
        返回:
            包含kext信息的字典
        """
        try:
            plist_path = self.utils.find_matching_paths(os.path.join(kexts_directory, kext_path), extension_filter=".plist", name_filter="Info")[0][0]
            bundle_info = self.utils.read_file(os.path.join(kexts_directory, kext_path, plist_path))

            if isinstance(bundle_info.get("CFBundleIdentifier", None), (str, unicode)):
                pass
        except:
            return None

        executable_path = os.path.join("Contents", "MacOS", bundle_info.get("CFBundleExecutable", "None"))
        if not os.path.exists(os.path.join(kexts_directory, kext_path, executable_path)):
            executable_path = ""
        
        return {
            "BundlePath": kext_path.replace("\\", "/").lstrip("/"),
            "Enabled": True,
            "ExecutablePath": executable_path.replace("\\", "/").lstrip("/"),
            "PlistPath": plist_path.replace("\\", "/").lstrip("/"),
            "BundleIdentifier": bundle_info.get("CFBundleIdentifier"),
            "BundleVersion": bundle_info.get("CFBundleVersion"),
            "BundleLibraries": {
                bundle_identifier: bundle_version
                for bundle_identifier, bundle_version in bundle_info.get("OSBundleLibraries", {}).items() 
            }
        }

    def modify_kexts(self, plist_path, hardware_report, macos_version):
        """
        根据硬件报告和macOS版本修改kext的Info.plist文件
        
        参数:
            plist_path: Info.plist文件的路径
            hardware_report: 硬件报告信息
            macos_version: macOS版本号
        """
        try:
            bundle_info = self.utils.read_file(plist_path)

            if bundle_info.get("IOKitPersonalities").get("itlwm").get("WiFiConfig"):
                from Scripts import wifi_profile_extractor
                
                wifi_profiles = wifi_profile_extractor.WifiProfileExtractor().get_profiles()

                if wifi_profiles:
                    bundle_info["IOKitPersonalities"]["itlwm"]["WiFiConfig"] = {
                        "WiFi_{}".format(index): {
                            "password": profile[1],
                            "ssid": profile[0]
                        }
                        for index, profile in enumerate(wifi_profiles, start=1)
                    }
            elif bundle_info.get("IOKitPersonalities").get("VoodooTSCSync"):
                bundle_info["IOKitPersonalities"]["VoodooTSCSync"]["IOPropertyMatch"]["IOCPUNumber"] = 0 if self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("21.0.0") else int(hardware_report["CPU"]["Core Count"]) - 1
            elif bundle_info.get("IOKitPersonalities").get("AmdTscSync"):
                bundle_info["IOKitPersonalities"]["AmdTscSync"]["IOPropertyMatch"]["IOCPUNumber"] = 0 if self.utils.parse_darwin_version(macos_version) >= self.utils.parse_darwin_version("21.0.0") else int(hardware_report["CPU"]["Core Count"]) - 1
            else:
                return
            
            self.utils.write_file(plist_path, bundle_info)
        except:
            return            
        
    def load_kexts(self, hardware_report, macos_version, kexts_directory):
        """
        加载kext信息并生成kernel_add配置
        
        参数:
            hardware_report: 硬件报告信息
            macos_version: macOS版本号
            kexts_directory: kext所在的目录
        
        返回:
            kernel_add配置列表
        """
        kernel_add = []
        unload_kext = []

        if self.kexts[kext_data.kext_index_by_name.get("IO80211ElCap")].checked:
            unload_kext.extend((
                "AirPortBrcm4331",
                "AppleAirPortBrcm43224"
            ))
        elif self.kexts[kext_data.kext_index_by_name.get("VoodooSMBus")].checked:
            unload_kext.append("VoodooPS2Mouse")
        elif self.kexts[kext_data.kext_index_by_name.get("VoodooRMI")].checked:
            if not self.kexts[kext_data.kext_index_by_name.get("VoodooI2C")].checked:
                unload_kext.append("RMII2C")
            else:
                unload_kext.extend((
                    "VoodooSMBus",
                    "RMISMBus",
                    "VoodooI2CHID"
                ))

        kext_paths = self.utils.find_matching_paths(kexts_directory, extension_filter=".kext")
        bundle_list = []

        for kext_path, type in kext_paths:
            bundle_info = self.process_kext(kexts_directory, kext_path)

            if bundle_info:
                self.modify_kexts(os.path.join(kexts_directory, kext_path, bundle_info.get("PlistPath")), hardware_report, macos_version)

                bundle_list.append(bundle_info)

        bundle_dict = {bundle["BundleIdentifier"]: bundle for bundle in bundle_list}

        sorted_bundles = []
        
        visited = set()
        seen_identifier = set()

        def visit(bundle):
            if os.path.splitext(os.path.basename(bundle.get("BundlePath")))[0] in unload_kext or (bundle.get("BundlePath"), bundle.get("BundleIdentifier")) in visited:
                return
                        
            bundle["MaxKernel"] = os_data.get_latest_darwin_version()
            bundle["MinKernel"] = os_data.get_lowest_darwin_version()

            kext_index = kext_data.kext_index_by_name.get(os.path.splitext(os.path.basename(bundle.get("BundlePath")))[0])

            if kext_index:
                bundle["MaxKernel"] = self.kexts[kext_index].max_darwin_version
                bundle["MinKernel"] = self.kexts[kext_index].min_darwin_version
            
            for dep_identifier in bundle.get("BundleLibraries"):
                if dep_identifier in bundle_dict:
                    visit(bundle_dict[dep_identifier])
                    
                    bundle["MaxKernel"] = bundle["MaxKernel"] if self.utils.parse_darwin_version(bundle["MaxKernel"]) < self.utils.parse_darwin_version(bundle_dict[dep_identifier].get("MaxKernel", "99.99.99")) else bundle_dict[dep_identifier]["MaxKernel"]
                    bundle["MinKernel"] = bundle["MinKernel"] if self.utils.parse_darwin_version(bundle["MinKernel"]) > self.utils.parse_darwin_version(bundle_dict[dep_identifier].get("MinKernel", "0.0.0")) else bundle_dict[dep_identifier]["MinKernel"]

            if os.path.splitext(os.path.basename(bundle.get("BundlePath")))[0] == "AirPortBrcm4360_Injector":
                bundle["MaxKernel"] = "19.99.99"
            elif os.path.splitext(os.path.basename(bundle.get("BundlePath")))[0] == "AirportItlwm":
                bundle["MaxKernel"] = macos_version[:2] + bundle["MaxKernel"][2:]
                bundle["MinKernel"] = macos_version[:2] + bundle["MinKernel"][2:]

            visited.add((bundle.get("BundlePath"), bundle.get("BundleIdentifier")))

            if bundle.get("BundleIdentifier") in seen_identifier:
                bundle["Enabled"] = False
            else:
                seen_identifier.add(bundle.get("BundleIdentifier"))

            sorted_bundles.append(bundle)

        for bundle in bundle_list:
            visit(bundle)

        latest_darwin_version = (os_data.get_latest_darwin_version(), os_data.get_latest_darwin_version(include_beta=False))
        lowest_darwin_version = os_data.get_lowest_darwin_version()

        for bundle in sorted_bundles:
            kernel_add.append({
                "Arch": "x86_64",
                "BundlePath": bundle.get("BundlePath"),
                "Comment": "",
                "Enabled": bundle.get("Enabled"),
                "ExecutablePath": bundle.get("ExecutablePath"),
                "MaxKernel": "" if bundle.get("MaxKernel") in latest_darwin_version else bundle.get("MaxKernel"),
                "MinKernel": "" if bundle.get("MinKernel") == lowest_darwin_version else bundle.get("MinKernel"),
                "PlistPath": bundle.get("PlistPath")
            })

        return kernel_add

    def uncheck_kext(self, index):
        """
        取消选中指定索引的kext
        
        参数:
            index: kext在kexts列表中的索引
        """
        kext = self.kexts[index]
        kext.checked = False

        for other_kext in self.kexts:
            if other_kext.name in kext.requires_kexts and not other_kext.required:
                other_kext.checked = False

    def verify_kext_compatibility(self, selected_kexts, target_darwin_version):
        """
        验证选中的kext是否与目标macOS版本兼容
        
        参数:
            selected_kexts: 选中的kext列表
            target_darwin_version: 目标Darwin版本号
        
        返回:
            布尔值，表示是否允许加载不兼容的kext
        """
        incompatible_kexts = []
        try:
            incompatible_kexts = [
                (self.kexts[index].name, "Lilu" in self.kexts[index].requires_kexts)
                for index in selected_kexts
                if not self.utils.parse_darwin_version(self.kexts[index].min_darwin_version)
                <= self.utils.parse_darwin_version(target_darwin_version)
                <= self.utils.parse_darwin_version(self.kexts[index].max_darwin_version)
            ]
        except:
            incompatible_kexts = [
                (self.kexts[kext_data.kext_index_by_name.get(kext_name)].name, "Lilu" in self.kexts[kext_data.kext_index_by_name.get(kext_name)].requires_kexts)
                for kext_name in selected_kexts
                if not self.utils.parse_darwin_version(self.kexts[kext_data.kext_index_by_name.get(kext_name)].min_darwin_version)
                <= self.utils.parse_darwin_version(target_darwin_version)
                <= self.utils.parse_darwin_version(self.kexts[kext_data.kext_index_by_name.get(kext_name)].max_darwin_version)
            ]

        if not incompatible_kexts:
            return False
        
        while True:
            self.utils.head("Kext兼容性检查")
            print("\n与当前macOS版本不兼容的kext ({}):\n".format(target_darwin_version))
            
            for index, (kext_name, is_lilu_dependent) in enumerate(incompatible_kexts, start=1):
                print("{:2}. {:25}{}".format(index, kext_name, " - Lilu插件" if is_lilu_dependent else ""))
            
            print("\n\033[1;93m注意:\033[0m")
            print("- 使用Lilu插件时，使用\"-lilubetaall\"启动参数将强制加载它们。")
            print("- 强制加载不支持的kext可能导致系统不稳定。 \033[0;31m请谨慎操作。\033[0m")
            print("")
            
            option = self.utils.request_input("您想在不支持的macOS版本上强制加载{}吗？ (yes/No): ".format("这些kext" if len(incompatible_kexts) > 1 else "这个kext"))
            
            if option.lower() == "yes":
                return True
            elif option.lower() == "no":
                return False

    def kext_configuration_menu(self, macos_version):
        """
        显示kext配置菜单，允许用户选择和配置kext
        
        参数:
            macos_version: macOS版本号
        """
        current_category = None

        while True:
            contents = []
            contents.append("")
            contents.append("可用的kext列表:")
            for index, kext in enumerate(self.kexts, start=1):
                if kext.category != current_category:
                    current_category = kext.category
                    category_header = "分类: {}".format(current_category if current_category else "未分类")
                    contents.append(f"\n{category_header}\n" + "=" * len(category_header))
                checkbox = "[*]" if kext.checked else "[ ]"
                
                line = "{} {:2}. {:35} - {:60}".format(checkbox, index, kext.name, kext.description)
                if kext.checked:
                    line = "\033[1;32m{}\033[0m".format(line)
                elif not self.utils.parse_darwin_version(kext.min_darwin_version) <= self.utils.parse_darwin_version(macos_version) <= self.utils.parse_darwin_version(kext.max_darwin_version):
                    line = "\033[90m{}\033[0m".format(line)
                contents.append(line)
            contents.append("")
            contents.append("\033[1;93m注意:\033[0m")
            contents.append("- 灰色行表示不支持当前macOS版本的kext ({})。".format(macos_version))
            contents.append("- 当选择一个kext的插件时，整个kext将被自动选择。")
            contents.append("- 您可以通过输入用逗号分隔的索引来选择多个kext（例如：'1, 2, 3'）。")
            contents.append("")
            contents.append("B. 返回")
            contents.append("Q. 退出")
            contents.append("")
            content = "\n".join(contents)

            self.utils.adjust_window_size(content)
            self.utils.head("配置 kexts（内核扩展）", resize=False)
            print(content)
            option = self.utils.request_input("选择您的选项: ")
            if option.lower() == "b":
                return
            if option.lower() == "q":
                self.utils.exit_program()
            indices = [int(i.strip()) -1 for i in option.split(",") if i.strip().isdigit()]

            allow_unsupported_kexts = self.verify_kext_compatibility(indices, macos_version)
    
            for index in indices:
                if index >= 0 and index < len(self.kexts):
                    kext = self.kexts[index]
                    if kext.checked and not kext.required:
                        self.uncheck_kext(index)
                    else:
                        self.check_kext(index, macos_version, allow_unsupported_kexts)