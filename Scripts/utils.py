import os
import sys
import json
import plistlib
import shutil
import re
import binascii
import subprocess
import pathlib
import zipfile
import tempfile

class Utils:
    def __init__(self, script_name = "OpCore Simplify"):
        self.script_name = script_name

    def clean_temporary_dir(self):
        temporary_dir = tempfile.gettempdir()
        
        for file in os.listdir(temporary_dir):
            if file.startswith("ocs_"):
    
                if not os.path.isdir(os.path.join(temporary_dir, file)):
                    continue

                try:
                    shutil.rmtree(os.path.join(temporary_dir, file))
                except Exception as e:
                    pass
    
    def get_temporary_dir(self):
        return tempfile.mkdtemp(prefix="ocs_")

    def write_file(self, file_path, data):
        file_extension = os.path.splitext(file_path)[1]

        with open(file_path, "w" if file_extension == ".json" else "wb") as file:
            if file_extension == ".json":
                json.dump(data, file, indent=4)
            else:
                if file_extension == ".plist":
                    data = plistlib.dumps(data)

                file.write(data)

    def read_file(self, file_path):
        if not os.path.exists(file_path):
            return None

        file_extension = os.path.splitext(file_path)[1]

        with open(file_path, "r" if file_extension == ".json" else "rb") as file_handle:
            if file_extension == ".plist":
                data = plistlib.load(file_handle)
            elif file_extension == ".json":
                data = json.load(file_handle)
            else:
                data = file_handle.read()
            return data

    def find_matching_paths(self, root_path, extension_filter=None, name_filter=None, type_filter=None):

        def is_valid_item(name):
            if name.startswith("."):
                return False
            if extension_filter and not name.lower().endswith(extension_filter.lower()):
                return False
            if name_filter and name_filter not in name:
                return False
            return True
        
        found_paths = []

        for root, dirs, files in os.walk(root_path):
            relative_root = root.replace(root_path, "")[1:]

            if type_filter in (None, "dir"):
                for d in dirs:
                    if is_valid_item(d):
                        found_paths.append((os.path.join(relative_root, d), "dir"))

            if type_filter in (None, "file"):
                for file in files:
                    if is_valid_item(file):
                        found_paths.append((os.path.join(relative_root, file), "file"))

        return sorted(found_paths, key=lambda path: path[0])

    def create_folder(self, path, remove_content=False):
        if os.path.exists(path):
            if remove_content:
                shutil.rmtree(path)
                os.makedirs(path)
        else:
            os.makedirs(path)

    def hex_to_bytes(self, string):
        try:
            hex_string = re.sub(r'[^0-9a-fA-F]', '', string)

            if len(re.sub(r"\s+", "", string)) != len(hex_string):
                return string
            
            return binascii.unhexlify(hex_string)
        except binascii.Error:
            return string
    
    def int_to_hex(self, number):
        return format(number, '02X')
    
    def to_little_endian_hex(self, hex_string):
        hex_string = hex_string.lower().lstrip("0x")

        return ''.join(reversed([hex_string[i:i+2] for i in range(0, len(hex_string), 2)])).upper()
    
    def string_to_hex(self, string):
        return ''.join(format(ord(char), '02X') for char in string)
    
    def extract_zip_file(self, zip_path, extraction_directory=None):
        if extraction_directory is None:
            extraction_directory = os.path.splitext(zip_path)[0]
        
        os.makedirs(extraction_directory, exist_ok=True)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extraction_directory)

    def contains_any(self, data, search_item, start=0, end=None):
        return next((item for item in data[start:end] if item.lower() in search_item.lower()), None)

    def normalize_path(self, path):
        path = re.sub(r'^[\'"]+|[\'"]+$', '', path)
        
        path = path.strip()
        
        path = os.path.expanduser(path)
        
        if os.name == 'nt':
            path = path.replace('\\', '/')
            path = re.sub(r'/+', '/', path)
        else:
            path = path.replace('\\', '')
        
        path = os.path.normpath(path)
        
        return str(pathlib.Path(path).resolve())
    
    def parse_darwin_version(self, darwin_version):
        major, minor, patch = map(int, darwin_version.split('.'))
        return major, minor, patch
    
    def open_folder(self, folder_path):
        if os.name == 'posix':
            if 'darwin' in os.uname().sysname.lower():
                subprocess.run(['open', folder_path])
            else:
                subprocess.run(['xdg-open', folder_path])
        elif os.name == 'nt':
            os.startfile(folder_path)

    def request_input(self, prompt="按[Enter]键继续..."):
        if sys.version_info[0] < 3:
            user_response = raw_input(prompt)
        else:
            user_response = input(prompt)
        
        if not isinstance(user_response, str):
            user_response = str(user_response)
        
        return user_response

    def progress_bar(self, title, steps, current_step_index, done=False):
        self.head(title)
        print("")
        if done:
            for step in steps:
                print("  [\033[92m✓\033[0m] {}".format(step))
        else:
            for i, step in enumerate(steps):
                if i < current_step_index:
                    print("  [\033[92m✓\033[0m] {}".format(step))
                elif i == current_step_index:
                    print("  [\033[1;93m>\033[0m] {}...".format(step))
                else:
                    print("  [ ] {}".format(step))
        print("")

    def head(self, text = None, width = 68, resize=True):
        if resize:
            self.adjust_window_size()
        os.system('cls' if os.name=='nt' else 'clear')
        if text == None:
            text = self.script_name
        separator = "═" * (width - 2)
        title = " {} ".format(text)
        if len(title) > width - 2:
            title = title[:width-4] + "..."
        title = self.center_align_with_width(title, (width - 2))
        
        print("╔{}╗\n║{}║\n╚{}╝".format(separator, title, separator))

    def center_align_with_width(self, s1, w1):
        """
        将字符串s1按指定宽度w1居中对齐，中文占2个宽度，英文占1个，空格填充，无法均分则前移一个
        边界处理：原字符串宽度≥w1时，截断并拼接...，最终结果严格匹配w1长度
        
        Args:
            s1: 待处理字符串
            w1: 目标宽度（以英文宽度为1单位）
        
        Returns:
            对齐后的字符串（长度严格匹配w1）
        """
        # 计算单个字符的宽度（中文2，其他1）
        def char_width(char: str) -> int:
            return 2 if '\u4e00' <= char <= '\u9fff' else 1

        # 计算字符串的实际宽度
        def calculate_str_width(s: str) -> int:
            return sum(char_width(c) for c in s)
        
        # 截断字符串并拼接...，确保最终宽度为w1
        def truncate_with_ellipsis(s: str, target_w: int) -> str:
            if target_w <= 3:  # 若目标宽度≤3，直接返回前target_w个字符（无法容纳...）
                return s[:target_w]
            
            # 预留3个宽度给...，计算可截断的最大宽度
            max_content_w = target_w - 3
            current_w = 0
            truncate_idx = 0
            
            # 遍历字符，累计宽度直到接近max_content_w
            for i, c in enumerate(s):
                c_w = char_width(c)
                if current_w + c_w > max_content_w:
                    break
                current_w += c_w
                truncate_idx = i + 1
            
            # 截断并拼接...
            truncated_str = s[:truncate_idx]
            return truncated_str + "..."
        
        # 1. 计算原字符串实际宽度
        str_total_width = calculate_str_width(s1)
        
        # 2. 边界处理：宽度≥w1时截断加...
        if str_total_width >= w1:
            return truncate_with_ellipsis(s1, w1)
        
        # 3. 居中对齐逻辑：计算左右填充空格
        total_space = w1 - str_total_width
        # 无法均分则左侧少1个（前移）
        left_space = total_space // 2 if total_space % 2 == 0 else (total_space - 1) // 2
        right_space = total_space - left_space
        
        # 4. 拼接结果并确保长度严格匹配w1
        result = ' ' * left_space + s1 + ' ' * right_space
        # 兜底校验（理论上不会触发）
        return result[:w1] if len(result) > w1 else result
    
    def adjust_window_size(self, content=""):
        lines = content.splitlines()
        rows = len(lines)
        cols = max(len(line) for line in lines) if lines else 0
        print('\033[8;{};{}t'.format(max(rows+6, 30), max(cols+2, 100)))

    def exit_program(self):
        self.head()
        width = 68
        print("")
        print("获取更多信息、报告错误或为产品做出贡献：".center(width))
        print("")

        separator = "─" * (width - 4)
        print(f" ┌{separator}┐ ")
        
        contacts = {
            "Facebook": "https://www.facebook.com/macforce2601",
            "Telegram": "https://t.me/lzhoang2601",
            "GitHub": "https://github.com/lzhoang2801/OpCore-Simplify"
        }
        
        for platform, link in contacts.items():
            line = f" * {platform}: {link}"
            print(f" │{line.ljust(width - 4)}│ ")

        print(f" └{separator}┘ ")
        print("")
        print("感谢使用我们的脚本！".center(width))
        print("")
        self.request_input("按[Enter]键退出。".center(width))
        sys.exit(0)