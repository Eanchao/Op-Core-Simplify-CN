# 原始源代码: https://github.com/corpnewt/SSDTTime/blob/44aadf01b7fe75cb4a3eab5590e7b6c458265c6f/SSDTTime.py

from Scripts.datasets import acpi_patch_data
from Scripts.datasets import chipset_data
from Scripts.datasets import cpu_data
from Scripts.datasets import pci_data
from Scripts import smbios
from Scripts import dsdt
from Scripts import run
from Scripts import utils
import os
import binascii
import re
import tempfile
import shutil
import sys
import plistlib

class ACPIGuru:
    def __init__(self):
        self.acpi = dsdt.DSDT()
        self.smbios = smbios.SMBIOS()
        self.run = run.Run().run
        self.utils = utils.Utils()
        self.patches = acpi_patch_data.patches
        self.hardware_report = None
        self.disabled_devices = None
        self.acpi_directory = None
        self.smbios_model = None
        self.dsdt = None
        self.lpc_bus_device = None
        self.osi_strings = {
            "Windows 2000": "Windows 2000",
            "Windows XP": "Windows 2001",
            "Windows XP SP1": "Windows 2001 SP1",
            "Windows Server 2003": "Windows 2001.1",
            "Windows XP SP2": "Windows 2001 SP2",
            "Windows Server 2003 SP1": "Windows 2001.1 SP1",
            "Windows Vista": "Windows 2006",
            "Windows Vista SP1": "Windows 2006 SP1",
            "Windows Server 2008": "Windows 2006.1",
            "Windows 7, Win Server 2008 R2": "Windows 2009",
            "Windows 8, Win Server 2012": "Windows 2012",
            "Windows 8.1": "Windows 2013",
            "Windows 10": "Windows 2015",
            "Windows 10, version 1607": "Windows 2016",
            "Windows 10, version 1703": "Windows 2017",
            "Windows 10, version 1709": "Windows 2017.2",
            "Windows 10, version 1803": "Windows 2018",
            "Windows 10, version 1809": "Windows 2018.2",
            "Windows 10, version 1903": "Windows 2019",
            "Windows 10, version 2004": "Windows 2020",
            "Windows 11": "Windows 2021",
            "Windows 11, version 22H2": "Windows 2022"
        }
        self.pre_patches = (
            {
                "PrePatch":"GPP7 duplicate _PRW methods",
                "Comment" :"GPP7._PRW to XPRW to fix Gigabyte's Mistake",
                "Find"    :"3708584847500A021406535245470214065350525701085F505257",
                "Replace" :"3708584847500A0214065352454702140653505257010858505257"
            },
            {
                "PrePatch":"GPP7 duplicate UP00 devices",
                "Comment" :"GPP7.UP00 to UPXX to fix Gigabyte's Mistake",
                "Find"    :"1047052F035F53425F50434930475050375B82450455503030",
                "Replace" :"1047052F035F53425F50434930475050375B82450455505858"
            },
            {
                "PrePatch":"GPP6 duplicate _PRW methods",
                "Comment" :"GPP6._PRW to XPRW to fix ASRock's Mistake",
                "Find"    :"47505036085F4144520C04000200140F5F505257",
                "Replace" :"47505036085F4144520C04000200140F58505257"
            },
            {
                "PrePatch":"GPP1 duplicate PTXH devices",
                "Comment" :"GPP1.PTXH to XTXH to fix MSI's Mistake",
                "Find"    :"50545848085F41445200140F",
                "Replace" :"58545848085F41445200140F"
            }
        )
        self.target_irqs = [0, 2, 8, 11]
        self.illegal_names = ("XHC1", "EHC1", "EHC2", "PXSX")
        self.dsdt_patches = []

    def get_unique_name(self,name,target_folder,name_append="-Patched"):
        # 在Results文件夹中获取新的文件名，以免覆盖原始文件
        name = os.path.basename(name)
        ext  = "" if not "." in name else name.split(".")[-1]
        if ext: name = name[:-len(ext)-1]
        if name_append: name = name+str(name_append)
        check_name = ".".join((name,ext)) if ext else name
        if not os.path.exists(os.path.join(target_folder,check_name)):
            return check_name
        # 我们需要一个唯一的名称
        num = 1
        while True:
            check_name = "{}-{}".format(name,num)
            if ext: check_name += "."+ext
            if not os.path.exists(os.path.join(target_folder,check_name)):
                return check_name
            num += 1 # 增加计数器

    def get_unique_device(self, path, base_name, starting_number=0, used_names = []):
        # 追加十六进制数字，直到找到唯一设备
        while True:
            hex_num = hex(starting_number).replace("0x","").upper()
            name = base_name[:-1*len(hex_num)]+hex_num
            if not len(self.acpi.get_device_paths("."+name)) and not name in used_names:
                return (name,starting_number)
            starting_number += 1

    def sorted_nicely(self, l): 
        convert = lambda text: int(text) if text.isdigit() else text 
        alphanum_key = lambda key: [ convert(c) for c in re.split('([0-9]+)', key.lower()) ] 
        return sorted(l, key = alphanum_key)
    
    def read_acpi_tables(self, path):
        if not path:
            return
        self.utils.head("Loading ACPI Table(s)")
        print("作者: CorpNewt")
        print("")
        tables = []
        trouble_dsdt = None
        fixed = False
        temp = None
        prior_tables = self.acpi.acpi_tables # Retain in case of failure
        # Clear any existing tables so we load anew
        self.acpi.acpi_tables = {}
        if os.path.isdir(path):
            print("正在从 {} 收集有效表...\n".format(os.path.basename(path)))
            for t in self.sorted_nicely(os.listdir(path)):
                if not "Patched" in t and self.acpi.table_is_valid(path,t):
                    print(" - {}".format(t))
                    tables.append(t)
            if not tables:
                # 检查传入的目录中是否有ACPI目录
                # 这可能表明SysReport已被删除
                if os.path.isdir(os.path.join(path,"ACPI")):
                    # 使用更新后的路径重新运行此函数
                    return self.read_acpi_tables(os.path.join(path,"ACPI"))
                print(" - 未找到有效的 .aml 文件!")
                print("")
                #self.u.grab("按 [enter] 返回...")
                self.utils.request_input()
                # 恢复任何先前的表
                self.acpi.acpi_tables = prior_tables
                return
            print("")
            # 我们至少找到了一个文件 - 让我们专门查找DSDT
            # 并尝试按原样加载它。如果加载失败，我们将不得不
            # 使用临时文件夹管理所有内容
            dsdt_list = [x for x in tables if self.acpi._table_signature(path,x) == "DSDT"]
            if len(dsdt_list) > 1:
                print("传入了多个带有DSDT签名的文件:")
                for d in self.sorted_nicely(dsdt_list):
                    print(" - {}".format(d))
                print("\n一次只允许一个。请删除上述文件之一，然后重试。")
                print("")
                #self.u.grab("按 [enter] 返回...")
                self.utils.request_input()
                # 恢复任何先前的表
                self.acpi.acpi_tables = prior_tables
                return
            # 获取DSDT（如果有）
            dsdt = dsdt_list[0] if len(dsdt_list) else None
            if dsdt: # 尝试加载它，看看是否会导致问题
                print("正在反汇编 {} 以验证是否需要预补丁...".format(dsdt))
                if not self.acpi.load(os.path.join(path,dsdt))[0]:
                    trouble_dsdt = dsdt
                else:
                    print("\n反汇编成功!\n")
        elif not "Patched" in path and os.path.isfile(path):
            print("正在加载 {}...".format(os.path.basename(path)))
            if self.acpi.load(path)[0]:
                print("\n完成。")
                # 如果加载正常 - 只需返回路径
                # 到父目录
                return os.path.dirname(path)
            if not self.acpi._table_signature(path) == "DSDT":
                # 不是DSDT，我们不应用预补丁
                print("\n{} 无法反汇编!".format(os.path.basename(path)))
                print("")
                #self.u.grab("按 [enter] 返回...")
                self.utils.request_input()
                # 恢复任何先前的表
                self.acpi.acpi_tables = prior_tables
                return
            # 加载失败 - 将其设置为有问题的文件
            trouble_dsdt = os.path.basename(path)
            # 将表放入表列表，并调整
            # 路径代表父目录
            tables.append(os.path.basename(path))
            path = os.path.dirname(path)
        else:
            print("传入的文件/文件夹不存在!")
            print("")
            #self.u.grab("按 [enter] 返回...")
            self.utils.request_input()
            # Restore any prior tables
            self.acpi.acpi_tables = prior_tables
            return
        # 如果我们到了这里 - 检查是否有有问题的DSDT。
        if trouble_dsdt:
            # 我们需要将ACPI文件移动到临时文件夹
            # 然后尝试在那里打补丁DSDT
            temp = tempfile.mkdtemp()
            for table in tables:
                shutil.copy(
                    os.path.join(path,table),
                    temp
                )
            # 获取新的有问题文件的引用
            trouble_path = os.path.join(temp,trouble_dsdt)
            # 现在我们尝试打补丁
            print("正在检查可用的预补丁...")
            print("正在将 {} 加载到内存中...".format(trouble_dsdt))
            with open(trouble_path,"rb") as f:
                d = f.read()
            res = self.acpi.check_output(path)
            target_name = self.get_unique_name(trouble_dsdt,res,name_append="-Patched")
            self.dsdt_patches = []
            print("正在迭代补丁...\n")
            for p in self.pre_patches:
                if not all(x in p for x in ("PrePatch","Comment","Find","Replace")): continue
                print(" - {}".format(p["PrePatch"]))
                find = binascii.unhexlify(p["Find"])
                if d.count(find) == 1:
                    self.dsdt_patches.append(p) # 保留补丁
                    repl = binascii.unhexlify(p["Replace"])
                    print(" --> 已找到 - 正在应用...")
                    d = d.replace(find,repl) # 在内存中替换
                    with open(trouble_path,"wb") as f:
                        f.write(d) # 写入更新后的文件
                    # 再次尝试加载
                    if self.acpi.load(trouble_path)[0]:
                        fixed = True
                        # 成功加载 - 让我们写入补丁
                        print("\n反汇编成功!\n")
                        #self.make_plist(None, None, patches)
                        # Save to the local file
                        #with open(os.path.join(res,target_name),"wb") as f:
                        #    f.write(d)
                        #print("\n!! Patches applied to modified file in Results folder:\n   {}".format(target_name))
                        #self.patch_warn()
                        break
            if not fixed:
                print("\n{} 无法反汇编!".format(trouble_dsdt))
                print("")
                #self.u.grab("按 [enter] 返回...")
                self.utils.request_input()
                if temp:
                    shutil.rmtree(temp,ignore_errors=True)
                # 恢复任何先前的表
                self.acpi.acpi_tables = prior_tables
                return
        # 让我们加载剩余的表
        if len(tables) > 1:
            print("正在加载 {} 中的有效表...".format(path))
        loaded_tables,failed = self.acpi.load(temp or path)
        if not loaded_tables or failed:
            print("\n无法加载 {} 中的表{}\n".format(
                os.path.dirname(path) if os.path.isfile(path) else path,
                ":" if failed else ""
            ))
            for t in self.sorted_nicely(failed):
                print(" - {}".format(t))
            # 恢复任何先前的表
            if not loaded_tables:
                self.acpi.acpi_tables = prior_tables
        else:
            if len(tables) > 1:
                print("") # 为了可读性换行
            print("完成。")
        # 如果我们必须打补丁DSDT，或者不是所有表都加载了，
        # 确保我们得到用户的交互才能继续
        if trouble_dsdt or not loaded_tables or failed:
            print("")
            #self.u.grab("按 [enter] 返回...")
            #self.utils.request_input()
        if temp:
            shutil.rmtree(temp,ignore_errors=True)
        self.dsdt = self.acpi.get_dsdt_or_only()
        return path

    def _ensure_dsdt(self, allow_any=False):
        # 辅助函数，用于检查何时有有效表的条件
        return self.dsdt and ((allow_any and self.acpi.acpi_tables) or (not allow_any and self.acpi.get_dsdt_or_only()))

    def ensure_dsdt(self, allow_any=False):
        if self._ensure_dsdt(allow_any=allow_any):
            # 已经有了
            return True
        # 需要提示
        self.select_acpi_tables()
        self.dsdt = self.acpi.get_dsdt_or_only()
        if self._ensure_dsdt(allow_any=allow_any):
            return True
        return False

    def get_sta_var(self,var="STAS",device=None,dev_hid="ACPI000E",dev_name="AWAC",log_locate=False,table=None):
        # 辅助函数，用于检查设备，检查（并确认）_STA方法，
        # 并在_STA作用域中查找特定变量
        #
        # 返回包含设备信息的字典 - 只有"valid"参数是
        # 有保证的。
        has_var = False
        patches = []
        root = None
        if device:
            dev_list = self.acpi.get_device_paths(device,table=table)
            if not len(dev_list):
                if log_locate: print(" - 无法定位 {}".format(device))
                return {"value":False}
        else:
            if log_locate: print("正在定位 {} ({}) 设备...".format(dev_hid,dev_name))
            dev_list = self.acpi.get_device_paths_with_hid(dev_hid,table=table)
            if not len(dev_list):
                if log_locate: print(" - 无法定位任何 {} 设备".format(dev_hid))
                return {"valid":False}
        dev = dev_list[0]
        if log_locate: print(" - 已找到 {}".format(dev[0]))
        root = dev[0].split(".")[0]
        #print(" --> Verifying _STA...")
        # Check Method first - then Name
        sta_type = "MethodObj"
        sta  = self.acpi.get_method_paths(dev[0]+"._STA",table=table)
        xsta = self.acpi.get_method_paths(dev[0]+".XSTA",table=table)
        if not sta and not xsta:
            # Check for names
            sta_type = "IntObj"
            sta = self.acpi.get_name_paths(dev[0]+"._STA",table=table)
            xsta = self.acpi.get_name_paths(dev[0]+".XSTA",table=table)
        if xsta and not sta:
            #print(" --> _STA 已重命名为 XSTA！跳过其他检查...")
            #print("     请为该设备禁用 _STA 到 XSTA 的重命名，重新启动，然后重试。")
            #print("")
            return {"valid":False,"break":True,"device":dev,"dev_name":dev_name,"dev_hid":dev_hid,"sta_type":sta_type}
        if sta:
            if var:
                scope = "\n".join(self.acpi.get_scope(sta[0][1],strip_comments=True,table=table))
                has_var = var in scope
                #print(" --> {}{} 变量".format("有" if has_var else "没有",var))
        #else:
            #print(" --> 未找到 _STA 方法/名称")
        # 让我们找出是否需要为 _STA -> XSTA 生成唯一的补丁
        if sta and not has_var:
            #print(" --> 正在生成 _STA 到 XSTA 的重命名")
            sta_index = self.acpi.find_next_hex(sta[0][1],table=table)[1]
            #print(" ----> 在索引 {} 处找到".format(sta_index))
            sta_hex  = "5F535441" # _STA
            xsta_hex = "58535441" # XSTA
            padl,padr = self.acpi.get_shortest_unique_pad(sta_hex,sta_index,table=table)
            patches.append({"Comment":"{} _STA 到 XSTA 重命名".format(dev_name),"Find":padl+sta_hex+padr,"Replace":padl+xsta_hex+padr})
        return {"valid":True,"has_var":has_var,"sta":sta,"patches":patches,"device":dev,"dev_name":dev_name,"dev_hid":dev_hid,"root":root,"sta_type":sta_type}

    def get_lpc_name(self,log=False,skip_ec=False,skip_common_names=False):
        # Intel 设备似乎使用 _ADR, 0x001F0000
        # AMD 设备似乎使用 _ADR, 0x00140003
        if log: print("正在定位 LPC(B)/SBRG...")
        for table_name in self.sorted_nicely(list(self.acpi.acpi_tables)):
            table = self.acpi.acpi_tables[table_name]
            # 如果找到，LPCB 设备将始终是 PNP0C09 设备的父设备
            if not skip_ec:
                ec_list = self.acpi.get_device_paths_with_hid("PNP0C09",table=table)
                if len(ec_list):
                    lpc_name = ".".join(ec_list[0][0].split(".")[:-1])
                    if log: print(" - 在 {} 中找到 {}".format(table_name,lpc_name))
                    return lpc_name
            # 如果尚未找到，可能尝试使用常见名称
            if not skip_common_names:
                for x in ("LPCB", "LPC0", "LPC", "SBRG", "PX40"):
                    try:
                        lpc_name = self.acpi.get_device_paths(x,table=table)[0][0]
                        if log: print(" - 在 {} 中找到 {}".format(table_name,lpc_name))
                        return lpc_name
                    except: pass
            # 最后按地址检查 - 一些 Intel 表在 0x00140003 处有设备
            paths = self.acpi.get_path_of_type(obj_type="Name",obj="_ADR",table=table)
            for path in paths:
                adr = self.get_address_from_line(path[1],table=table)
                if adr in (0x001F0000, 0x00140003):
                    # 获取路径减去 ._ADR
                    lpc_name = path[0][:-5]
                    # 确保 LPCB 设备没有 _HID
                    lpc_hid = lpc_name+"._HID"
                    if any(x[0]==lpc_hid for x in table.get("paths",[])):
                        continue
                    if log: print(" - 在 {} 中找到 {}".format(table_name,lpc_name))
                    return lpc_name
        if log:
            print(" - 无法定位 LPC(B)！中止！")
            print("")
        return None # 未找到

    def get_address_from_line(self, line, split_by="_ADR, ", table=None):
        if table is None:
            table = self.acpi.get_dsdt_or_only()
        try:
            return int(table["lines"][line].split(split_by)[1].split(")")[0].replace("Zero","0x0").replace("One","0x1"),16)
        except:
            return None

    def enable_cpu_power_management(self):
        #if not self.ensure_dsdt(allow_any=True):
        #    return
        #self.u.head("Plugin Type")
        #print("")
        #print("正在确定CPU命名方案...")
        for table_name in self.sorted_nicely(list(self.acpi.acpi_tables)):
            ssdt_name = "SSDT-PLUG"
            table = self.acpi.acpi_tables[table_name]
            if not table.get("signature") in (b"DSDT",b"SSDT"):
                continue # 我们不检查数据表格
            #print(" 正在检查 {}...".format(table_name))
            try: cpu_name = self.acpi.get_processor_paths(table=table)[0][0]
            except: cpu_name = None
            if cpu_name:
                #print(" - 已找到处理器: {}".format(cpu_name))
                #oc = {"Comment":"在第一个Processor对象上设置plugin-type为1","Enabled":True,"Path":ssdt_name+".aml"}
                #print("正在创建SSDT-PLUG...")
                ssdt = """//
// 基于https://github.com/acidanthera/OpenCorePkg/blob/master/Docs/AcpiSamples/SSDT-PLUG.dsl中的示例
//
DefinitionBlock ("", "SSDT", 2, "ZPSS", "CpuPlug", 0x00003000)
{
    External ([[CPUName]], ProcessorObj)
    Scope ([[CPUName]])
    {
        If (_OSI ("Darwin")) {
            Method (_DSM, 4, NotSerialized)  // _DSM: 设备特定方法
            {
                If (LNot (Arg2))
                {
                    Return (Buffer (One)
                    {
                        0x03
                    })
                }
                Return (Package (0x02)
                {
                    "plugin-type", 
                    One
                })
            }
        }
    }
}""".replace("[[CPUName]]",cpu_name)
            else:
                ssdt_name += "-ALT"
                #print(" - 未找到Processor对象...")
                procs = self.acpi.get_device_paths_with_hid(hid="ACPI0007",table=table)
                if not procs:
                    #print(" - 未找到ACPI0007设备...")
                    continue
                #print(" - 已定位 {:,} 个ACPI0007设备{}".format(
                #    len(procs), "" if len(procs)==1 else "s"
                #))
                parent = procs[0][0].split(".")[0]
                #print(" - 在 {} 获取父节点，正在迭代...".format(parent))
                proc_list = []
                for proc in procs:
                    #print(" - 正在检查 {}...".format(proc[0].split(".")[-1]))
                    uid = self.acpi.get_path_of_type(obj_type="Name",obj=proc[0]+"._UID",table=table)
                    if not uid:
                        #print(" --> 未找到! 跳过...")
                        continue
                    # 让我们获取实际的_UID值
                    try:
                        _uid = table["lines"][uid[0][1]].split("_UID, ")[1].split(")")[0]
                        #print(" --> _UID: {}".format(_uid))
                        proc_list.append((proc[0],_uid))
                    except:
                        pass
                        #print(" --> 未找到! 跳过...")
                if not proc_list:
                    continue
                #print("正在迭代 {:,} 个有效处理器设备{}...".format(len(proc_list),"" if len(proc_list)==1 else "s"))
                ssdt = """//
// 基于https://github.com/acidanthera/OpenCorePkg/blob/master/Docs/AcpiSamples/Source/SSDT-PLUG-ALT.dsl中的示例
//
DefinitionBlock ("", "SSDT", 2, "ZPSS", "CpuPlugA", 0x00003000)
{
    External ([[parent]], DeviceObj)

    Scope ([[parent]])
    {
""".replace("[[parent]]",parent)
                # Ensure our name scheme won't conflict
                schemes = ("C000","CP00","P000","PR00","CX00","PX00")
                # Walk the processor objects, and add them to the SSDT
                for i,proc_uid in enumerate(proc_list):
                    proc,uid = proc_uid
                    adr = hex(i)[2:].upper()
                    name = None
                    for s in schemes:
                        name_check = s[:-len(adr)]+adr
                        check_path = "{}.{}".format(parent,name_check)
                        if self.acpi.get_path_of_type(obj_type="Device",obj=check_path,table=table):
                            continue # 已定义 - 跳过
                        # 如果我们到了这里 - 我们找到了一个未使用的名称
                        name = name_check
                        break
                    if not name:
                        #print(" - 无法找到可用的命名方案! 中止。")
                        #print("")
                        #self.u.grab("按 [enter] 返回主菜单...")
                        return
                    ssdt+="""
        Processor ([[name]], [[uid]], 0x00000510, 0x06)
        {
            // [[proc]]
            Name (_HID, "ACPI0007" /* 处理器设备 */)  // _HID: 硬件ID
            Name (_UID, [[uid]])
            Method (_STA, 0, NotSerialized)  // _STA: 状态
            {
                If (_OSI ("Darwin"))
                {
                    Return (0x0F)
                }
                Else
                {
                    Return (Zero)
                }
            }""".replace("[[name]]",name).replace("[[uid]]",uid).replace("[[proc]]",proc)
                    if i == 0: # 获得了第一个，同时添加plugin-type
                        ssdt += """
            Method (_DSM, 4, NotSerialized)
            {
                If (LNot (Arg2)) {
                    Return (Buffer (One) { 0x03 })
                }

                Return (Package (0x02)
                {
                    "plugin-type",
                    One
                })
            }"""
                # 关闭SSDT
                    ssdt += """
        }"""
                ssdt += """
    }
}"""
            #    oc = {"Comment":"将现代CPU设备重新定义为传统Processor对象并在第一个对象上设置plugin-type为1","Enabled":True,"Path":ssdt_name+".aml"}
            #self.make_plist(oc, ssdt_name+".aml", ())
            #self.write_ssdt(ssdt_name,ssdt)
            #print("")
            #print("完成。")
            #self.patch_warn()
            #self.u.grab("按 [enter] 返回...")
            #return
        # 如果我们到了这里 - 我们到达了末尾
        #print("未找到有效的处理器设备!")
        #print("")
        #self.u.grab("按 [enter] 返回...")
        #return

            return {
                "Add": [
                    {
                        "Comment": ssdt_name + ".aml",
                        "Enabled": self.write_ssdt(ssdt_name, ssdt),
                        "Path": ssdt_name + ".aml"
                    }
                ]
            }

    def list_irqs(self):
        # 遍历DSDT，跟踪当前设备并保存找到的IRQNoFlags
        devices = {}
        current_device = None
        current_hid = None
        irq = False
        last_irq = False
        irq_index = 0
        for index,line in enumerate(self.dsdt["lines"]):
            if self.acpi.is_hex(line):
                # Skip all hex lines
                continue
            if irq:
                # Get the values
                num = line.split("{")[1].split("}")[0].replace(" ","")
                num = "#" if not len(num) else num
                if current_device in devices:
                    if last_irq: # In a row
                        devices[current_device]["irq"] += ":"+num
                    else: # Skipped at least one line
                        irq_index = self.acpi.find_next_hex(index)[1]
                        devices[current_device]["irq"] += "-"+str(irq_index)+"|"+num
                else:
                    irq_index = self.acpi.find_next_hex(index)[1]
                    devices[current_device] = {"irq":str(irq_index)+"|"+num}
                irq = False
                last_irq = True
            elif "Device (" in line:
                # Check if we retain the _HID here
                if current_device and current_device in devices and current_hid:
                    # Save it
                    devices[current_device]["hid"] = current_hid
                last_irq = False
                current_hid = None
                try: current_device = line.split("(")[1].split(")")[0]
                except:
                    current_device = None
                    continue
            elif "_HID, " in line and current_device:
                try: current_hid = line.split('"')[1]
                except: pass
            elif "IRQNoFlags" in line and current_device:
                # Next line has our interrupts
                irq = True
            # Check if just a filler line
            elif len(line.replace("{","").replace("}","").replace("(","").replace(")","").replace(" ","").split("//")[0]):
                # Reset last IRQ as it's not in a row
                last_irq = False
        # Retain the final _HID if needed
        if current_device and current_device in devices and current_hid:
            devices[current_device]["hid"] = current_hid
        return devices

    def get_irq_choice(self, irqs):
        names_and_hids = [
            "PIC",
            "IPIC",
            "TMR",
            "TIMR",
            "RTC",
            "RTC0",
            "RTC1",
            "PNPC0000",
            "PNP0100",
            "PNP0B00"
        ]
        defaults = [x for x in irqs if x.upper() in names_and_hids or irqs[x].get("hid","").upper() in names_and_hids]
        d = {}

        for x in defaults:
            d[x] = self.target_irqs
        return d

    def get_hex_from_irqs(self, irq, rem_irq = None):
        # 我们需要搜索几种不同的类型：
        #
        # 22 XX XX 22 XX XX 22 XX XX（不同行上的多个条目）
        # 22 XX XX（同一括号内的多个总和 - {0,8,11}）
        # 22 XX XX（单个IRQNoFlags条目）
        # 
        # 可以以79 [00]（方法结束）、86 09（方法中间）或47 01（未知）结尾
        lines = []
        remd  = []
        for a in irq.split("-"):
            index,i = a.split("|") # Get the index
            index = int(index)
            find = self.get_int_for_line(i)
            repl = [0]*len(find)
            # Now we need to verify if we're patching *all* IRQs, or just some specifics
            if rem_irq:
                repl = [x for x in find]
                matched = []
                for x in rem_irq:
                    # Get the int
                    rem = self.convert_irq_to_int(x)
                    repl1 = [y&(rem^0xFFFF) if y >= rem else y for y in repl]
                    if repl1 != repl:
                        # Changes were made
                        remd.append(x)
                    repl = [y for y in repl1]
            # Get the hex
            d = {
                "irq":i,
                "find": "".join(["22"+self.acpi.get_hex_from_int(x) for x in find]),
                "repl": "".join(["22"+self.acpi.get_hex_from_int(x) for x in repl]),
                "remd": remd,
                "index": index
                }
            d["changed"] = not (d["find"]==d["repl"])
            lines.append(d)
        return lines
    
    def get_int_for_line(self, irq):
        irq_list = []
        for i in irq.split(":"):
            irq_list.append(self.same_line_irq(i))
        return irq_list

    def convert_irq_to_int(self, irq):
        b = "0"*(16-irq)+"1"+"0"*(irq)
        return int(b,2)

    def same_line_irq(self, irq):
        # 我们将IRQ值相加并返回整数
        total = 0
        for i in irq.split(","):
            if i == "#":
                continue # 空值
            try: i=int(i)
            except: continue # 不是整数
            if i > 15 or i < 0:
                continue # Out of range
            total = total | self.convert_irq_to_int(i)
        return total
    
    def fix_irq_conflicts(self):
        hpets = self.acpi.get_device_paths_with_hid("PNP0103")
        hpet_fake = not hpets
        hpet_sta = False
        sta = None
        patches = []
        if hpets:
            name = hpets[0][0]
            
            sta = self.get_sta_var(var=None,dev_hid="PNP0103",dev_name="HPET",log_locate=False)
            if sta.get("patches"):
                hpet_sta = True
                patches.extend(sta.get("patches",[]))

            hpet = self.acpi.get_method_paths(name+"._CRS") or self.acpi.get_name_paths(name+"._CRS")
            if not hpet:
                return

            crs_index = self.acpi.find_next_hex(hpet[0][1])[1]

            mem_base = mem_length = primed = None
            for line in self.acpi.get_scope(hpets[0][1],strip_comments=True):
                if "Memory32Fixed (" in line:
                    primed = True
                    continue
                if not primed:
                    continue
                elif ")" in line: # 到达作用域末尾
                    break
                # 我们已准备好，且不在末尾 - 让我们尝试获取基址和长度
                try:
                    val = line.strip().split(",")[0].replace("Zero","0x0").replace("One","0x1")
                    check = int(val,16)
                except:
                    break
                # 按顺序设置它们
                if mem_base is None:
                    mem_base = val
                else:
                    mem_length = val
                    break # 获取两个值后离开
            # 检查是否找到了值
            got_mem = mem_base and mem_length
            if not got_mem:
                mem_base = "0xFED00000"
                mem_length = "0x00000400"
            crs  = "5F435253"
            xcrs = "58435253"
            padl,padr = self.acpi.get_shortest_unique_pad(crs, crs_index)
            patches.append({"Comment":"{} _CRS 重命名为 XCRS".format(name.split(".")[-1].lstrip("\\")),"Find":padl+crs+padr,"Replace":padl+xcrs+padr})
        else:
            ec_list = self.acpi.get_device_paths_with_hid("PNP0C09")
            name = None
            if len(ec_list):
                name = ".".join(ec_list[0][0].split(".")[:-1])
            if name == None:
                for x in ("LPCB", "LPC0", "LPC", "SBRG", "PX40"):
                    try:
                        name = self.acpi.get_device_paths(x)[0][0]
                        break
                    except: pass
            if not name:
                return
            
        devs = self.list_irqs()
        target_irqs = self.get_irq_choice(devs)
        if target_irqs is None: return # 退出，返回主菜单
        # 让我们逐步应用补丁
        saved_dsdt = self.dsdt.get("raw")
        unique_patches  = {}
        generic_patches = []
        for dev in devs:
            if not dev in target_irqs:
                continue
            irq_patches = self.get_hex_from_irqs(devs[dev]["irq"],target_irqs[dev])
            i = [x for x in irq_patches if x["changed"]]
            for a,t in enumerate(i):
                if not t["changed"]:
                    # 没有补丁 - 跳过
                    continue
                # 尝试我们的结尾 - 7900, 8609 和 4701 - 还允许最多8个字符的填充（感谢MSI）
                matches = re.findall("("+t["find"]+"(.{0,8})(7900|4701|8609))",self.acpi.get_hex_starting_at(t["index"])[0])
                if not len(matches):
                    continue
                if len(matches) > 1:
                    # 找到太多匹配项！
                    # 将它们全部添加为查找/替换条目
                    for x in matches:
                        generic_patches.append({
                            "remd":",".join([str(y) for y in set(t["remd"])]),
                            "orig":t["find"],
                            "find":t["find"]+"".join(x[1:]),
                            "repl":t["repl"]+"".join(x[1:])
                        })
                    continue
                ending = "".join(matches[0][1:])
                padl,padr = self.acpi.get_shortest_unique_pad(t["find"]+ending, t["index"])
                t_patch = padl+t["find"]+ending+padr
                r_patch = padl+t["repl"]+ending+padr
                if not dev in unique_patches:
                    unique_patches[dev] = []
                unique_patches[dev].append({
                    "dev":dev,
                    "remd":",".join([str(y) for y in set(t["remd"])]),
                    "orig":t["find"],
                    "find":t_patch,
                    "repl":r_patch
                })
        # 遍历唯一补丁（如果有）
        if len(unique_patches):
            for x in unique_patches:
                for i,p in enumerate(unique_patches[x]):
                    patch_name = "{} IRQ {} 补丁".format(x, p["remd"])
                    if len(unique_patches[x]) > 1:
                        patch_name += " - {}/{}个".format(i+1, len(unique_patches[x]))
                    patches.append({
                        "Comment": patch_name,
                        "Find": p["find"],
                        "Replace": p["repl"]
                    })
        # 遍历通用补丁（如果有）
        if len(generic_patches):
            generic_set = [] # 确保我们不重复查找值
            for x in generic_patches:
                if x in generic_set:
                    continue
                generic_set.append(x)

            for i,x in enumerate(generic_set):
                patch_name = "通用 IRQ 补丁 {}/{}个 - {} - {}".format(i+1,len(generic_set),x["remd"],x["orig"])
                patches.append({
                    "Comment": patch_name,
                    "Find": x["find"],
                    "Replace": x["repl"],
                    "Enabled": False
                })
        # 恢复内存中的原始DSDT
        self.dsdt["raw"] = saved_dsdt

        ssdt_name = "SSDT-HPET"

        if hpet_fake:
            ssdt_content = """// 虚拟HPET设备
//
DefinitionBlock ("", "SSDT", 2, "ZPSS", "HPET", 0x00000000)
{
    External ([[name]], DeviceObj)

    Scope ([[name]])
    {
        Device (HPET)
        {
            Name (_HID, EisaId ("PNP0103") /* HPET System Timer */)  // _HID: Hardware ID
            Name (_CID, EisaId ("PNP0C01") /* System Board */)  // _CID: Compatible ID
            Method (_STA, 0, NotSerialized)  // _STA: 状态
            {
                If (_OSI ("Darwin"))
                {
                    Return (0x0F)
                }
                Else
                {
                    Return (Zero)
                }
            }
            Name (_CRS, ResourceTemplate ()  // _CRS: Current Resource Settings
            {
                IRQNoFlags ()
                    {0,8,11}
                Memory32Fixed (ReadWrite,
                    0xFED00000,         // Address Base
                    0x00000400,         // Address Length
                    )
            })
        }
    }
}""".replace("[[name]]",name)
        else:
            ssdt_content = """//
// 来自Goldfish64的补充HPET _CRS
// 需要将HPET的_CRS重命名为XCRS
//
DefinitionBlock ("", "SSDT", 2, "ZPSS", "HPET", 0x00000000)
{
    External ([[name]], DeviceObj)
    External ([[name]].XCRS, [[type]])

    Scope ([[name]])
    {
        Name (BUFX, ResourceTemplate ()
        {
            IRQNoFlags ()
                {0,8,11}
            Memory32Fixed (ReadWrite,
                // [[mem]]
                [[mem_base]],         // Address Base
                [[mem_length]],         // Address Length
            )
        })
        Method (_CRS, 0, Serialized)  // _CRS: Current Resource Settings
        {
            // 如果启动macOS或XCRS方法因某些原因不再存在，则返回我们的缓冲区
            If (LOr (_OSI ("Darwin"), LNot(CondRefOf ([[name]].XCRS))))
            {
                Return (BUFX)
            }
            // 不是macOS且XCRS存在 - 返回其结果
            Return ([[name]].XCRS[[method]])
        }""" \
    .replace("[[name]]",name) \
    .replace("[[type]]","MethodObj" if hpet[0][-1] == "Method" else "BuffObj") \
    .replace("[[mem]]","Base/Length pulled from DSDT" if got_mem else "Default Base/Length - verify with your DSDT!") \
    .replace("[[mem_base]]",mem_base) \
    .replace("[[mem_length]]",mem_length) \
    .replace("[[method]]"," ()" if hpet[0][-1]=="Method" else "")
            if hpet_sta:
                # Inject our external reference to the renamed XSTA method
                ssdt_parts = []
                external = False
                for line in ssdt_content.split("\n"):
                    if "External (" in line: external = True
                    elif external:
                        ssdt_parts.append("    External ({}.XSTA, {})".format(name,sta["sta_type"]))
                        external = False
                    ssdt_parts.append(line)
                ssdt_content = "\n".join(ssdt_parts)
                # Add our method
                ssdt_content += """
        Method (_STA, 0, NotSerialized)  // _STA: 状态
        {
            // 如果启动macOS或XSTA方法因某些原因不再存在，则返回0x0F
            If (LOr (_OSI ("Darwin"), LNot (CondRefOf ([[name]].XSTA))))
            {
                Return (0x0F)
            }
            // 不是macOS且XSTA存在 - 返回其结果
            Return ([[name]].XSTA[[called]])
        }""".replace("[[name]]",name).replace("[[called]]"," ()" if sta["sta_type"]=="MethodObj" else "")
            ssdt_content += """
    }
}"""

        return {
            "Add": [
                {
                    "Comment": ssdt_name + ".aml",
                    "Enabled": self.write_ssdt(ssdt_name, ssdt_content),
                    "Path": ssdt_name + ".aml"
                }
            ],
            "Patch": patches
        }

    def fix_system_clock_awac(self):
        #if not self.ensure_dsdt():
        #    return
        #self.u.head("SSDT RTCAWAC")
        #print("")
        rtc_range_needed = False
        rtc_crs_type = None
        crs_lines = []
        lpc_name = None
        awac_dict = self.get_sta_var(var="STAS",dev_hid="ACPI000E",dev_name="AWAC")
        rtc_dict = self.get_sta_var(var="STAS",dev_hid="PNP0B00",dev_name="RTC")
        # 到目前为止 - 我们应该已经有了AWAC和RTC设备的所有信息
        # 让我们看看是否需要虚拟RTC设备 - 然后构建SSDT.
        if not rtc_dict.get("valid"):
            #print(" - 需要虚拟RTC设备!")
            lpc_name = self.get_lpc_name()
            if lpc_name is None:
                #self.u.grab("按[回车]返回主菜单...")
                return
        else:
            # 让我们检查RTC设备是否有_CRS变量 - 如果有，让我们查找任何跳过的范围
            #print(" --> 正在检查_CRS...")
            rtc_crs = self.acpi.get_method_paths(rtc_dict["device"][0]+"._CRS") or self.acpi.get_name_paths(rtc_dict["device"][0]+"._CRS")
            if rtc_crs:
                #print(" ----> {}".format(rtc_crs[0][0]))
                rtc_crs_type = "MethodObj" if rtc_crs[0][-1] == "Method" else "BuffObj"
                # 只有当它是buffobj时才检查范围
                if rtc_crs_type.lower() == "buffobj":
                    #print(" --> _CRS是一个缓冲区 - 正在检查RTC范围...")
                    last_adr = last_len = last_ind = None
                    crs_scope = self.acpi.get_scope(rtc_crs[0][1])
                    # 让我们尝试清理scope - 它通常是一团糟
                    pad_len = len(crs_scope[0])-len(crs_scope[0].lstrip())
                    pad = crs_scope[0][:pad_len]
                    fixed_scope = []
                    for line in crs_scope:
                        if line.startswith(pad): # 得到完整行 - 去掉缩进并保存
                            fixed_scope.append(line[pad_len:])
                        else: # 可能是前一行的一部分
                            fixed_scope[-1] = fixed_scope[-1]+line
                    for i,line in enumerate(fixed_scope):
                        if "Name (_CRS, " in line:
                            # 将_CRS重命名为BUFX供以后使用 - 并去掉任何注释以避免混淆
                            line = line.replace("Name (_CRS, ","Name (BUFX, ").split("  //")[0]
                        if "IO (Decode16," in line:
                            # 我们找到了开始 - 获取下一行和第4行
                            try:
                                curr_adr = int(fixed_scope[i+1].strip().split(",")[0],16)
                                curr_len = int(fixed_scope[i+4].strip().split(",")[0],16)
                                curr_ind = i+4 # 保存我们可能需要填充的值
                            except: # 坏值? 退出...
                                #print(" ----> 无法收集值 - 无法验证RTC范围.")
                                rtc_range_needed = False
                                break
                            if last_adr is not None: # 比较我们的范围值
                                adjust = curr_adr - (last_adr + last_len)
                                if adjust: # 我们需要将前一个长度增加adjust值
                                    rtc_range_needed = True
                                    #print(" ----> 正在调整IO范围 {} 长度到 {}".format(self.hexy(last_adr,pad_to=4),self.hexy(last_len+adjust,pad_to=2)))
                                    try:
                                        hex_find,hex_repl = self.hexy(last_len,pad_to=2),self.hexy(last_len+adjust,pad_to=2)
                                        crs_lines[last_ind] = crs_lines[last_ind].replace(hex_find,hex_repl)
                                    except:
                                        #print(" ----> 无法调整值 - 无法验证RTC范围.")
                                        rtc_range_needed = False
                                        break
                            # 保存我们的最后值
                            last_adr,last_len,last_ind = curr_adr,curr_len,curr_ind
                        crs_lines.append(line)
                if rtc_range_needed: # 我们需要生成_CRS -> XCRS的重命名
                    #print(" --> 正在生成_CRS到XCRS的重命名...")
                    crs_index = self.acpi.find_next_hex(rtc_crs[0][1])[1]
                    #print(" ----> 在索引 {} 处找到".format(crs_index))
                    crs_hex  = "5F435253" # _CRS
                    xcrs_hex = "58435253" # XCRS
                    padl,padr = self.acpi.get_shortest_unique_pad(crs_hex, crs_index)
                    patches = rtc_dict.get("patches",[])
                    patches.append({"Comment":"{} _CRS到XCRS的重命名".format(rtc_dict["dev_name"]),"Find":padl+crs_hex+padr,"Replace":padl+xcrs_hex+padr})
                    rtc_dict["patches"] = patches
                    rtc_dict["crs"] = True
            #else:
            #    print(" ----> 未找到")
        # 让我们看看是否需要SSDT
        # 如果AWAC不存在则不需要；RTC存在，没有STAS变量，没有_STA方法，也不需要范围修复
        if not awac_dict.get("valid") and rtc_dict.get("valid") and not rtc_dict.get("has_var") and not rtc_dict.get("sta") and not rtc_range_needed:
            #print("")
            #print("已找到并验证有效的PNP0B00（RTC）设备，未找到ACPI000E（AWAC）设备。")
            #print("不需要补丁或SSDT。")
            #print("")
            #self.u.grab("按[回车]返回主菜单...")
            return
        suffix  = []
        for x in (awac_dict,rtc_dict):
            if not x.get("valid"): continue
            val = ""
            if x.get("sta") and not x.get("has_var"):
                val = "{} _STA to XSTA".format(x["dev_name"])
            if x.get("crs"):
                val += "{} _CRS to XCRS".format(" and " if val else x["dev_name"])
            if val: suffix.append(val)
        #if suffix:
        #    comment += " - Requires {} Rename".format(", ".join(suffix))
        # 此时 - 我们需要执行以下操作:
        # 1. 如有需要，更改 STAS
        # 2. 使用 _OSI 设置 _STA，并在需要时调用 XSTA
        # 3. 如有需要，模拟 RTC
        #oc = {"Comment":comment,"Enabled":True,"Path":"SSDT-RTCAWAC.aml"}
        #self.make_plist(oc, "SSDT-RTCAWAC.aml", awac_dict.get("patches",[])+rtc_dict.get("patches",[]), replace=True)
        #print("Creating SSDT-RTCAWAC...")
        ssdt_name = "SSDT-RTCAWAC"
        ssdt = """//
// 原始来源来自 Acidanthera:
//  - https://github.com/acidanthera/OpenCorePkg/blob/master/Docs/AcpiSamples/SSDT-AWAC.dsl
//  - https://github.com/acidanthera/OpenCorePkg/blob/master/Docs/AcpiSamples/SSDT-RTC0.dsl
//
// 使用 ZPSS 名称来表示此文件的创建位置，用于故障排除。
//
DefinitionBlock ("", "SSDT", 2, "ZPSS", "RTCAWAC", 0x00000000)
{
"""
        if any(x.get("has_var") for x in (awac_dict,rtc_dict)):
            ssdt += """    External (STAS, IntObj)
    Scope (\\)
    {
        Method (_INI, 0, NotSerialized)  // _INI: Initialize
        {
            If (_OSI ("Darwin"))
            {
                Store (One, STAS)
            }
        }
    }
"""
        for x in (awac_dict,rtc_dict):
            if not x.get("valid") or x.get("has_var") or not x.get("device"): continue
            # Device was found, and it doesn't have the STAS var - check if we
            # have an _STA (which would be renamed)
            macos,original = ("Zero","0x0F") if x.get("dev_hid") == "ACPI000E" else ("0x0F","Zero")
            if x.get("sta"):
                ssdt += """    External ([[DevPath]], DeviceObj)
    External ([[DevPath]].XSTA, [[sta_type]])
    Scope ([[DevPath]])
    {
        Name (ZSTA, [[Original]])
        Method (_STA, 0, NotSerialized)  // _STA: 状态
        {
            If (_OSI ("Darwin"))
            {
                Return ([[macOS]])
            }
            // Default to [[Original]] - but return the result of the renamed XSTA if possible
            If (CondRefOf ([[DevPath]].XSTA))
            {
                Store ([[DevPath]].XSTA[[called]], ZSTA)
            }
            Return (ZSTA)
        }
    }
""".replace("[[DevPath]]",x["device"][0]).replace("[[Original]]",original).replace("[[macOS]]",macos).replace("[[sta_type]]",x["sta_type"]).replace("[[called]]"," ()" if x["sta_type"]=="MethodObj" else "")
            elif x.get("dev_hid") == "ACPI000E":
                # AWAC device with no STAS, and no _STA - let's just add one
                ssdt += """    External ([[DevPath]], DeviceObj)
    Scope ([[DevPath]])
    {
        Method (_STA, 0, NotSerialized)  // _STA: 状态
        {
            If (_OSI ("Darwin"))
            {
                Return (Zero)
            }
            Else
            {
                Return (0x0F)
            }
        }
    }
""".replace("[[DevPath]]",x["device"][0])
        # Check if we need to setup an RTC range correction
        if rtc_range_needed and rtc_crs_type.lower() == "buffobj" and crs_lines and rtc_dict.get("valid"):
            ssdt += """    External ([[DevPath]], DeviceObj)
    External ([[DevPath]].XCRS, [[type]])
    Scope ([[DevPath]])
    {
        // 从 DSDT 中提取并调整并重命名的 _CRS 缓冲区，已修正范围
[[NewCRS]]
        // 调整后的 _CRS 和重命名缓冲区的结束

        // 创建一个新的 _CRS 方法，返回重命名后的 XCRS 的结果
        Method (_CRS, 0, Serialized)  // _CRS: 当前资源设置
        {
            If (LOr (_OSI ("Darwin"), LNot (CondRefOf ([[DevPath]].XCRS))))
            {
                // 如果启动macOS或XCRS方法因某些原因不再存在，则返回我们的缓冲区
                Return (BUFX)
            }
            // 不是macOS且XCRS存在 - 返回其结果
            Return ([[DevPath]].XCRS[[method]])
        }
    }
""".replace("[[DevPath]]",rtc_dict["device"][0]) \
    .replace("[[type]]",rtc_crs_type) \
    .replace("[[method]]"," ()" if rtc_crs_type == "Method" else "") \
    .replace("[[NewCRS]]","\n".join([(" "*8)+x for x in crs_lines]))
        # 检查我们是否根本没有RTC设备
        if not rtc_dict.get("valid") and lpc_name:
            ssdt += """    External ([[LPCName]], DeviceObj)    // (from opcode)
    Scope ([[LPCName]])
    {
        Device (RTC0)
        {
            Name (_HID, EisaId ("PNP0B00"))  // _HID: Hardware ID
            Name (_CRS, ResourceTemplate ()  // _CRS: Current Resource Settings
            {
                IO (Decode16,
                    0x0070,             // Range Minimum
                    0x0070,             // Range Maximum
                    0x01,               // Alignment
                    0x08,               // Length
                    )
                IRQNoFlags ()
                    {8}
            })
            Method (_STA, 0, NotSerialized)  // _STA: 状态
            {
                If (_OSI ("Darwin"))
                {
                    Return (0x0F)
                }
                Else
                {
                    Return (0)
                }
            }
        }
    }
""".replace("[[LPCName]]",lpc_name)
        ssdt += "}"
        #self.write_ssdt("SSDT-RTCAWAC",ssdt)
        #print("")
        #print("完成.")
        # 检查我们是否生成了一个故障保护 - 并鼓励手动检查
        # 需要只有RTC设备（没有AWAC）且有_STA但没有STAS变量
        #if rtc_dict.get("valid") and not awac_dict.get("valid") and rtc_dict.get("sta") and not rtc_dict.get("has_var") and not rtc_range_needed:
        #    print("\n   {}!! 注意 !!{} 仅检测到RTC（没有AWAC），带有_STA方法但没有STAS".format(self.yel,self.rst))
        #    print("               变量! 已创建补丁和SSDT-RTCAWAC作为故障保护，")
        #    print("               但请通过检查RTC._STA条件来验证您是否需要它们!")
        #self.patch_warn()
        #self.u.grab("按[回车]返回...")
        
        if self.write_ssdt(ssdt_name, ssdt):
            return {
                "Add": [
                    {
                        "Comment": ssdt_name + ".aml",
                        "Enabled": self.write_ssdt(ssdt_name, ssdt),
                        "Path": ssdt_name + ".aml"
                    }
                ],
                "Patch": awac_dict.get("patches",[])+rtc_dict.get("patches",[])
            }

    def fake_embedded_controller(self):
        ssdt_name = "SSDT-EC"
        laptop = "Laptop" in self.hardware_report.get("Motherboard").get("Platform")
        
        #if not self.ensure_dsdt():
        #    return
        #self.u.head("虚拟EC")
        #print("")
        #print("正在定位PNP0C09 (EC)设备...")
        # 设置一个辅助方法来确定
        # 根据类型和返回值是否需要修补_STA。
        def sta_needs_patching(sta):
            if not isinstance(sta,dict) or not sta.get("sta"):
                return False
            # 检查我们是否有IntObj或MethodObj
            # _STA，如果可能的话，抓取值。
            if sta.get("sta_type") == "IntObj":
                # 我们得到了一个整数 - 看看它是否被强制启用
                try:
                    sta_scope = table["lines"][sta["sta"][0][1]]
                    if not "Name (_STA, 0x0F)" in sta_scope:
                        return True
                except Exception as e:
                    #print(e)
                    return True
            elif sta.get("sta_type") == "MethodObj":
                # 我们得到了一个方法 - 如果我们有多个
                # "Return (", 或不是单个 "Return (0x0F)",
                # 那么我们需要修补它并替换
                try:
                    sta_scope = "\n".join(self.acpi.get_scope(sta["sta"][0][1],strip_comments=True,table=table))
                    if sta_scope.count("Return (") > 1 or not "Return (0x0F)" in sta_scope:
                        # 不止一个返回，或者我们的返回不是强制启用的
                        return True
                except Exception as e:
                    return True
            # 如果我们到了这里 - 它不是一个可识别的类型，或者
            # 它已经完全合格，不需要修补
            return False
        rename = False
        named_ec = False
        ec_to_patch = []
        ec_to_enable = []
        ec_sta = {}
        ec_enable_sta = {}
        patches = []
        lpc_name = None
        ec_located = False
        for table_name in self.sorted_nicely(list(self.acpi.acpi_tables)):
            table = self.acpi.acpi_tables[table_name]
            ec_list = self.acpi.get_device_paths_with_hid("PNP0C09",table=table)
            if len(ec_list):
                lpc_name = ".".join(ec_list[0][0].split(".")[:-1])
                #print(" - Got {:,} in {}".format(len(ec_list),table_name))
                #print(" - Validating...")
                for x in ec_list:
                    device = orig_device = x[0]
                    #print(" --> {}".format(device))
                    if device.split(".")[-1] == "EC":
                        named_ec = True
                        if not laptop:
                            # 只有当我们试图替换它时才重命名
                            #print(" ----> PNP0C09 (EC) 名为 EC。正在重命名")
                            device = ".".join(device.split(".")[:-1]+["EC0"])
                            rename = True
                    scope = "\n".join(self.acpi.get_scope(x[1],strip_comments=True,table=table))
                    # 我们需要检查 _HID, _CRS 和 _GPE
                    if all(y in scope for y in ["_HID","_CRS","_GPE"]):
                        #print(" ----> 有效的 PNP0C09 (EC) 设备")
                        ec_located = True
                        sta = self.get_sta_var(
                            var=None,
                            device=orig_device,
                            dev_hid="PNP0C09",
                            dev_name=orig_device.split(".")[-1],
                            log_locate=False,
                            table=table
                        )
                        if not laptop:
                            ec_to_patch.append(device)
                            # 只有在不是为笔记本电脑构建时才无条件覆盖 _STA 方法
                            if sta.get("patches"):
                                patches.extend(sta.get("patches",[]))
                                ec_sta[device] = sta
                        elif sta.get("patches"):
                            if sta_needs_patching(sta):
                                # 保留信息，因为我们需要覆盖它
                                ec_to_enable.append(device)
                                ec_enable_sta[device] = sta
                                # 默认禁用补丁并添加到列表中
                                for patch in sta.get("patches",[]):
                                    patch["Enabled"] = False
                                    patch["Disabled"] = True
                                    patches.append(patch)
                    #else:
                    #    print(" --> _STA 已正确启用 - 跳过重命名")
            #else:
            #    print(" ----> 不是有效的 PNP0C09 (EC) 设备")
        #if not ec_located:
            #print(" - 未找到有效的 PNP0C09 (EC) 设备 - 只需要虚拟 EC 设备")
        if laptop and named_ec and not patches:
            #print(" ----> 已定位到命名为 EC 的设备 - 不需要虚拟设备。")
            #print("")
            #self.u.grab("按[回车]返回主菜单...")
            return
        if lpc_name is None:
            lpc_name = self.get_lpc_name(skip_ec=True,skip_common_names=True)
        if lpc_name is None:
            #self.u.grab("Press [enter] to return to main menu...")
            return
        #comment = "虚拟嵌入式控制器"
        if rename == True:
            patches.insert(0,{
                "Comment":"EC 到 EC0{}".format("" if not ec_sta else " - 必须在任何 EC _STA 到 XSTA 重命名之前！"),
                "Find":"45435f5f",
                "Replace":"4543305f"
            })
        #    comment += " - 需要 EC 到 EC0 {}".format(
        #        "和 EC _STA 到 XSTA 重命名" if ec_sta else "重命名"
        #    )
        #elif ec_sta:
        #    comment += " - 需要 EC _STA 到 XSTA 重命名"
        #oc = {"Comment":comment,"Enabled":True,"Path":"SSDT-EC.aml"}
        #self.make_plist(oc, "SSDT-EC.aml", patches, replace=True)
        #print("正在创建 SSDT-EC...")
        ssdt = """
DefinitionBlock ("", "SSDT", 2, "ZPSS", "EC", 0x00001000)
{
    External ([[LPCName]], DeviceObj)
""".replace("[[LPCName]]",lpc_name)
        for x in ec_to_patch:
            ssdt += "    External ({}, DeviceObj)\n".format(x)
            if x in ec_sta:
                ssdt += "    External ({}.XSTA, {})\n".format(x,ec_sta[x].get("sta_type","MethodObj"))
        # 遍历需要启用的EC设备
        for x in ec_to_enable:
            ssdt += "    External ({}, DeviceObj)\n".format(x)
            if x in ec_enable_sta:
                # Add the _STA and XSTA refs as the patch may not be enabled
                ssdt += "    External ({0}._STA, {1})\n    External ({0}.XSTA, {1})\n".format(x,ec_enable_sta[x].get("sta_type","MethodObj"))
        # 再次遍历并添加_STA方法
        for x in ec_to_patch:
            ssdt += """
    Scope ([[ECName]])
    {
        Method (_STA, 0, NotSerialized)  // _STA: Status
        {
            If (_OSI ("Darwin"))
            {
                Return (0)
            }
            Else
            {
                Return ([[XSTA]])
            }
        }
    }
""".replace("[[LPCName]]",lpc_name).replace("[[ECName]]",x) \
    .replace("[[XSTA]]","{}.XSTA{}".format(x," ()" if ec_sta[x].get("sta_type","MethodObj")=="MethodObj" else "") if x in ec_sta else "0x0F")
        # 再次遍历 - 并根据需要强制启用
        for x in ec_to_enable:
            ssdt += """
    If (LAnd (CondRefOf ([[ECName]].XSTA), LNot (CondRefOf ([[ECName]]._STA))))
    {
        Scope ([[ECName]])
        {
            Method (_STA, 0, NotSerialized)  // _STA: Status
            {
                If (_OSI ("Darwin"))
                {
                    Return (0x0F)
                }
                Else
                {
                    Return ([[XSTA]])
                }
            }
        }
    }
""".replace("[[LPCName]]",lpc_name).replace("[[ECName]]",x) \
    .replace("[[XSTA]]","{}.XSTA{}".format(x," ()" if ec_enable_sta[x].get("sta_type","MethodObj")=="MethodObj" else "") if x in ec_enable_sta else "Zero")
        # 创建虚拟EC
        if not laptop or not named_ec:
            ssdt += """
    Scope ([[LPCName]])
    {
        Device (EC)
        {
            Name (_HID, "ACID0001")  // _HID: Hardware ID
            Method (_STA, 0, NotSerialized)  // _STA: Status
            {
                If (_OSI ("Darwin"))
                {
                    Return (0x0F)
                }
                Else
                {
                    Return (Zero)
                }
            }
        }
    }""".replace("[[LPCName]]",lpc_name)
        # 关闭SSDT作用域
        ssdt += """\n}"""
        #self.write_ssdt("SSDT-EC",ssdt)
        #print("")
        #print("完成.")
        #self.patch_warn()
        #self.u.grab("按[回车]返回...")

        return {
            "Add": [
                {
                    "Comment": ssdt_name + ".aml",
                    "Enabled": self.write_ssdt(ssdt_name, ssdt),
                    "Path": ssdt_name + ".aml"
                }
            ],
            "Patch": patches
        }

    def get_data(self, data, pad_to=0):
        if sys.version_info >= (3, 0):
            if not isinstance(data,bytes):
                data = data.encode()
            return data+b"\x00"*(max(pad_to-len(data),0))
        else:
            return plistlib.Data(data+b"\x00"*(max(pad_to-len(data),0)))

    def write_ssdt(self, ssdt_name, ssdt_content, compile=True):
        dsl_path = os.path.join(self.acpi_directory, ssdt_name + ".dsl")
        aml_path = os.path.join(self.acpi_directory, ssdt_name + ".aml")

        if not os.path.exists(self.acpi_directory):
            os.makedirs(self.acpi_directory)

        with open(dsl_path,"w") as f:
            f.write(ssdt_content)

        if not compile:
            return False
        
        output = self.run({
            "args":[self.acpi.iasl, dsl_path]
        })
        
        if output[-1] != 0:
            return False
        else:
            os.remove(dsl_path)
        
        return os.path.exists(aml_path)

    def apply_acpi_patches(self, acpi_patches):
        acpi_patches = [
            {
                "Base": acpi_patch.get("Base", ""),
                "BaseSkip": acpi_patch.get("BaseSkip", 0),
                "Comment": acpi_patch.get("Comment", ""),
                "Count": acpi_patch.get("Count", 0),
                "Enabled": True,
                "Find": self.utils.hex_to_bytes(acpi_patch["Find"]),
                "Limit": acpi_patch.get("Limit", 0),
                "Mask": self.utils.hex_to_bytes(acpi_patch.get("Mask", "")),
                "OemTableId": self.utils.hex_to_bytes(acpi_patch.get("OemTableId", "")),
                "Replace": self.utils.hex_to_bytes(acpi_patch["Replace"]),
                "ReplaceMask": self.utils.hex_to_bytes(acpi_patch.get("ReplaceMask", "")),
                "Skip": acpi_patch.get("Skip", 0),
                "TableLength": acpi_patch.get("TableLength", 0),
                "TableSignature": self.utils.hex_to_bytes(acpi_patch.get("TableSignature", "")),
            }
            for acpi_patch in acpi_patches
        ]

        return sorted(acpi_patches, key=lambda x: x["Comment"])  # 按注释排序补丁

    def add_intel_management_engine(self):
        # 添加英特尔管理引擎设备
        ssdt_name = "SSDT-IMEI"
        ssdt_content = """
DefinitionBlock ("", "SSDT", 2, "ZPSS", "IMEI", 0x00000000)
{
    External (_SB_.PCI0, DeviceObj)

    Scope (_SB.PCI0)
    {
        Device (IMEI)
        {
            Name (_ADR, 0x00160000)  // _ADR: 地址
            Method (_STA, 0, NotSerialized)  // _STA: 状态
            {
                If (_OSI ("Darwin"))
                {
                    Return (0x0F)
                }
                Else
                {
                    Return (Zero)
                }
            }
        }
    }
}"""

        imei_device = self.acpi.get_device_paths_with_hid("0x00160000", self.dsdt)

        if not imei_device:  # 如果没有找到IMEI设备，则创建虚拟设备
            return {
                "Add": [
                    {
                        "Comment": ssdt_name + ".aml",
                        "Enabled": self.write_ssdt(ssdt_name, ssdt_content),
                        "Path": ssdt_name + ".aml"
                    }
                ]
            }

    def add_memory_controller_device(self):
        # 添加内存控制器设备
        if not self.lpc_bus_device:
            return
        
        ssdt_name = "SSDT-MCHC"
        ssdt_content = """
DefinitionBlock ("", "SSDT", 2, "ZPSS", "MCHC", 0)
{
    External ([[PCIName]], DeviceObj)

    Scope ([[PCIName]])
    {
        Device (MCHC)
        {
            Name (_ADR, Zero)
            Method (_STA, 0, NotSerialized)
            {
                If (_OSI ("Darwin"))
                {
                    Return (0x0F)
                }
                Else
                {
                    Return (Zero)
                }
            }
        }
    }
}"""

        mchc_device = self.acpi.get_device_paths("MCHC", self.dsdt)

        if mchc_device:
            return
        
        pci_bus_device = ".".join(self.lpc_bus_device.split(".")[:2])
        ssdt_content = ssdt_content.replace("[[PCIName]]", pci_bus_device)

        return {
            "Add": [
                {
                    "Comment": ssdt_name + ".aml",
                    "Enabled": self.write_ssdt(ssdt_name, ssdt_content),
                    "Path": ssdt_name + ".aml"
                }
            ]
        }

    def add_system_management_bus_device(self):
        # 添加系统管理总线设备
        if not self.lpc_bus_device:
            return
        
        try:
            # 根据CPU代数选择合适的HID
            smbus_device_name = self.acpi.get_device_paths_with_hid(
                "0x001F0003" if self.hardware_report.get("CPU").get("Codename") in cpu_data.IntelCPUGenerations[50:] else "0x001F0004", 
                self.dsdt
            )[0][0].split(".")[-1]
        except:
            smbus_device_name = "SBUS"  # 默认名称
            
        pci_bus_device = ".".join(self.lpc_bus_device.split(".")[:2])
        smbus_device_path = "{}.{}".format(pci_bus_device, smbus_device_name)

        ssdt_name = "SSDT-{}".format(smbus_device_name)
        ssdt_content = """
DefinitionBlock ("", "SSDT", 2, "ZPSS", "[[SMBUSName]]", 0)
{
    External ([[SMBUSDevice]], DeviceObj)

    Scope ([[SMBUSDevice]])
    {
        Device (BUS0)
        {
            Name (_CID, "smbus")
            Name (_ADR, Zero)  // _ADR: 地址
            Method (_STA, 0, NotSerialized)  // _STA: 状态
            {
                If (_OSI ("Darwin"))
                {
                    Return (0x0F)
                }
                Else
                {
                    Return (Zero)
                }
            }
        }
    }
}""".replace("[[SMBUSName]]", smbus_device_name).replace("[[SMBUSDevice]]", smbus_device_path)

        return {
            "Add": [
                {
                    "Comment": ssdt_name + ".aml",
                    "Enabled": self.write_ssdt(ssdt_name, ssdt_content),
                    "Path": ssdt_name + ".aml"
                }
            ]
        }

    def add_usb_power_properties(self):
        # 添加USB电源属性
        ssdt_name = "SSDT-USBX"
        ssdt_content = """
DefinitionBlock ("", "SSDT", 2, "ZPSS", "USBX", 0x00001000)
{
    Scope (\\_SB)
    {
        Device (USBX)
        {
            Name (_ADR, Zero)  // _ADR: 地址
            Method (_DSM, 4, NotSerialized)  // _DSM: 设备特定方法
            {
                If (LNot (Arg2))
                {
                    Return (Buffer ()
                    {
                        0x03
                    })
                }
                Return (Package ()
                {[[USBX_PROPS]]
                })
            }
            Method (_STA, 0, NotSerialized)  // _STA: Status
            {
                If (_OSI ("Darwin"))
                {
                    Return (0x0F)
                }
                Else
                {
                    Return (Zero)
                }
            }
        }
    }
}"""
        
        usb_power_properties = None
        if self.utils.contains_any(["MacPro7,1", "iMacPro1,1", "iMac20,", "iMac19,", "iMac18,", "iMac17,", "iMac16,"], self.smbios_model):
            # 桌面机型的USB电源属性
            usb_power_properties = {
                "kUSBSleepPowerSupply":"0x13EC",
                "kUSBSleepPortCurrentLimit":"0x0834",
                "kUSBWakePowerSupply":"0x13EC",
                "kUSBWakePortCurrentLimit":"0x0834"
            }
        elif "MacMini8,1" in self.smbios_model:
            # Mac mini的USB电源属性
            usb_power_properties = {
                "kUSBSleepPowerSupply":"0x0C80",
                "kUSBSleepPortCurrentLimit":"0x0834",
                "kUSBWakePowerSupply":"0x0C80",
                "kUSBWakePortCurrentLimit":"0x0834"
            }
        elif self.utils.contains_any(["MacBookPro16,", "MacBookPro15,", "MacBookPro14,", "MacBookPro13,", "MacBookAir9,1"], self.smbios_model):
            # 现代笔记本的USB电源属性
            usb_power_properties = {
                "kUSBSleepPortCurrentLimit":"0x0BB8",
                "kUSBWakePortCurrentLimit":"0x0BB8"
            }
        elif "MacBook9,1" in self.smbios_model:
            # 旧款MacBook的USB电源属性
            usb_power_properties = {
                "kUSBSleepPowerSupply":"0x05DC",
                "kUSBSleepPortCurrentLimit":"0x05DC",
                "kUSBWakePowerSupply":"0x05DC",
                "kUSBWakePortCurrentLimit":"0x05DC"
            }

        if usb_power_properties:
            ssdt_content = ssdt_content.replace("[[USBX_PROPS]]", ",".join("\n                    \"{}\",\n                    {}".format(key, usb_power_properties[key]) for key in usb_power_properties))
            
            return {
                "Add": [
                    {
                        "Comment": ssdt_name + ".aml",
                        "Enabled": self.write_ssdt(ssdt_name, ssdt_content),
                        "Path": ssdt_name + ".aml"
                    }
                ]
            }

    def ambient_light_sensor(self):
        # 创建环境光传感器设备
        ssdt_name = "SSDT-ALS0"
        ssdt_content = """
// 来源: https://github.com/acidanthera/OpenCorePkg/blob/master/Docs/AcpiSamples/Source/SSDT-ALS0.dsl

/*
 * 从macOS 10.15开始，环境光传感器的存在是背光功能所必需的。
 * 这里我们创建一个环境光传感器ACPI设备，可被SMCLightSensor驱动用来
 * 通过SMC接口报告虚拟值（当没有实际设备存在时）或有效值。
 */
DefinitionBlock ("", "SSDT", 2, "ZPSS", "ALS0", 0x00000000)
{
    Scope (_SB)
    {
        Device (ALS0)
        {
            Name (_HID, "ACPI0008" /* Ambient Light Sensor Device */)  // _HID: Hardware ID
            Name (_CID, "smc-als")  // _CID: Compatible ID
            Name (_ALI, 0x012C)  // _ALI: Ambient Light Illuminance
            Name (_ALR, Package (0x01)  // _ALR: Ambient Light Response
            {
                Package (0x02)
                {
                    0x64, 
                    0x012C
                }
            })
            Method (_STA, 0, NotSerialized)  // _STA: Status
            {
                If (_OSI ("Darwin"))
                {
                    Return (0x0F)
                }
                Else
                {
                    Return (Zero)
                }
            }
        }
    }
}"""
        try:
            als_device = self.acpi.get_device_paths_with_hid("ACPI0008", self.dsdt)[0][0]
        except:
            als_device = None

        patches = []

        if als_device:
            als_device_name = als_device.split(".")[-1]
            if "." not in als_device:
                als_device_name = als_device_name[1:]

            sta = self.get_sta_var(var=None, device=None, dev_hid="ACPI0008", dev_name=als_device_name, table=self.dsdt)
            patches.extend(sta.get("patches", []))
            
            ssdt_name = "SSDT-{}".format(als_device_name)
            ssdt_content = """
DefinitionBlock ("", "SSDT", 2, "ZPSS", "[[ALSName]]", 0x00000000)
{
    External ([[ALSDevice]], DeviceObj)
    External ([[ALSDevice]].XSTA, [[STAType]])

    Scope ([[ALSDevice]])
    {
        Method (_STA, 0, NotSerialized)  // _STA: Status
        {
            If (_OSI ("Darwin"))
            {
                Return (0x0F)
            }
            Else
            {
                Return ([[XSTA]])
            }
        }
    }
}""".replace("[[ALSName]]", als_device_name) \
    .replace("[[ALSDevice]]", als_device) \
    .replace("[[STAType]]", sta.get("sta_type","MethodObj")) \
    .replace("[[XSTA]]", "{}.XSTA{}".format(als_device," ()" if sta.get("sta_type","MethodObj") == "MethodObj" else "") if sta else "0x0F")

        return {
            "Add": [
                {
                    "Comment": ssdt_name + ".aml",
                    "Enabled": self.write_ssdt(ssdt_name, ssdt_content),
                    "Path": ssdt_name + ".aml"
                }
            ],
            "Patch": patches
        }
    
    def findall_power_resource_blocks(self, table_lines):
        # 查找ACPI表中的所有PowerResource块
        power_resource_blocks = []

        i = 0
        while i < len(table_lines):
            line = table_lines[i].strip()
            if line.startswith("PowerResource"):
                start_index = i
                open_brackets = 1
                i += 1
                while i < len(table_lines) and open_brackets > 0:
                    if '{' in table_lines[i]:
                        open_brackets += table_lines[i].count('{')
                    if '}' in table_lines[i]:
                        open_brackets -= table_lines[i].count('}')
                    i += 1
                end_index = i - 1
                power_resource_blocks.append((start_index, end_index))
            else:
                i += 1

        return power_resource_blocks

    def is_method_in_power_resource(self, method, table_lines):
        # 检查方法是否位于PowerResource块内
        power_resource_blocks = self.findall_power_resource_blocks(table_lines)
        
        for start, end in power_resource_blocks:
            if start <= method[1] <= end:
                return True
        return False

    def disable_unsupported_device(self):
        # 禁用不受支持的设备
        results = {
            "Add": []
        }

        for device_name, device_props in self.disabled_devices.items():
            if not device_props.get("Bus Type", "PCI") == "PCI" or not device_props.get("ACPI Path"):
                continue

            ssdt_name = None
            if "GPU" in device_name and device_props.get("Device Type") != "Integrated GPU":
                ssdt_name = "SSDT-Disable_GPU_{}".format(device_props.get("ACPI Path").split(".")[2])
                target_device = device_props.get("ACPI Path")

                off_method_found = ps3_method_found = False
                for table_name, table_data in self.acpi.acpi_tables.items():
                    off_methods = self.acpi.get_method_paths("_OFF", table_data)
                    ps3_methods = self.acpi.get_method_paths("_PS3", table_data)

                    off_method_found = off_method_found or any(method[0].startswith(target_device) and not self.is_method_in_power_resource(method, table_data.get("lines")) for method in off_methods)
                    ps3_method_found = ps3_method_found or any(method[0].startswith(target_device) for method in ps3_methods)
                
                if not off_method_found and not ps3_method_found:
                    continue

                if off_method_found:
                    ps3_method_found = False

                device_props["Disabled"] = True
                
                ssdt_content = """
DefinitionBlock ("", "SSDT", 2, "ZPSS", "DGPU", 0x00000000)
{"""
                if off_method_found:
                    ssdt_content += """
    External ([[DevicePath]]._OFF, MethodObj)
    External ([[DevicePath]]._ON_, MethodObj)"""
                if ps3_method_found:
                    ssdt_content += """
    External ([[DevicePath]]._PS0, MethodObj)  // _PS0: 电源状态0
    External ([[DevicePath]]._PS3, MethodObj)  // _PS3: 电源状态3
    External ([[DevicePath]]._DSM, MethodObj)  // _DSM: 设备特定方法
"""
                ssdt_content += """
    Device (DGPU)
    {
        Name (_HID, "DGPU1000")
        Method (_INI, 0, NotSerialized)  // _INI: 初始化
        {
            _OFF ()
        }

        Method (_STA, 0, NotSerialized)  // _STA: 状态
        {
            If (_OSI ("Darwin"))
            {
                Return (0x0F)
            }
            Else
            {
                Return (Zero)
            }
        }

        Method (_ON, 0, NotSerialized)  // _ON: 开启
        {
"""
                if off_method_found:
                    ssdt_content += """
            [[DevicePath]]._ON ()
            """

                if ps3_method_found:
                    ssdt_content += """
            [[DevicePath]]._PS0 ()
            """
        
                ssdt_content += """
        }

        Method (_OFF, 0, NotSerialized)  // _OFF: 关闭
        {
"""
                if off_method_found:
                    ssdt_content += """
            [[DevicePath]]._OFF ()
            """

                if ps3_method_found:
                    ssdt_content += """
            [[DevicePath]]._DSM (ToUUID ("a486d8f8-0bda-471b-a72b-6042a6b5bee0") /* 未知UUID */, 0x0100, 0x1A, Buffer (0x04)
            {
                    0x01, 0x00, 0x00, 0x03                           // ....
            })
            [[DevicePath]]._PS3 ()  // 进入电源状态3
            """
        
                ssdt_content += """\n        }\n    }\n}"""

            elif "Network" in device_name and device_props.get("Bus Type") == "PCI":
                ssdt_name = "SSDT-Disable_Network_{}".format(device_props.get("ACPI Path").split(".")[2])
                ssdt_content = """
DefinitionBlock ("", "SSDT", 2, "ZPSS", "DNET", 0x00000000)
{
    External ([[DevicePath]], DeviceObj)

    Method ([[DevicePath]]._DSM, 4, NotSerialized)  // _DSM: 设备特定方法
    {
        If ((!Arg2 || (_OSI ("Darwin") == Zero)))
        {
            Return (Buffer (One)
            {
                 0x03                                             // .
            })
        }

        Return (Package (0x0A)
        {
            "name", 
            Buffer (0x09)
            {
                "#network"
            }, 

            "IOName", 
            "#display", 
            "class-code", 
            Buffer (0x04)
            {
                 0xFF, 0xFF, 0xFF, 0xFF                           // ....
            }, 

            "vendor-id", 
            Buffer (0x04)
            {
                 0xFF, 0xFF, 0x00, 0x00                           // ....
            }, 

            "device-id", 
            Buffer (0x04)
            {
                 0xFF, 0xFF, 0x00, 0x00                           // ....
            }
        })
    }
}
"""
            elif "Storage" in device_name:
                # 禁用NVMe存储设备
                ssdt_name = "SSDT-Disable_NVMe_{}".format(device_props.get("ACPI Path").split(".")[-2])
                ssdt_content = """
DefinitionBlock ("", "SSDT", 2, "ZPSS", "DNVMe", 0x00000000)
{
    External ([[DevicePath]], DeviceObj)

    Method ([[DevicePath]]._DSM, 4, NotSerialized)  // _DSM: 设备特定方法
    {
        If (_OSI ("Darwin"))
        {
            If (!Arg2)
            {
                Return (Buffer (One)
                {
                     0x03                                             // .
                })
            }

            Return (Package (0x02)
            {
                "class-code", 
                Buffer (0x04)
                {
                     0xFF, 0x08, 0x01, 0x00                           // ....
                }
            })
        }
    }
}
"""

            if ssdt_name:
                ssdt_content = ssdt_content.replace("[[DevicePath]]", device_props.get("ACPI Path"))
                
                results["Add"].append(
                    {
                        "Comment": ssdt_name + ".aml",
                        "Enabled": self.write_ssdt(ssdt_name, ssdt_content),
                        "Path": ssdt_name + ".aml"
                    }
                )

        return results
  
    def enable_backlight_controls(self):
        # 启用背光控制
        patches = []

        integrated_gpu = list(self.hardware_report.get("GPU").items())[-1][-1]
        uid_value = 19
        if integrated_gpu.get("Codename") in ("Iron Lake", "Sandy Bridge", "Ivy Bridge"):
            uid_value = 14
        elif integrated_gpu.get("Codename") in ("Haswell", "Broadwell"):
            uid_value = 15
        elif integrated_gpu.get("Codename") in ("Skylake", "Kaby Lake"):
            uid_value = 16
                                
        if "PNLF" in self.dsdt.get("table"):
            patches.append({
                "Comment": "PNLF 重命名为 XNLF",
                "Find": "504E4C46",
                "Replace": "584E4C46"
            })

        for table_name in self.sorted_nicely(list(self.acpi.acpi_tables)):
            table = self.acpi.acpi_tables[table_name]

            if binascii.unhexlify("084E4243460A00") in table.get("raw"):
                patches.append({
                    "Comment": "NBCF 0x00 改为 0x01",
                    "Find": "084E4243460A00",
                    "Replace": "084E4243460A01"
                })
                break
            elif binascii.unhexlify("084E42434600") in table.get("raw"):
                patches.append({
                    "Comment": "NBCF 0x00 改为 0x01",
                    "Find": "084E42434600",
                    "Replace": "084E42434601"
                })
                break
            
        ssdt_name = "SSDT-PNLF"
        ssdt_content = """
DefinitionBlock ("", "SSDT", 2, "ZPSS", "PNLF", 0x00000000)
{"""
        if integrated_gpu.get("ACPI Path"):
            ssdt_content += """\n    External ([[DevicePath]], DeviceObj)\n    Device ([[DevicePath]].PNLF)"""
        else:
            ssdt_content += """\n    Device (PNLF)"""
        ssdt_content += """
    {
        Name (_HID, EisaId ("APP0002"))  // _HID: 硬件ID
        Name (_CID, "backlight")  // _CID: 兼容ID
        Name (_UID, [[uid_value]])  // _UID: 唯一ID
        
        Method (_STA, 0, NotSerialized)  // _STA: 状态
        {
            If (_OSI ("Darwin"))
            {
                Return (0x0B)
            }
            Else
            {
                Return (Zero)
            }
        }"""
        if integrated_gpu.get("ACPI Path") and uid_value == 14:
            ssdt_content += """
        Method (_INI, 0, Serialized)
        {
            If (_OSI ("Darwin"))
            {
                OperationRegion ([[DevicePath]].RMP3, PCI_Config, Zero, 0x14)
                Field ([[DevicePath]].RMP3, AnyAcc, NoLock, Preserve)
                {
                    Offset (0x02), GDID,16,
                    Offset (0x10), BAR1,32,
                }
                // IGPU PWM背光寄存器描述:
                //   LEV2 当前未使用
                //   LEVL Sandy/Ivy平台的背光亮度
                //   P0BL 计数器，当为0时是垂直空白
                //   GRAN 详见下面的INI1方法描述
                //   LEVW 应初始化为0xC0000000
                //   LEVX PWMMax（除FBTYPE_HSWPLUS外，是max/level的组合，Sandy/Ivy存储在MSW中）
                //   LEVD Coffeelake平台的背光亮度
                //   PCHL 当前未使用
                OperationRegion (RMB1, SystemMemory, BAR1 & ~0xF, 0xe1184)
                Field(RMB1, AnyAcc, Lock, Preserve)
                {
                    Offset (0x48250),
                    LEV2, 32,
                    LEVL, 32,
                    Offset (0x70040),
                    P0BL, 32,
                    Offset (0xc2000),
                    GRAN, 32,
                    Offset (0xc8250),
                    LEVW, 32,
                    LEVX, 32,
                    LEVD, 32,
                    Offset (0xe1180),
                    PCHL, 32,
                }
                // Now fixup the backlight PWM depending on the framebuffer type
                // At this point:
                //   Local4 is RMCF.BLKT value (unused here), if specified (default is 1)
                //   Local0 is device-id for IGPU
                //   Local2 is LMAX, if specified (Ones means based on device-id)
                //   Local3 is framebuffer type

                // Adjustment required when using WhateverGreen.kext
                Local0 = GDID
                Local2 = Ones
                Local3 = 0

                // check Sandy/Ivy
                // #define FBTYPE_SANDYIVY 1
                If (LOr (LEqual (1, Local3), LNotEqual (Match (Package()
                {
                    // Sandy HD3000
                    0x010b, 0x0102,
                    0x0106, 0x1106, 0x1601, 0x0116, 0x0126,
                    0x0112, 0x0122,
                    // Ivy
                    0x0152, 0x0156, 0x0162, 0x0166,
                    0x016a,
                    // Arrandale
                    0x0046, 0x0042,
                }, MEQ, Local0, MTR, 0, 0), Ones)))
                {
                    if (LEqual (Local2, Ones))
                    {
                        // #define SANDYIVY_PWMMAX 0x710
                        Store (0x710, Local2)
                    }
                    // change/scale only if different than current...
                    Store (LEVX >> 16, Local1)
                    If (LNot (Local1))
                    {
                        Store (Local2, Local1)
                    }
                    If (LNotEqual (Local2, Local1))
                    {
                        // set new backlight PWMMax but retain current backlight level by scaling
                        Store ((LEVL * Local2) / Local1, Local0)
                        Store (Local2 << 16, Local3)
                        If (LGreater (Local2, Local1))
                        {
                            // PWMMax is getting larger... store new PWMMax first
                            Store (Local3, LEVX)
                            Store (Local0, LEVL)
                        }
                        Else
                        {
                            // otherwise, store new brightness level, followed by new PWMMax
                            Store (Local0, LEVL)
                            Store (Local3, LEVX)
                        }
                    }
                }
            }
        }"""
        ssdt_content += """
    }
}"""

        ssdt_content = ssdt_content.replace("[[uid_value]]", str(uid_value))
        if integrated_gpu.get("ACPI Path"):
            ssdt_content = ssdt_content.replace("[[DevicePath]]", integrated_gpu.get("ACPI Path"))   
        
        return {
            "Add": [
                {
                    "Comment": ssdt_name + ".aml",
                    "Enabled": self.write_ssdt(ssdt_name, ssdt_content),
                    "Path": ssdt_name + ".aml"
                }
            ],
            "Patch": patches
        }

    def enable_gpio_device(self):
        try:
            gpio_device = self.acpi.get_device_paths("GPI0", self.dsdt)[0][0] or self.acpi.get_device_paths("GPIO", self.dsdt)[0][0]
        except:
            return
        
        sta = self.get_sta_var(var=None, device=gpio_device, dev_hid=None, dev_name=gpio_device.split(".")[-1], table=self.dsdt)
        
        ssdt_name = "SSDT-GPI0"
        ssdt_content = """
DefinitionBlock ("", "SSDT", 2, "ZPSS", "GPI0", 0x00000000)
{
    External ([[GPI0Path]], DeviceObj)
    External ([[GPI0Path]].XSTA, [[STAType]])

    Scope ([[GPI0Path]])
    {
        Method (_STA, 0, NotSerialized)  // _STA: Status
        {
            If (_OSI ("Darwin"))
            {
                Return (0x0F)
            }
            Else
            {
                Return ([[XSTA]])
            }
        }
    }
}""".replace("[[GPI0Path]]", gpio_device) \
    .replace("[[STAType]]", sta.get("sta_type","MethodObj")) \
    .replace("[[XSTA]]", "{}.XSTA{}".format(gpio_device," ()" if sta.get("sta_type","MethodObj") == "MethodObj" else "") if sta else "0x0F")

        return {
            "Add": [
                {
                    "Comment": ssdt_name + ".aml",
                    "Enabled": self.write_ssdt(ssdt_name, ssdt_content),
                    "Path": ssdt_name + ".aml"
                }
            ],
            "Patch": sta.get("patches", [])
        }
    
    def enable_nvram_support(self):
        if not self.lpc_bus_device:
            return
              
        ssdt_name = "SSDT-PMC"
        ssdt_content = """
// 来源: https://github.com/acidanthera/OpenCorePkg/blob/master/Docs/AcpiSamples/Source/SSDT-PMC.dsl

/*
 * Intel 300系列PMC支持macOS
 *
 * 从Z390芯片组开始，PMC（D31:F2）只能通过MMIO访问。
 * 由于ACPI中没有标准的PMC设备，Apple引入了自己的命名"APP9876"，以便从AppleIntelPCHPMC驱动程序访问该设备。
 * 为避免混淆，我们在所有其他操作系统中禁用此设备，因为它们通常使用另一个非标准设备，其HID为"PNP0C02"，UID为"PCHRESV"。
 *
 * 在某些实现中，包括APTIO V，NVRAM访问需要PMC初始化，否则会在SMM模式下冻结。
 * 其原因尚不清楚。请注意，PMC和SPI位于单独的内存区域，PCHRESV映射两者，但AppleIntelPCHPMC仅使用PMC区域：
 * 0xFE000000~0xFE00FFFF - PMC MBAR
 * 0xFE010000~0xFE010FFF - SPI BAR0
 * 0xFE020000~0xFE035FFF - ACPI模式下的SerialIo BAR
 *
 * PMC设备与LPC总线无关，但将其添加到LPC总线范围是为了更快地初始化。
 * 如果将其添加到它通常存在的PCI0中，它将在PCI配置的最后启动，这对于NVRAM支持来说太晚了。
 */
DefinitionBlock ("", "SSDT", 2, "ACDT", "PMCR", 0x00001000)
{
    External ([[LPCPath]], DeviceObj)

    Scope ([[LPCPath]])
    {
        Device (PMCR)
        {
            Name (_HID, EisaId ("APP9876"))  // _HID: 硬件ID
            Method (_STA, 0, NotSerialized)  // _STA: 状态
            {
                If (_OSI ("Darwin"))
                {
                    Return (0x0B)
                }
                Else
                {
                    Return (Zero)
                }
            }
            Name (_CRS, ResourceTemplate ()  // _CRS: 当前资源设置
            {
                Memory32Fixed (ReadWrite,
                    0xFE000000,         // Address Base
                    0x00010000,         // Address Length
                    )
            })
        }
    }
}""".replace("[[LPCPath]]", self.lpc_bus_device)

        return {
            "Add": [
                {
                    "Comment": ssdt_name + ".aml",
                    "Enabled": self.write_ssdt(ssdt_name, ssdt_content),
                    "Path": ssdt_name + ".aml"
                }
            ],
        }
    
    def remove_conditional_scope(self):
        # 移除条件ACPI作用域声明
        return {
            "Patch": [
                {
                    "Comment": "移除条件ACPI作用域声明",
                    "Find": "A000000092935043484100",
                    "Replace": "A3A3A3A3A3A3A3A3A3A3A3",
                    "Mask": "FF000000FFFFFFFFFFFFFF",
                    "Count": 1,
                    "TableSignature": "44534454"
                }
            ]
        }

    def fix_hp_005_post_error(self):
        # 修复HP实时时钟电源丢失(005)启动错误
        if binascii.unhexlify("4701700070000108") in self.dsdt.get("raw"):
            return {
                "Patch": [
                    {
                        "Comment": "修复HP实时时钟电源丢失(005)启动错误",
                        "Find": "4701700070000108",
                        "Replace": "4701700070000102"
                    }
                ]
            }

    def add_null_ethernet_device(self):
        random_mac_address = self.smbios.generate_random_mac()
        mac_address_byte = ", ".join([f'0x{random_mac_address[i:i+2]}' for i in range(0, len(random_mac_address), 2)])
        
        ssdt_name = "SSDT-RMNE"
        ssdt_content = """
// 来源: https://github.com/RehabMan/OS-X-Null-Ethernet/blob/master/SSDT-RMNE.dsl

/* ssdt.dsl -- NullEthernet的SSDT注入器
 *
 * 版权所有 (c) 2014 RehabMan <racerrehabman@gmail.com>
 * 保留所有权利。
 *
 * 本程序是自由软件；您可以根据自由软件基金会发布的GNU通用公共许可证的条款
 * 重新发布或修改它，无论是版本2还是（根据您的选择）任何更新的版本。
 *
 * 本程序是基于"现况"发布的，不提供任何形式的明示或暗示保证，
 * 包括但不限于适销性和特定用途适用性的保证。
 * 有关更多详情，请参阅GNU通用公共许可证。
 *
 */

// 使用此SSDT作为修补DSDT的替代方案...

DefinitionBlock("", "SSDT", 2, "ZPSS", "RMNE", 0x00001000)
{
    Device (RMNE)
    {
        Name (_ADR, Zero)
        // NullEthernet驱动程序通过此HID匹配
        Name (_HID, "NULE0000")
        // 这是驱动程序返回的MAC地址。如有必要，请修改。
        Name (MAC, Buffer() { [[MACAddress]] })
        Method (_DSM, 4, NotSerialized)
        {
            If (LEqual (Arg2, Zero)) { Return (Buffer() { 0x03 } ) }
            Return (Package()
            {
                "built-in", Buffer() { 0x00 },
                "IOName", "ethernet",
                "name", Buffer() { "ethernet" },
                "model", Buffer() { "RM-NullEthernet-1001" },
                "device_type", Buffer() { "ethernet" },
            })
        }

        Method (_STA, 0, NotSerialized)  // _STA: Status
        {
            If (_OSI ("Darwin"))
            {
                Return (0x0F)
            }
            Else
            {
                Return (Zero)
            }
        }
    }
}""".replace("[[MACAddress]]", mac_address_byte)

        return {
            "Add": [
                {
                    "Comment": ssdt_name + ".aml",
                    "Enabled": self.write_ssdt(ssdt_name, ssdt_content),
                    "Path": ssdt_name + ".aml"
                }
            ]
        }

    def is_intel_hedt_cpu(self, processor_name, cpu_codename):
        if cpu_codename in cpu_data.IntelCPUGenerations[45:66]:
            return cpu_codename.endswith(("-X", "-P", "-W", "-E", "-EP", "-EX"))
        
        if cpu_codename in cpu_data.IntelCPUGenerations[66:]:
            return "Xeon" in processor_name
        
        return False
    
    def fix_system_clock_hedt(self):
        awac_device = self.acpi.get_device_paths_with_hid("ACPI000E", self.dsdt)
        try:
            rtc_device = self.acpi.get_device_paths_with_hid("PNP0B00", self.dsdt)[0][0]
            if rtc_device.endswith("RTC"):
                rtc_device += "_"
        except:
            if not self.lpc_bus_device:
                return
            rtc_device = self.lpc_bus_device + ".RTC0"
        new_rtc_device = ".".join(rtc_device.split(".")[:-1] + [self.get_unique_device(rtc_device, rtc_device.split(".")[-1])[0]])

        patches = []
        ssdt_name = "SSDT-RTC0-RANGE"
        ssdt_content = """
DefinitionBlock ("", "SSDT", 2, "ZPSS", "RtcRange", 0x00000000)
{"""
        if not awac_device:
            sta = self.get_sta_var(var=None, device=rtc_device, dev_hid=None, dev_name=rtc_device.split(".")[-1], table=self.dsdt)
            patches.extend(sta.get("patches", []))

            ssdt_content += """
    External ([[device_path]], DeviceObj)
    
    Scope ([[device_path]])
    {
        Method (_STA, 0, NotSerialized)  // _STA: Status
        {
            If (_OSI ("Darwin"))
            {
                Return (Zero)
            }
            Else
            {
                Return (0x0F)
            }
        }
    }""".replace("[[device_path]]", rtc_device)
        ssdt_content += """
    External ([[parent_path]], DeviceObj)

    Device ([[device_path]])
    {
        Name (_HID, EisaId ("PNP0B00") /* AT 实时时钟 */)  // _HID: 硬件ID
        Name (_CRS, ResourceTemplate ()  // _CRS: 当前资源设置
        {
            IO (Decode16,
                0x0070,             // Range Minimum
                0x0070,             // Range Maximum
                0x01,               // Alignment
                0x04,               // Length
                )
            IO (Decode16,
                0x0074,             // Range Minimum
                0x0074,             // Range Maximum
                0x01,               // Alignment
                0x04,               // Length
                )
            IRQNoFlags ()
                {8}
        })
        Method (_STA, 0, NotSerialized)  // _STA: Status
        {
            If (_OSI ("Darwin"))
            {
                Return (0x0F)
            }
            Else
            {
                Return (Zero)
            }
        }
    }
}""".replace("[[parent_path]]", ".".join(rtc_device.split(".")[:-1])).replace("[[device_path]]", new_rtc_device)
                
        return {
            "Add": [
                {
                    "Comment": ssdt_name + ".aml",
                    "Enabled": self.write_ssdt(ssdt_name, ssdt_content),
                    "Path": ssdt_name + ".aml"
                }
            ],
            "Patch": patches
        }

    def instant_wake_fix(self):
        ssdt_name = "SSDT-PRW"

        uswe_object = "9355535745"
        wole_object = "93574F4C45"
        gprw_method = "4750525702"
        uprw_method = "5550525702"
        xprw_method = "5850525702"

        patches = []

        if binascii.unhexlify(gprw_method) in self.dsdt.get("raw"):
            patches.append({
                "Comment": "GPRW to XPRW Rename",
                "Find": gprw_method,
                "Replace": xprw_method
            })
        else:
            gprw_method = None
        if binascii.unhexlify(uprw_method) in self.dsdt.get("raw"):
            patches.append({
                "Comment": "UPRW to XPRW Rename",
                "Find": uprw_method,
                "Replace": xprw_method
            })
        else:
            uprw_method = None
        if not binascii.unhexlify(uswe_object) in self.dsdt.get("raw"):
            uswe_object = None
        if not binascii.unhexlify(wole_object) in self.dsdt.get("raw"):
            wole_object = None
        
        ssdt_content = """
// 来源: https://github.com/5T33Z0/OC-Little-Translated/blob/main/04_Fixing_Sleep_and_Wake_Issues/060D_Instant_Wake_Fix/README.md

DefinitionBlock ("", "SSDT", 2, "ZPSS", "_PRW", 0x00000000)
{"""
        if gprw_method or uprw_method:
            ssdt_content += """\n    External(XPRW, MethodObj)"""
        if uswe_object:
            ssdt_content += "\n    External (USWE, FieldUnitObj)"
        if wole_object:
            ssdt_content += "\n    External (WOLE, FieldUnitObj)"
        if uswe_object or wole_object:
            ssdt_content += """\n
    Scope (\\)
    {
        If (_OSI ("Darwin"))
        {"""
            if uswe_object:
                ssdt_content += "\n            USWE = Zero"
            if wole_object:
                ssdt_content += "\n            WOLE = Zero"
            ssdt_content += """        }
    }"""
        if gprw_method:
            ssdt_content += """
    Method (GPRW, 2, NotSerialized)
    {
        If (_OSI ("Darwin"))
        {
            If ((0x6D == Arg0))
            {
                Return (Package ()
                {
                    0x6D, 
                    Zero
                })
            }

            If ((0x0D == Arg0))
            {
                Return (Package ()
                {
                    0x0D, 
                    Zero
                })
            }
        }
        Return (XPRW (Arg0, Arg1))
    }"""
        if uprw_method:
            ssdt_content += """
    Method (UPRW, 2, NotSerialized)
    {
        If (_OSI ("Darwin"))
        {
            If ((0x6D == Arg0))
            {
                Return (Package ()
                {
                    0x6D, 
                    Zero
                })
            }

            If ((0x0D == Arg0))
            {
                Return (Package ()
                {
                    0x0D, 
                    Zero
                })
            }
        }
        Return (XPRW (Arg0, Arg1))
    }"""
        ssdt_content += "\n}"

        if gprw_method or uprw_method or uswe_object or wole_object:
            return {
                "Add": [
                    {
                        "Comment": ssdt_name + ".aml",
                        "Enabled": self.write_ssdt(ssdt_name, ssdt_content),
                        "Path": ssdt_name + ".aml"
                    }
                ],
                "Patch": patches
            }

    def fix_uncore_bridge(self):
        unc0_device = self.acpi.get_device_paths("UNC0", self.dsdt)

        if not unc0_device:
            return
        
        ssdt_name = "SSDT-UNC"
        ssdt_content = """
// Resource: https://github.com/acidanthera/OpenCorePkg/blob/master/Docs/AcpiSamples/Source/SSDT-UNC.dsl

/*
 * Discovered on X99-series.
 * These platforms have uncore PCI bridges for 4 CPU sockets
 * present in ACPI despite having none physically.
 *
 * Under normal conditions these are disabled depending on
 * CPU presence in the socket via Processor Bit Mask (PRBM),
 * but on X99 this code is unused or broken as such bridges
 * simply do not exist. We fix that by writing 0 to PRBM.
 *
 * Doing so is important as starting with macOS 11 IOPCIFamily
 * will crash as soon as it sees non-existent PCI bridges.
 */

DefinitionBlock ("", "SSDT", 2, "ZPSS", "UNC", 0x00000000)
{
    External (_SB.UNC0, DeviceObj)
    External (PRBM, IntObj)

    Scope (_SB.UNC0)
    {
        Method (_INI, 0, NotSerialized)
        {
            // In most cases this patch does benefit all operating systems,
            // yet on select pre-Windows 10 it may cause issues.
            // Remove If (_OSI ("Darwin")) in case you have none.
            If (_OSI ("Darwin")) {
                PRBM = 0
            }
        }
    }
}"""

        return {
            "Add": [
                {
                    "Comment": ssdt_name + ".aml",
                    "Enabled": self.write_ssdt(ssdt_name, ssdt_content),
                    "Path": ssdt_name + ".aml"
                }
            ]
        }

    def operating_system_patch(self):
        ssdt_name = "SSDT-XOSI"
        ssdt_content = """
// Resource: https://github.com/dortania/Getting-Started-With-ACPI/blob/master/extra-files/decompiled/SSDT-XOSI.dsl

DefinitionBlock ("", "SSDT", 2, "ZPSS", "XOSI", 0x00001000)
{
    Method (XOSI, 1, NotSerialized)
    {
        // Based off of: 
        // https://docs.microsoft.com/en-us/windows-hardware/drivers/acpi/winacpi-osi#_osi-strings-for-windows-operating-systems
        // Add OSes from the below list as needed, most only check up to Windows 2015
        // but check what your DSDT looks for
        Store (Package ()
        {
[[OSIStrings]]
        }, Local0)
        If (_OSI ("Darwin"))
        {
            Return (LNotEqual (Match (Local0, MEQ, Arg0, MTR, Zero, Zero), Ones))
        }
        Else
        {
            Return (_OSI (Arg0))
        }
    }
}""".replace("[[OSIStrings]]", "\n,".join(["            \"{}\"".format(osi_string) for target_os, osi_string in self.osi_strings.items() if osi_string in self.dsdt.get("table")]))
        
        patches = []

        osid = self.acpi.get_method_paths("OSID", self.dsdt)
        if osid:
            patches.append({
                "Comment": "OSID to XSID rename - must come before _OSI to XOSI rename!",
                "Find": "4F534944",
                "Replace": "58534944"
            })

        osif = self.acpi.get_method_paths("OSIF", self.dsdt)
        if osif:
            patches.append({
                "Comment": "OSIF to XSIF rename - must come before _OSI to XOSI rename!",
                "Find": "4F534946",
                "Replace": "58534946"
            })

        patches.append({
            "Comment": "_OSI to XOSI rename - requires SSDT-XOSI.aml",
            "Find": "5F4F5349",
            "Replace": "584F5349"
        })
        
        return {
            "Add": [
                {
                    "Comment": ssdt_name + ".aml",
                    "Enabled": self.write_ssdt(ssdt_name, ssdt_content),
                    "Path": ssdt_name + ".aml"
                }
            ],
            "Patch": patches
        }

    def surface_laptop_special_patch(self):
        ssdt_name = "SSDT-SURFACE"
        ssdt_content = """
DefinitionBlock ("", "SSDT", 2, "ZPSS", "SURFACE", 0x00001000)
{
    External (_SB_.PCI0, DeviceObj)
    External (GPRW, MethodObj)    // 2 Arguments

    If (_OSI ("Darwin"))
    {
        Scope (_SB)
        {
            Device (ALS0)
            {
                Name (_HID, "ACPI0008" /* Ambient Light Sensor Device */)  // _HID: Hardware ID
                Name (_CID, "smc-als")  // _CID: Compatible ID
                Name (_ALI, 0x012C)  // _ALI: Ambient Light Illuminance
                Name (_ALR, Package (0x05)  // _ALR: Ambient Light Response
                {
                    Package (0x02)
                    {
                        0x46, 
                        Zero
                    }, 

                    Package (0x02)
                    {
                        0x49, 
                        0x0A
                    }, 

                    Package (0x02)
                    {
                        0x55, 
                        0x50
                    }, 

                    Package (0x02)
                    {
                        0x64, 
                        0x012C
                    }, 

                    Package (0x02)
                    {
                        0x96, 
                        0x03E8
                    }
                })
                Method (XALI, 1, Serialized)
                {
                    _ALI = Arg0
                }
            }

            Device (ADP0)
            {
                Name (_HID, "ACPI0003" /* Power Source Device */)  // _HID: Hardware ID
                Name (SPSR, Zero)
                Method (_PRW, 0, NotSerialized)  // _PRW: Power Resources for Wake
                {
                    Return (GPRW (0x6D, 0x04))
                }

                Method (_STA, 0, NotSerialized)  // _STA: Status
                {
                    Return (0x0F)
                }

                Method (XPSR, 1, Serialized)
                {
                    If ((Arg0 == Zero))
                    {
                        SPSR = Zero
                    }
                    ElseIf ((Arg0 == One))
                    {
                        SPSR = One
                    }

                    Notify (ADP0, 0x80) // Status Change
                }

                Method (_PSR, 0, Serialized)  // _PSR: Power Source
                {
                    Return (SPSR) /* \\_SB_.ADP0.SPSR */
                }

                Method (_PCL, 0, NotSerialized)  // _PCL: Power Consumer List
                {
                    Return (\\_SB)
                }
            }

            Device (BAT0)
            {
                Name (_HID, EisaId ("PNP0C0A") /* Control Method Battery */)  // _HID: Hardware ID
                Name (_UID, Zero)  // _UID: Unique ID
                Name (_PCL, Package (0x01)  // _PCL: Power Consumer List
                {
                    _SB
                })
                Method (_STA, 0, NotSerialized)  // _STA: Status
                {
                    Return (0x1F)
                }
            }
        }

        Scope (_SB.PCI0)
        {
            Device (IPTS)
            {
                Name (_ADR, 0x00160004)  // _ADR: Address
            }
        }
    }
}
""" 

        return {
            "Add": [
                {
                    "Comment": ssdt_name + ".aml",
                    "Enabled": self.write_ssdt(ssdt_name, ssdt_content),
                    "Path": ssdt_name + ".aml"
                }
            ]
        }

    def find_line_start(self, text, index):
        current_idx = index
        while current_idx > 0:
            if text[current_idx] == '\n':
                return current_idx + 1
            current_idx -= 1
        return 0

    def extract_line(self, text, index):
        start_idx = self.find_line_start(text, index)
        end_idx = text.index("\n", start_idx) + 1 if "\n" in text[start_idx:] else len(text)
        return text[start_idx:end_idx].strip(), start_idx, end_idx

    def extract_block_content(self, text, start_idx):
        try:
            block_start = text.index("{", start_idx)
            
            brace_count = 1
            pos = block_start + 1
            
            while brace_count > 0 and pos < len(text):
                if text[pos] == '{':
                    brace_count += 1
                elif text[pos] == '}':
                    brace_count -= 1
                pos += 1
            
            if brace_count == 0:
                return text[block_start:pos]
        except ValueError as e:
            pass

        return ""

    def parse_field_line(self, line):
        try:
            if "//" in line:
                line = line.split("//")[0].strip()
            
            parts = line.split(",")
            
            if len(parts) >= 2:
                field_name = parts[0].strip()
                
                size_part = parts[1].strip()
                try:
                    field_size = int(size_part)
                except ValueError:
                    return None, None
                        
                return field_name, field_size
        except (ValueError, IndexError) as e:
            pass
        
        return None, None

    def process_embedded_control_region(self, table, start_idx):
        try:
            embed_control_idx = table.index("EmbeddedControl", start_idx)
            line, start_line_idx, end_line_idx = self.extract_line(table, embed_control_idx)
            
            region_name = line.split("(")[1].split(",")[0].strip()
            
            return region_name, end_line_idx
        except (ValueError, IndexError) as e:
            return None, start_idx + 1

    def process_field_definition(self, table, region_name, start_idx):
        fields = []
        try:
            field_pattern = f"Field ({region_name}"
            if field_pattern not in table[start_idx:]:
                return fields, len(table)
                
            field_start_idx = table.index(field_pattern, start_idx)
            field_line, field_start_line_idx, field_end_line_idx = self.extract_line(table, field_start_idx)
            
            field_block = self.extract_block_content(table, field_end_line_idx)
            
            for line in field_block.splitlines():
                line = line.strip()
                if not line or line in ["{", "}"]:
                    continue
                    
                field_name, field_size = self.parse_field_line(line)
                if field_name and field_size is not None:
                    field_info = {
                        "name": field_name,
                        "size": field_size,
                    }
                    fields.append(field_info)
            
            return fields, field_end_line_idx
        except (ValueError, IndexError) as e:
            return fields, start_idx + 1

    def battery_status_patch(self):
        if not self.dsdt:
            return False

        search_start_idx = 0
        all_fields = []
        
        while "EmbeddedControl" in self.dsdt.get("table")[search_start_idx:]:
            region_name, search_start_idx = self.process_embedded_control_region(self.dsdt.get("table"), search_start_idx)
            
            if not region_name:
                continue
                
            current_idx = search_start_idx
            region_fields = []
            
            while True:
                fields, next_idx = self.process_field_definition(self.dsdt.get("table"), region_name, current_idx)
                
                if not fields or next_idx <= current_idx:
                    break
                    
                region_fields.extend(fields)
                current_idx = next_idx
                
                if f"Field ({region_name}" not in self.dsdt.get("table")[current_idx:]:
                    break
            
            all_fields.extend(region_fields)

        return any(f["size"] > 8 for f in all_fields)

    def dropping_the_table(self, signature=None, oemtableid=None):
        table_data = self.acpi.get_table_with_signature(signature) or self.acpi.get_table_with_id(oemtableid)

        if not table_data:
            return
                
        return {
            "All": True,
            "Comment": "Delete {}".format((signature or oemtableid).rstrip(b"\x00").decode()),
            "Enabled": True,
            "OemTableId": self.utils.hex_to_bytes(binascii.hexlify(table_data.get("id")).decode()),
            "TableLength": table_data.get("length"),
            "TableSignature": self.utils.hex_to_bytes(binascii.hexlify(table_data.get("signature")).decode())
        }

    def fix_apic_processor_id(self):
        self.apic = self.acpi.get_table_with_signature("APIC")
        new_apic = ""

        if not self.apic:
            return

        for table_name in self.sorted_nicely(list(self.acpi.acpi_tables)):
            table = self.acpi.acpi_tables[table_name]
            processors = self.acpi.get_processor_paths(table=table)

            if not processors:
                continue

            processor_index = -1
            apic_length = len(self.apic.get("lines"))
            skip_unknown_subtable = False
            for index in range(apic_length):
                line = self.apic.get("lines")[index]

                if "Unknown" in line:
                    skip_unknown_subtable = not skip_unknown_subtable
                    continue

                if skip_unknown_subtable:
                    continue

                if "Subtable Type" in line and "[Processor Local APIC]" in line:
                    processor_index += 1
                    apic_processor_id = self.apic["lines"][index + 2][-2:]
                    try:
                        processor_id = table.get("lines")[processors[processor_index][1]].split(", ")[1][2:]
                    except:
                        return
                    if processor_index == 0 and apic_processor_id == processor_id:
                        return
                    self.apic["lines"][index + 2] = self.apic["lines"][index + 2][:-2] + processor_id

                new_apic += line + "\n"

            if processor_index != -1:
                return {
                    "Add": [
                        {
                            "Comment": "APIC.aml",
                            "Enabled": self.write_ssdt("APIC", new_apic),
                            "Path": "APIC.aml"
                        }
                    ],
                    "Delete": [
                        self.dropping_the_table("APIC")
                    ]
                }

    def disable_usb_hub_devices(self):
        ssdt_name = "SSDT-USB-Reset"
        patches = []
        ssdt_content = """
DefinitionBlock ("", "SSDT", 2, "ZPSS", "UsbReset", 0x00001000)
{"""

        rhub_devices = self.acpi.get_device_paths("RHUB")
        rhub_devices.extend(self.acpi.get_device_paths("HUBN"))
        rhub_devices.extend(self.acpi.get_device_paths("URTH"))

        if not rhub_devices:
            return
        
        for device in rhub_devices:
            device_path = device[0]

            sta = self.get_sta_var(var=None, device=device_path, dev_hid=None, dev_name=device_path.split(".")[-1], table=self.dsdt)
            patches.extend(sta.get("patches", []))

            ssdt_content += """
    External ([[device_path]], DeviceObj)

    Scope ([[device_path]])
    {
        Method (_STA, 0, NotSerialized)  // _STA: Status
        {
            If (_OSI ("Darwin"))
            {
                Return (Zero)
            }
            Else
            {
                Return (0x0F)
            }
        }
    }
""".replace("[[device_path]]", device_path)
            
        ssdt_content += "\n}"

        return {
            "Add": [
                {
                    "Comment": ssdt_name + ".aml",
                    "Enabled": self.write_ssdt(ssdt_name, ssdt_content),
                    "Path": ssdt_name + ".aml"
                }
            ],
            "Patch": patches
        }
    
    def return_thermal_zone(self):
        ssdt_name = "SSDT-WMIS"
        ssdt_content = """
// Resource: https://github.com/zhen-zen/YogaSMC/blob/master/YogaSMC/SSDTSample/SSDT-WMIS.dsl

/*
 * Sample SSDT to fix sensor return
 *
 * Certain models forget to return result from ThermalZone:
 *
 * Method (WQBI, 1, NotSerialized)
 * {
 *     \\_TZ.WQBI (Arg0)
 * }
 *
 * So we have to patch it for correct reporting.
 * Rename Method (WQBI, 1, N) to XQBI
 * (ThermalZone one usually has Serialized type)
 *
 * Find: 57514249 01 // WQBI
 * Repl: 58514249 01 // XQBI 
 *
 * MethodFlags :=
 * bit 0-2: ArgCount (0-7)
 * bit 3:   SerializeFlag
 *          0 NotSerialized
 *          1 Serialized
 */
DefinitionBlock ("", "SSDT", 2, "ZPSS", "WMIS", 0x00000000)
{
    External (_TZ.WQBI, MethodObj)    // Method in ThermalZone

    Method (_SB.WMIS.WQBI, 1, NotSerialized)
    {
        Return (\\_TZ.WQBI (Arg0))
    }
}
"""
        for table_name in self.sorted_nicely(list(self.acpi.acpi_tables)):
            table = self.acpi.acpi_tables[table_name]
            wqbi_method = self.acpi.get_method_paths("WQBI", table=table)

            if not wqbi_method:
                continue

            return {
                "Add": [
                    {
                        "Comment": ssdt_name + ".aml",
                        "Enabled": self.write_ssdt(ssdt_name, ssdt_content),
                        "Path": ssdt_name + ".aml"
                    }
                ],
                "Patch": [
                    {
                        "Comment": "WQBI to XQBI Rename",
                        "Find": "5751424901",
                        "Replace": "5851424901"
                    }
                ]
            }

    def drop_cpu_tables(self):
        cpu_tables = ["CpuPm", "Cpu0Ist"]
        deletes = []

        for table_name in cpu_tables:
            padded_table_id = self.get_data(table_name, pad_to=8)
            table_entry = self.dropping_the_table(oemtableid=padded_table_id)
            if table_entry:
                deletes.append(table_entry)

        return {
            "Delete": deletes
        }

    def select_acpi_tables(self):
        while True:
            self.utils.head("选择ACPI表")
            print("")
            print("Q. 退出")
            print(" ")
            menu = self.utils.request_input("请在此处拖放ACPI表文件夹: ")
            if menu.lower() == "q":
                self.utils.exit_program()
            path = self.utils.normalize_path(menu)
            if not path: 
                continue
            return self.read_acpi_tables(path)

    def get_patch_index(self, name):
        for index, patch in enumerate(self.patches):
            if patch.name == name:
                return index
        return None

    def select_acpi_patches(self, hardware_report, disabled_devices):
        selected_patches = []

        if  "Laptop" in hardware_report.get("Motherboard").get("Platform") and \
            "Integrated GPU" in list(hardware_report.get("GPU").items())[-1][-1].get("Device Type") and \
            not "SURFACE" in hardware_report.get("Motherboard").get("Name"):
            selected_patches.append("ALS")
            selected_patches.append("PNLF")

        if self.is_intel_hedt_cpu(hardware_report.get("CPU").get("Processor Name"), hardware_report.get("CPU").get("Codename")):
            selected_patches.append("APIC")

        for device_name, device_info in disabled_devices.items():
            if "PCI" in device_info.get("Bus Type", "PCI"):
                selected_patches.append("Disable Devices")

        selected_patches.append("FakeEC")

        if "HP " in hardware_report.get("Motherboard").get("Name"):
            selected_patches.append("CMOS")

        if hardware_report.get("Motherboard").get("Chipset") in chipset_data.IntelChipsets[-7:]:
            selected_patches.append("RCSP")

        if "Laptop" in hardware_report.get("Motherboard").get("Platform") and hardware_report.get("CPU").get("Codename") in cpu_data.IntelCPUGenerations[50:]:
            selected_patches.append("FixHPET")

        for device_name, device_info in hardware_report.get("System Devices", {}).items():
            device_id = device_info.get("Device ID")

            if not device_id in ("8086-1C3A", "8086-1E3A"):
                continue
            
            if  "Sandy Bridge" in hardware_report.get("CPU").get("Codename") and device_id in "8086-1E3A" or \
                "Ivy Bridge" in hardware_report.get("CPU").get("Codename") and device_id in "8086-1C3A":
                selected_patches.append("IMEI")

        if hardware_report.get("Motherboard").get("Chipset") in chipset_data.IntelChipsets[100:112]:
            selected_patches.append("PMC")

        if "Sandy Bridge" in hardware_report.get("CPU").get("Codename") or "Ivy Bridge" in hardware_report.get("CPU").get("Codename"):
            selected_patches.append("PM (Legacy)")
        else:
            selected_patches.append("PLUG")

        if all(network_props.get("Bus Type") == "USB" for network_props in hardware_report.get("Network", {}).values()):
            selected_patches.append("RMNE")

        if hardware_report.get("Motherboard").get("Chipset") in chipset_data.IntelChipsets[62:64] + chipset_data.IntelChipsets[90:100]:
            selected_patches.append("RTC0")

        if "AMD" in hardware_report.get("CPU").get("Manufacturer") or hardware_report.get("CPU").get("Codename") in cpu_data.IntelCPUGenerations[:40]:
            selected_patches.append("RTCAWAC")

        if "Intel" in hardware_report.get("CPU").get("Manufacturer"):
            selected_patches.append("BUS0")

        if "SURFACE" in hardware_report.get("Motherboard").get("Name"):
            selected_patches.append("Surface Patch")
        else:
            if "Intel" in hardware_report.get("CPU").get("Manufacturer"):
                for device_name, device_info in hardware_report.get("Input", {}).items():
                    if "I2C" in device_info.get("Device Type", "None"):
                        selected_patches.append("GPI0")

        if hardware_report.get("Motherboard").get("Chipset") in chipset_data.IntelChipsets[27:28] + chipset_data.IntelChipsets[62:64]:
            selected_patches.append("UNC")
        
        if "AMD" in hardware_report.get("CPU").get("Manufacturer") or hardware_report.get("Motherboard").get("Chipset") in chipset_data.IntelChipsets[112:]:
            selected_patches.append("USB Reset")

        selected_patches.append("USBX")
        
        if "Laptop" in hardware_report.get("Motherboard").get("Platform"):
            selected_patches.append("BATP")
            selected_patches.append("XOSI")

        for device_name, device_info in hardware_report.get("System Devices", {}).items():
            if device_info.get("Bus Type") == "ACPI" and device_info.get("Device") in pci_data.YogaHIDs:
                selected_patches.append("WMIS")

        for patch in self.patches:
            patch.checked = patch.name in selected_patches
    
    def customize_patch_selection(self):
        while True:
            contents = []
            contents.append("")
            contents.append("可用补丁列表:")
            contents.append("")
            for index, kext in enumerate(self.patches, start=1):
                checkbox = "[*]" if kext.checked else "[ ]"
                
                line = "{} {:2}. {:15} - {:60}".format(checkbox, index, kext.name, kext.description)
                if kext.checked:
                    line = "\033[1;32m{}\033[0m".format(line)
                contents.append(line)
            contents.append("")
            contents.append("\033[1;93m注意:\033[0m 您可以通过输入用逗号分隔的索引来选择多个kext（例如：'1, 2, 3'）。")
            contents.append("")
            contents.append("B. 返回")
            contents.append("Q. 退出")
            contents.append("")
            content = "\n".join(contents)

            self.utils.adjust_window_size(content)
            self.utils.head("自定义ACPI补丁选择", resize=False)
            print(content)
            option = self.utils.request_input("选择您的选项: ")
            if option.lower() == "q":
                self.utils.exit_program()
            if option.lower() == "b":
                return

            indices = [int(i.strip()) -1 for i in option.split(",") if i.strip().isdigit()]
    
            for index in indices:
                if index >= 0 and index < len(self.patches):
                    patch = self.patches[index]
                    patch.checked = not patch.checked