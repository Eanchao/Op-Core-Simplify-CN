# 原始来源: https://github.com/corpnewt/SSDTTime/blob/64446d553fcbc14a4e6ebf3d8d16e3357b5cbf50/Scripts/dsdt.py

import os, errno, tempfile, shutil, plistlib, sys, binascii, zipfile, getpass, re
from Scripts import github
from Scripts import resource_fetcher
from Scripts import run
from Scripts import utils

class DSDT:
    def __init__(self, **kwargs):
        #self.dl = downloader.Downloader()
        self.github = github.Github()
        self.fetcher = resource_fetcher.ResourceFetcher()
        self.r  = run.Run()
        #self.u  = utils.Utils("SSDT Time")
        self.u = utils.Utils()
        self.iasl_url_macOS = "https://raw.githubusercontent.com/acidanthera/MaciASL/master/Dist/iasl-stable"
        self.iasl_url_macOS_legacy = "https://raw.githubusercontent.com/acidanthera/MaciASL/master/Dist/iasl-legacy"
        self.iasl_url_linux = "https://raw.githubusercontent.com/corpnewt/linux_iasl/main/iasl.zip"
        self.iasl_url_linux_legacy = "https://raw.githubusercontent.com/corpnewt/iasl-legacy/main/iasl-legacy-linux.zip"
        self.acpi_binary_tools = "https://github.com/acpica/acpica/releases"
        self.iasl_url_windows_legacy = "https://raw.githubusercontent.com/corpnewt/iasl-legacy/main/iasl-legacy-windows.zip"
        self.h = {} # {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        self.iasl = self.check_iasl()
        #self.iasl_legacy = self.check_iasl(legacy=True)
        if not self.iasl:
            url = self.acpi_binary_tools if os.name=="nt" else \
            self.iasl_url_macOS if sys.platform=="darwin" else \
            self.iasl_url_linux if sys.platform.startswith("linux") else None
            exception = "Could not locate or download iasl!"
            if url:
                exception += "\n\nPlease manually download {} from:\n - {}\n\nAnd place in:\n - {}\n".format(
                    "\"iasl-win-YYYYMMDD.zip\" and extract iasl.exe" if os.name=="nt" else "iasl",
                    url,
                    os.path.dirname(os.path.realpath(__file__))
                )
            raise Exception(exception)
        self.allowed_signatures = (b"APIC",b"DMAR",b"DSDT",b"SSDT")
        self.mixed_listing      = (b"DSDT",b"SSDT")
        self.acpi_tables = {}
        # 设置正则表达式匹配
        self.hex_match  = re.compile(r"^\s*[0-9A-F]{4,}:(\s[0-9A-F]{2})+(\s+\/\/.*)?$")
        self.type_match = re.compile(r".*(?P<type>Processor|Scope|Device|Method|Name) \((?P<name>[^,\)]+).*")

    def _table_signature(self, table_path, table_name = None):
        path = os.path.join(table_path,table_name) if table_name else table_path
        if not os.path.isfile(path):
            return None
        # 尝试加载文件并读取前4个字节来验证签名
        with open(path,"rb") as f:
            try:
                sig = f.read(4)
                return sig
            except:
                pass
        return None

    def table_is_valid(self, table_path, table_name = None):
        return self._table_signature(table_path,table_name=table_name) in self.allowed_signatures

    def get_ascii_print(self, data):
        # 辅助函数：通过用?替换不可打印字符来清理数据
        unprintables = False
        ascii_string = ""
        for b in data:
            if not isinstance(b,int):
                try: b = ord(b)
                except: pass
            if ord(" ") <= b < ord("~"):
                ascii_string += chr(b)
            else:
                ascii_string += "?"
                unprintables = True
        return (unprintables,ascii_string)

    def load(self, table_path):
        # 尝试加载传入的文件 - 如果传入的是目录，则加载目录中所有.aml和.dat文件
        cwd = os.getcwd()
        temp = None
        target_files = {}
        failed = []
        try:
            if os.path.isdir(table_path):
                # 得到一个目录 - 收集所有文件
                # 收集目录中的有效文件
                valid_files = [x for x in os.listdir(table_path) if self.table_is_valid(table_path, x)]
            elif os.path.isfile(table_path):
                # 只加载一个表
                valid_files = [table_path]
            else:
                # 不是有效的路径
                raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), table_path)

            if not valid_files:
                # 没有找到有效的文件
                raise FileNotFoundError(
                    errno.ENOENT,
                    os.strerror(errno.ENOENT),
                    "没有在 {} 中找到有效的 .aml/.dat 文件".format(table_path)
                )

            # 创建一个临时目录并将所有文件复制到那里
            temp = tempfile.mkdtemp()
            for file in valid_files:
                shutil.copy(
                    os.path.join(table_path, file),
                    temp
                )

            # 构建临时文件夹中所有目标文件的列表 - 并保存每个文件的disassembled_name用于后续验证
            list_dir = os.listdir(temp)
            for x in list_dir:
                if len(list_dir) > 1 and not self.table_is_valid(temp, x):
                    continue  # 当传递多个文件时跳过无效文件
                name_ext = [y for y in os.path.basename(x).split(".") if y]
                if name_ext and name_ext[-1].lower() in ("asl", "dsl"):
                    continue  # 跳过任何已经反汇编的文件
                target_files[x] = {
                    "assembled_name": os.path.basename(x),
                    "disassembled_name": ".".join(x.split(".")[:-1]) + ".dsl",
                }

            if not target_files:
                # 不知何故我们最终一个都没有？
                raise FileNotFoundError(
                    errno.ENOENT,
                    os.strerror(errno.ENOENT),
                    "没有在 {} 中找到有效的 .aml/.dat 文件".format(table_path)
                )

            os.chdir(temp)
            # 生成并运行命令
            dsdt_or_ssdt = [x for x in list(target_files) if self._table_signature(temp, x) in self.mixed_listing]
            other_tables = [x for x in list(target_files) if x not in dsdt_or_ssdt]
            out_d = ("", "", 0)
            out_t = ("", "", 0)

            def exists(folder_path, file_name):
                # 辅助函数，确保文件存在且大小不为零
                check_path = os.path.join(folder_path,file_name)
                if os.path.isfile(check_path) and os.stat(check_path).st_size > 0:
                    return True
                return False
            
            # 首先检查我们的 DSDT 和 SSDT
            if dsdt_or_ssdt:
                args = [self.iasl,"-da","-dl","-l"]+list(dsdt_or_ssdt)
                out_d = self.r.run({"args":args})
                if out_d[2] != 0:
                    # 如果上述失败，尝试不使用 `-da` 运行
                    args = [self.iasl,"-dl","-l"]+list(dsdt_or_ssdt)
                    out_d = self.r.run({"args":args})
                # 获取反汇编失败的名称列表
                fail_temp = []
                for x in dsdt_or_ssdt:
                    if not exists(temp,target_files[x]["disassembled_name"]):
                        fail_temp.append(x)
                # 让我们尝试单独反汇编任何失败的表
                for x in fail_temp:
                    args = [self.iasl,"-dl","-l",x]
                    self.r.run({"args":args})
                    if not exists(temp,target_files[x]["disassembled_name"]):
                        failed.append(x)
            # 检查其他表（DMAR、APIC 等）
            if other_tables:
                args = [self.iasl]+list(other_tables)
                out_t = self.r.run({"args":args})
                # 获取反汇编失败的名称列表
                for x in other_tables:
                    if not exists(temp,target_files[x]["disassembled_name"]):
                        failed.append(x)
            if len(failed) == len(target_files):
                raise Exception("Failed to disassemble - {}".format(", ".join(failed)))
            # 现在实际处理这些表
            to_remove = []
            for file in target_files:
                # 我们需要将.aml和.dsl文件加载到内存中并获取路径和作用域
                if not exists(temp,target_files[file]["disassembled_name"]):
                    to_remove.append(file)
                    continue
                with open(os.path.join(temp,target_files[file]["disassembled_name"]),"r") as f:
                    target_files[file]["table"] = f.read()
                    # 移除开头的编译器信息
                    if target_files[file]["table"].startswith("/*"):
                        target_files[file]["table"] = "*/".join(target_files[file]["table"].split("*/")[1:]).strip()
                    # 检查"Table Header:"或"Raw Table Data: Length"，并移除最后一次出现后的所有内容
                    for h in ("\nTable Header:","\nRaw Table Data: Length"):
                        if h in target_files[file]["table"]:
                            target_files[file]["table"] = h.join(target_files[file]["table"].split(h)[:-1]).rstrip()
                            break # 在第一次匹配时退出
                    target_files[file]["lines"] = target_files[file]["table"].split("\n")
                    target_files[file]["scopes"] = self.get_scopes(table=target_files[file])
                    target_files[file]["paths"] = self.get_paths(table=target_files[file])
                with open(os.path.join(temp,file),"rb") as f:
                    table_bytes = f.read()
                    target_files[file]["raw"] = table_bytes
                    # 让我们读取表头部并获取所需信息
                    #
                    # [0:4]   = 表签名
                    # [4:8]   = 长度（小端序）
                    # [8]     = 合规性修订版本
                    # [9]     = 校验和
                    # [10:16] = OEM ID（6个字符，右侧用\x00填充）
                    # [16:24] = 表ID（8个字符，右侧用\x00填充）
                    # [24:28] = OEM修订版本（小端序）
                    # 
                    target_files[file]["signature"] = table_bytes[0:4]
                    target_files[file]["revision"]  = table_bytes[8]
                    target_files[file]["oem"]       = table_bytes[10:16]
                    target_files[file]["id"]        = table_bytes[16:24]
                    target_files[file]["oem_revision"] = int(binascii.hexlify(table_bytes[24:28][::-1]),16)
                    target_files[file]["length"]    = len(table_bytes)
                    # 必要时获取签名、OEM和ID的可打印版本
                    for key in ("signature","oem","id"):
                        unprintable,ascii_string = self.get_ascii_print(target_files[file][key])
                        if unprintable:
                            target_files[file][key+"_ascii"] = ascii_string
                    # 在py2上转换为int，在py3上尝试将字节解码为字符串
                    if 2/3==0:
                        target_files[file]["revision"] = int(binascii.hexlify(target_files[file]["revision"]),16)
                # 反汇编程序在混合列表文件中省略了最后一行十六进制数据...很方便。不过我们应该能够手动重建它。
                last_hex = next((l for l in target_files[file]["lines"][::-1] if self.is_hex(l)),None)
                if last_hex:
                    # 获取冒号左侧的地址
                    addr = int(last_hex.split(":")[0].strip(),16)
                    # 获取冒号右侧的十六进制字节
                    hexs = last_hex.split(":")[1].split("//")[0].strip()
                    # 按照十六进制字节数增加地址
                    next_addr = addr+len(hexs.split())
                    # 现在我们需要获取末尾的字节
                    hexb = self.get_hex_bytes(hexs.replace(" ",""))
                    # 获取分割后的最后一次出现
                    remaining = target_files[file]["raw"].split(hexb)[-1]
                    # 以16个为一组进行迭代
                    for chunk in [remaining[i:i+16] for i in range(0,len(remaining),16)]:
                        # 构建一个新的字节字符串
                        hex_string = binascii.hexlify(chunk)
                        # 如果是python 3，解码字节
                        if 2/3!=0: hex_string = hex_string.decode()
                        # 确保所有字节都是大写
                        hex_string = hex_string.upper()
                        l = "   {}: {}".format(
                            hex(next_addr)[2:].upper().rjust(4,"0"),
                            " ".join([hex_string[i:i+2] for i in range(0,len(hex_string),2)])
                        )
                        # 增加我们的地址
                        next_addr += len(chunk)
                        # 添加我们的行
                        target_files[file]["lines"].append(l)
                        target_files[file]["table"] += "\n"+l
            # 移除任何未反汇编的内容
            for file in to_remove:
                target_files.pop(file,None)
        except Exception as e:
            print(e)
            return ({},failed)
        finally:
            os.chdir(cwd)
            if temp: shutil.rmtree(temp,ignore_errors=True)
        # 添加/更新我们加载的任何表
        for table in target_files:
            self.acpi_tables[table] = target_files[table]
        # 仅返回新加载的结果
        return (target_files, failed,)

    def get_latest_iasl(self):
        latest_release = self.github.get_latest_release("acpica", "acpica") or {}
        
        for line in latest_release.get("body", "").splitlines():
            if "iasl" in line and ".zip" in line:
                return line.split("\"")[1]

        for asset in latest_release.get("assets", []):
            if "/iasl" in asset.get("url") and ".zip" in asset.get("url"):
                return asset.get("url")
            
        return None
    
    def check_iasl(self, legacy=False, try_downloading=True):
        if sys.platform == "win32":
            targets = (os.path.join(os.path.dirname(os.path.realpath(__file__)), "iasl-legacy.exe" if legacy else "iasl.exe"),)
        else:
            if legacy:
                targets = (os.path.join(os.path.dirname(os.path.realpath(__file__)), "iasl-legacy"),)
            else:
                targets = (
                    os.path.join(os.path.dirname(os.path.realpath(__file__)), "iasl-dev"),
                    os.path.join(os.path.dirname(os.path.realpath(__file__)), "iasl-stable"),
                    os.path.join(os.path.dirname(os.path.realpath(__file__)), "iasl")
                )
        target = next((t for t in targets if os.path.exists(t)),None)
        if target or not try_downloading:
            # 要么找到了它 - 要么没有，并且我们已经尝试下载过
            return target
        # 需要下载
        temp = tempfile.mkdtemp()
        try:
            if sys.platform == "darwin":
                self._download_and_extract(temp,self.iasl_url_macOS_legacy if legacy else self.iasl_url_macOS)
            elif sys.platform.startswith("linux"):
                self._download_and_extract(temp,self.iasl_url_linux_legacy if legacy else self.iasl_url_linux)
            elif sys.platform == "win32":
                iasl_url_windows = self.iasl_url_windows_legacy if legacy else self.get_latest_iasl()
                if not iasl_url_windows: raise Exception("无法获取适用于 Windows 的最新 iASL")
                self._download_and_extract(temp,iasl_url_windows)
            else: 
                raise Exception("未知操作系统")
        except Exception as e:
            print("发生错误：(\n - {}".format(e))
        shutil.rmtree(temp, ignore_errors=True)
        # 下载后再次检查
        return self.check_iasl(legacy=legacy,try_downloading=False)

    def _download_and_extract(self, temp, url):
        self.u.head("正在收集文件")
        print("")
        print("请等待下载 iASL...")
        print("")
        ztemp = tempfile.mkdtemp(dir=temp)
        zfile = os.path.basename(url)
        #print("正在下载 {}".format(os.path.basename(url)))
        #self.dl.stream_to_file(url, os.path.join(ztemp,zfile), progress=False, headers=self.h)
        self.fetcher.download_and_save_file(url, os.path.join(ztemp,zfile))
        search_dir = ztemp
        if zfile.lower().endswith(".zip"):
            print(" - 正在解压")
            search_dir = tempfile.mkdtemp(dir=temp)
            # 使用内置工具解压 \o/
            with zipfile.ZipFile(os.path.join(ztemp,zfile)) as z:
                z.extractall(search_dir)
        script_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)))
        for x in os.listdir(search_dir):
            if x.lower().startswith(("iasl","acpidump")):
                # 找到了一个
                print(" - 找到 {}".format(x))
                if sys.platform != "win32":
                    print("   - 设置执行权限")
                    self.r.run({"args":["chmod","+x",os.path.join(search_dir,x)]})
                print("   - 正在复制到 {} 目录".format(os.path.basename(script_dir)))
                shutil.copy(os.path.join(search_dir,x), os.path.join(script_dir,x))

    def dump_tables(self, output, disassemble=False):
        # 辅助函数，用于将所有ACPI表转储到指定的输出路径
        self.u.head("正在转储 ACPI 表")
        print("")
        res = self.check_output(output)
        if os.name == "nt":
            target = os.path.join(os.path.dirname(os.path.realpath(__file__)),"acpidump.exe")
            if os.path.exists(target):
                # 转储到目标文件夹
                print("正在将表转储到 {}...".format(res))
                cwd = os.getcwd()
                os.chdir(res)
                out = self.r.run({"args":[target,"-b"]})
                os.chdir(cwd)
                if out[2] != 0:
                    print(" - {}".format(out[1]))
                    return
                # 确保我们有一个DSDT
                if not next((x for x in os.listdir(res) if x.lower().startswith("dsdt.")),None):
                    # 我们需要尝试单独转储DSDT - 这有时会在旧的Windows安装或奇怪的OEM机器上发生
                    print(" - 未找到 DSDT - 按签名转储...")
                    os.chdir(res)
                    out = self.r.run({"args":[target,"-b","-n","DSDT"]})
                    os.chdir(cwd)
                    if out[2] != 0:
                        print(" - {}".format(out[1]))
                        return
                # 遍历转储的文件并确保名称是大写的，并且使用的扩展名是.aml，而不是默认的.dat
                print("正在更新名称...")
                for f in os.listdir(res):
                    new_name = f.upper()
                    if new_name.endswith(".DAT"):
                        new_name = new_name[:-4]+".aml"
                    if new_name != f:
                        # 有些东西改变了 - 打印它并重命名
                        try:
                            os.rename(os.path.join(res,f),os.path.join(res,new_name))
                        except Exception as e:
                            print(" - {} -> {} 失败: {}".format(f,new_name,e))
                print("转储成功!")
                if disassemble:
                    return self.load(res)
                return res
            else:
                print("未能找到 acpidump.exe")
                return
        elif sys.platform.startswith("linux"):
            table_dir = "/sys/firmware/acpi/tables"
            if not os.path.isdir(table_dir):
                print("无法定位 {}!".format(table_dir))
                return
            print("正在将表复制到 {}...".format(res))
            copied_files = []
            for table in os.listdir(table_dir):
                if not os.path.isfile(os.path.join(table_dir,table)):
                    continue # We only want files
                target_path = os.path.join(res,table.upper()+".aml")
                out = self.r.run({"args":["sudo","cp",os.path.join(table_dir,table),target_path]})
                if out[2] != 0:
                    print(" - {}".format(out[1]))
                    return
                out = self.r.run({"args":["sudo","chown",getpass.getuser(), target_path]})
                if out[2] != 0:
                    print(" - {}".format(out[1]))
                    return
            print("转储成功!")
            if disassemble:
                return self.load(res)
            return res

    def check_output(self, output):
        t_folder = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), output)
        if not os.path.isdir(t_folder):
            os.makedirs(t_folder)
        return t_folder

    def get_hex_from_int(self, total, pad_to = 4):
        hex_str = hex(total)[2:].upper().rjust(pad_to,"0")
        return "".join([hex_str[i:i + 2] for i in range(0, len(hex_str), 2)][::-1])

    def get_hex(self, line):
        # strip the header and commented end
        return line.split(":")[1].split("//")[0].replace(" ","")

    def get_line(self, line):
        # 去除注释部分 - 但保留空格
        line = line.split("//")[0]
        if ":" in line:
            return line.split(":")[1]
        return line

    def get_hex_bytes(self, line):
        return binascii.unhexlify(line)

    def get_str_bytes(self, value):
        if 2/3!=0 and isinstance(value,str):
            value = value.encode()
        return value

    def get_table_with_id(self, table_id):
        table_id = self.get_str_bytes(table_id)
        return next((v for k,v in self.acpi_tables.items() if table_id == v.get("id")),None)

    def get_table_with_signature(self, table_sig):
        table_sig = self.get_str_bytes(table_sig)
        return next((v for k,v in self.acpi_tables.items() if table_sig == v.get("signature")),None)
    
    def get_table(self, table_id_or_sig):
        table_id_or_sig = self.get_str_bytes(table_id_or_sig)
        return next((v for k,v in self.acpi_tables.items() if table_id_or_sig in (v.get("signature"),v.get("id"))),None)

    def get_dsdt(self):
        return self.get_table_with_signature("DSDT")

    def get_dsdt_or_only(self):
        dsdt = self.get_dsdt()
        if dsdt: return dsdt
        # 确保只有一个表
        if len(self.acpi_tables) != 1:
            return None
        return list(self.acpi_tables.values())[0]

    def find_previous_hex(self, index=0, table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return ("",-1,-1)
        # 返回指定索引之前的十六进制数字集的索引
        start_index = -1
        end_index   = -1
        old_hex = True
        for i,line in enumerate(table.get("lines","")[index::-1]):
            if old_hex:
                if not self.is_hex(line):
                    # 跳出旧的十六进制区域
                    old_hex = False
                continue
            # 不在旧的十六进制区域 - 检查是否有新的十六进制
            if self.is_hex(line): # 检查是否有冒号，但不在注释中
                end_index = index-i
                hex_text,start_index = self.get_hex_ending_at(end_index,table=table)
                return (hex_text, start_index, end_index)
        return ("",start_index,end_index)
    
    def find_next_hex(self, index=0, table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return ("",-1,-1)
        # 返回指定索引之后的十六进制数字集的索引
        start_index = -1
        end_index   = -1
        old_hex = True
        for i,line in enumerate(table.get("lines","")[index:]):
            if old_hex:
                if not self.is_hex(line):
                    # 跳出旧的十六进制区域
                    old_hex = False
                continue
            # 不在旧的十六进制区域 - 检查是否有新的十六进制
            if self.is_hex(line): # 检查是否有冒号，但不在注释中
                start_index = i+index
                hex_text,end_index = self.get_hex_starting_at(start_index,table=table)
                return (hex_text, start_index, end_index)
        return ("",start_index,end_index)

    def is_hex(self, line):
        return self.hex_match.match(line) is not None

    def get_hex_starting_at(self, start_index, table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return ("",-1)
        # 返回十六进制数据和结束索引的元组
        hex_text = ""
        index = -1
        for i,x in enumerate(table.get("lines","")[start_index:]):
            if not self.is_hex(x):
                break
            hex_text += self.get_hex(x)
            index = i+start_index
        return (hex_text, index)

    def get_hex_ending_at(self, start_index, table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return ("",-1)
        # 返回十六进制数据和起始索引的元组
        hex_text = ""
        index = -1
        for i,x in enumerate(table.get("lines","")[start_index::-1]):
            if not self.is_hex(x):
                break
            hex_text = self.get_hex(x)+hex_text
            index = start_index-i
        return (hex_text, index)

    def get_shortest_unique_pad(self, current_hex, index, instance=0, table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return None
        try:    left_pad  = self.get_unique_pad(current_hex, index, False, instance, table=table)
        except: left_pad  = None
        try:    right_pad = self.get_unique_pad(current_hex, index, True, instance, table=table)
        except: right_pad = None
        try:    mid_pad   = self.get_unique_pad(current_hex, index, None, instance, table=table)
        except: mid_pad   = None
        if left_pad == right_pad == mid_pad is None: raise Exception("No unique pad found!")
        # 我们至少找到了一个唯一的填充
        min_pad = None
        for x in (left_pad,right_pad,mid_pad):
            if x is None: continue # 跳过
            if min_pad is None or len(x[0]+x[1]) < len(min_pad[0]+min_pad[1]):
                min_pad = x
        return min_pad

    def get_unique_pad(self, current_hex, index, direction=None, instance=0, table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: raise Exception("No valid table passed!")
        # 返回使传入的补丁唯一所需的任何填充
        # direction 可以是 True = 向前, False = 向后, None = 双向
        start_index = index
        line,last_index = self.get_hex_starting_at(index,table=table)
        if last_index == -1:
            raise Exception("Could not find hex starting at index {}!".format(index))
        first_line = line
        # 假设在索引处至少存在1字节的current_hex，因此如果我们还没有找到它，
        # 我们需要至少加载len(current_hex)-2的数据。
        while True:
            if current_hex in line or len(line) >= len(first_line)+len(current_hex):
                break # 假设我们已经达到了上限
            new_line,_index,last_index = self.find_next_hex(last_index, table=table)
            if last_index == -1:
                raise Exception("Hit end of file before passed hex was located!")
            # 追加新信息
            line += new_line
        if not current_hex in line:
            raise Exception("{} not found in table at index {}-{}!".format(current_hex,start_index,last_index))
        padl = padr = ""
        parts = line.split(current_hex)
        if instance >= len(parts)-1:
            raise Exception("Instance out of range!")
        linel = current_hex.join(parts[0:instance+1])
        liner = current_hex.join(parts[instance+1:])
        last_check = True # Default to forward
        while True:
            # Check if our hex string is unique
            check_bytes = self.get_hex_bytes(padl+current_hex+padr)
            if table["raw"].count(check_bytes) == 1: # Got it!
                break
            if direction == True or (direction is None and len(padr)<=len(padl)):
                # Let's check a forward byte
                if not len(liner):
                    # Need to grab more
                    liner, _index, last_index = self.find_next_hex(last_index, table=table)
                    if last_index == -1: raise Exception("Hit end of file before unique hex was found!")
                padr  = padr+liner[0:2]
                liner = liner[2:]
                continue
            if direction == False or (direction is None and len(padl)<=len(padr)):
                # Let's check a backward byte
                if not len(linel):
                    # Need to grab more
                    linel, start_index, _index = self.find_previous_hex(start_index, table=table)
                    if _index == -1: raise Exception("Hit end of file before unique hex was found!")
                padl  = linel[-2:]+padl
                linel = linel[:-2]
                continue
            break
        return (padl,padr)
    
    def get_devices(self,search=None,types=("Device (","Scope ("),strip_comments=False,table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return []
        # 返回格式为(Device/Scope, d_s_index, matched_index)的元组列表
        if search is None:
            return []
        last_device = None
        device_index = 0
        devices = []
        for index,line in enumerate(table.get("lines","")):
            if self.is_hex(line):
                continue
            line = self.get_line(line) if strip_comments else line
            if any ((x for x in types if x in line)):
                # Got a last_device match
                last_device = line
                device_index = index
            if search in line:
                # Got a search hit - add it
                devices.append((last_device,device_index,index))
        return devices

    def get_scope(self,starting_index=0,add_hex=False,strip_comments=False,table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return []
        # 从starting_index开始遍历作用域，直到退出作用域时返回
        brackets = None
        scope = []
        for line in table.get("lines","")[starting_index:]:
            if self.is_hex(line):
                if add_hex:
                    scope.append(line)
                continue
            line = self.get_line(line) if strip_comments else line
            scope.append(line)
            if brackets is None:
                if line.count("{"):
                    brackets = line.count("{")
                continue
            brackets = brackets + line.count("{") - line.count("}")
            if brackets <= 0:
                # We've exited the scope
                return scope
        return scope

    def get_scopes(self, table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return []
        scopes = []
        for index,line in enumerate(table.get("lines","")):
            if self.is_hex(line): continue
            if any(x in line for x in ("Processor (","Scope (","Device (","Method (","Name (")):
                scopes.append((line,index))
        return scopes

    def get_paths(self, table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return []
        # 设置完整路径列表和当前路径引用
        path_list  = []
        _path      = []
        brackets = 0
        for i,line in enumerate(table.get("lines",[])):
            if self.is_hex(line):
                # Skip hex
                continue
            line = self.get_line(line)
            brackets += line.count("{")-line.count("}")
            while len(_path):
                # Remove any path entries that are nested
                # equal to or further than our current set
                if _path[-1][-1] >= brackets:
                    del _path[-1]
                else:
                    break
            type_match = self.type_match.match(line)
            if type_match:
                # Add our path entry and save the full path
                # to the path list as needed
                _path.append((type_match.group("name"),brackets))
                if type_match.group("type") == "Scope":
                    continue
                # Ensure that we only consider non-Scope paths that aren't
                # already fully qualified with a \ prefix
                path = []
                for p in _path[::-1]:
                    path.append(p[0])
                    p_check = p[0].split(".")[0].rstrip("_")
                    if p_check.startswith("\\") or p_check in ("_SB","_PR"):
                        # Fully qualified - bail here
                        break
                path = ".".join(path[::-1]).split(".")
                # Properly qualify the path
                if len(path) and path[0] == "\\": path.pop(0)
                if any("^" in x for x in path): # Accommodate caret notation
                    new_path = []
                    for x in path:
                        if x.count("^"):
                            # Remove the last Y paths to account for going up a level
                            del new_path[-1*x.count("^"):]
                        new_path.append(x.replace("^","")) # Add the original, removing any ^ chars
                    path = new_path
                if not path:
                    continue
                # Ensure we strip trailing underscores for consistency
                padded_path = [("\\" if j==0 else"")+x.lstrip("\\").rstrip("_") for j,x in enumerate(path)]
                path_str = ".".join(padded_path)
                path_list.append((path_str,i,type_match.group("type")))
        return sorted(path_list)

    def get_path_of_type(self, obj_type="Device", obj="HPET", table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return []
        paths = []
        # 为所有传入的路径元素去除尾随下划线并标准化大小写
        obj = ".".join([x.rstrip("_").upper() for x in obj.split(".")])
        obj_type = obj_type.lower() if obj_type else obj_type
        for path in table.get("paths",[]):
            path_check = ".".join([x.rstrip("_").upper() for x in path[0].split(".")])
            if (obj_type and obj_type != path[2].lower()) or not path_check.endswith(obj):
                # 类型或对象不匹配 - 跳过
                continue
            paths.append(path)
        return sorted(paths)

    def get_device_paths(self, obj="HPET",table=None):
        return self.get_path_of_type(obj_type="Device",obj=obj,table=table)

    def get_method_paths(self, obj="_STA",table=None):
        return self.get_path_of_type(obj_type="Method",obj=obj,table=table)

    def get_name_paths(self, obj="CPU0",table=None):
        return self.get_path_of_type(obj_type="Name",obj=obj,table=table)

    def get_processor_paths(self, obj_type="Processor",table=None):
        return self.get_path_of_type(obj_type=obj_type,obj="",table=table)

    def get_device_paths_with_hid(self, hid="ACPI000E", table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return []
        devs = []
        for p in table.get("paths",[]):
            try:
                if p[0].endswith("._HID") and hid.upper() in table.get("lines")[p[1]]:
                    # 保存路径，从末尾去除._HID
                    devs.append(p[0][:-len("._HID")])
            except: continue
        devices = []
        # 再次遍历路径 - 保存与我们之前列表匹配的任何设备
        for p in table.get("paths",[]):
            if p[0] in devs and p[-1] == "Device":
                devices.append(p)
        return devices