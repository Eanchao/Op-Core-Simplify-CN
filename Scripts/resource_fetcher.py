# 资源获取器模块
# 用于从网络获取和解析各种资源内容

from Scripts import integrity_checker
from Scripts import utils
import ssl
import os
import json
import plistlib
import socket
import sys
import gzip
import zlib
import time

# 根据Python版本选择合适的urllib模块
if sys.version_info >= (3, 0):
    from urllib.request import urlopen, Request
    from urllib.error import URLError
else:
    import urllib2
    from urllib2 import urlopen, Request, URLError

MAX_ATTEMPTS = 3  # 最大尝试次数

class ResourceFetcher:
    """资源获取器类
    
    用于从网络获取资源，支持：
    - HTTP请求发送
    - 内容解析（JSON、plist等）
    - 文件下载（带进度显示）
    - 完整性校验（SHA256）
    """
    
    def __init__(self, headers=None):
        """初始化资源获取器
        
        参数:
            headers: 自定义HTTP请求头
        """
        # 请求头设置，默认使用Chrome浏览器的User-Agent
        self.request_headers = headers or {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        }
        self.buffer_size = 16 * 1024  # 缓冲区大小（16KB）
        self.ssl_context = self.create_ssl_context()  # 创建SSL上下文
        self.integrity_checker = integrity_checker.IntegrityChecker()  # 完整性检查器实例
        self.utils = utils.Utils()  # 工具类实例

    def create_ssl_context(self):
        """创建SSL上下文
        
        尝试创建安全的SSL上下文，如果失败则创建不验证的上下文
        
        返回:
            ssl.SSLContext: SSL上下文对象
        """
        try:
            # 获取默认的CA证书文件路径
            cafile = ssl.get_default_verify_paths().openssl_cafile
            if not os.path.exists(cafile):
                import certifi
                cafile = certifi.where()  # 使用certifi库的CA证书
            ssl_context = ssl.create_default_context(cafile=cafile)
        except Exception as e:
            print("创建SSL上下文失败: {}".format(e))
            # 创建不验证的SSL上下文（不安全，仅在必要时使用）
            ssl_context = ssl._create_unverified_context()
        return ssl_context

    def _make_request(self, resource_url, timeout=10):
        """发送HTTP请求
        
        参数:
            resource_url: 资源URL
            timeout: 超时时间（秒）
            
        返回:
            http.client.HTTPResponse: HTTP响应对象，失败则返回None
        """
        try:
            headers = dict(self.request_headers)
            headers["Accept-Encoding"] = "gzip, deflate"  # 支持压缩
            
            # 发送请求并返回响应
            return urlopen(Request(resource_url, headers=headers), timeout=timeout, context=self.ssl_context)
        except socket.timeout as e:
            print("超时错误: {}".format(e))
        except ssl.SSLError as e:
            print("SSL错误: {}".format(e))
        except (URLError, socket.gaierror) as e:
            print("连接错误: {}".format(e))
        except Exception as e:
            print("请求失败: {}".format(e))

        return None

    def fetch_and_parse_content(self, resource_url, content_type=None):
        """获取并解析内容
        
        参数:
            resource_url: 资源URL
            content_type: 内容类型（json、plist或None）
            
        返回:
            解析后的内容（字典、列表或字符串），失败则返回None
        """
        attempt = 0
        response = None

        # 尝试多次获取资源
        while attempt < 3:
            response = self._make_request(resource_url)

            if not response:
                attempt += 1
                print("从{}获取内容失败，正在重试...".format(resource_url))
                continue

            if response.getcode() == 200:  # 状态码200表示成功
                break

            attempt += 1

        if not response:
            print("从{}获取内容失败".format(resource_url))
            return None
        
        content = response.read()  # 读取响应内容

        # 处理压缩内容
        if response.info().get("Content-Encoding") == "gzip" or content.startswith(b"\x1f\x8b"):
            try:
                content = gzip.decompress(content)
            except Exception as e:
                print("解压缩gzip内容失败: {}".format(e))
        elif response.info().get("Content-Encoding") == "deflate":
            try:
                content = zlib.decompress(content)
            except Exception as e:
                print("解压缩deflate内容失败: {}".format(e))
        
        # 解析内容
        try:
            if content_type == "json":
                return json.loads(content)
            elif content_type == "plist":
                return plistlib.loads(content)
            else:
                return content.decode("utf-8")
        except Exception as e:
            print("解析{}内容失败: {}".format(content_type, e))
            
        return None

    def _download_with_progress(self, response, local_file):
        """带进度显示的下载功能
        
        参数:
            response: HTTP响应对象
            local_file: 本地文件对象
        """
        total_size = response.getheader("Content-Length")  # 获取文件总大小
        if total_size:
            total_size = int(total_size)
        bytes_downloaded = 0
        start_time = time.time()
        last_time = start_time
        last_bytes = 0
        speeds = []  # 用于计算平均下载速度

        speed_str = "-- KB/s"
        
        while True:
            chunk = response.read(self.buffer_size)  # 读取数据块
            if not chunk:
                break
            local_file.write(chunk)  # 写入本地文件
            bytes_downloaded += len(chunk)  # 更新已下载字节数
            
            current_time = time.time()
            time_diff = current_time - last_time  # 计算时间差
            
            if time_diff > 0.5:  # 每0.5秒更新一次速度
                current_speed = (bytes_downloaded - last_bytes) / time_diff
                speeds.append(current_speed)
                if len(speeds) > 5:  # 保留最近5个速度样本
                    speeds.pop(0)
                avg_speed = sum(speeds) / len(speeds)  # 计算平均速度
                
                # 格式化速度字符串
                if avg_speed < 1024*1024:
                    speed_str = "{:.1f} KB/s".format(avg_speed/1024)
                else:
                    speed_str = "{:.1f} MB/s".format(avg_speed/(1024*1024))
                
                last_time = current_time
                last_bytes = bytes_downloaded
            
            # 显示进度条
            if total_size:
                percent = int(bytes_downloaded / total_size * 100)
                bar_length = 40
                filled = int(bar_length * bytes_downloaded / total_size)
                bar = "█" * filled + "░" * (bar_length - filled)  # 进度条
                progress = "{} [{}] {:3d}% {:.1f}/{:.1f}MB".format(
                    speed_str, bar, percent, 
                    bytes_downloaded/(1024*1024), 
                    total_size/(1024*1024)
                )
            else:
                progress = "已下载：{} {:.1f}MB".format(speed_str, bytes_downloaded/(1024*1024))
            
            # 清除当前行并打印新进度
            print(" " * 80, end="\r")
            print(progress, end="\r")
            
        print()  # 下载完成后换行

    def download_and_save_file(self, resource_url, destination_path, sha256_hash=None):
        """下载文件并保存
        
        参数:
            resource_url: 资源URL
            destination_path: 本地保存路径
            sha256_hash: 可选的SHA256校验和
            
        返回:
            bool: 下载成功返回True，失败返回False
        """
        attempt = 0

        while attempt < MAX_ATTEMPTS:
            attempt += 1
            response = self._make_request(resource_url)

            if not response:
                print("从{}获取内容失败，正在重试...".format(resource_url))
                continue

            # 下载文件
            with open(destination_path, "wb") as local_file:
                self._download_with_progress(response, local_file)

            # 检查文件是否存在且大小大于0
            if os.path.exists(destination_path) and os.path.getsize(destination_path) > 0:
                if sha256_hash:
                    print("正在验证SHA256校验和...")
                    downloaded_hash = self.integrity_checker.get_sha256(destination_path)
                    if downloaded_hash.lower() == sha256_hash.lower():
                        print("校验和验证成功。")
                        return True
                    else:
                        print("校验和不匹配！正在删除文件并重新下载...")
                        os.remove(destination_path)
                        continue
                else:
                    print("未提供SHA256校验和，下载文件未验证。")
                    return True
            
            # 删除损坏的文件
            if os.path.exists(destination_path):
                os.remove(destination_path)

            if attempt < MAX_ATTEMPTS:
                print("{}下载失败，正在重试...".format(resource_url))

        print("尝试{}次后，下载{}失败。".format(MAX_ATTEMPTS, resource_url))
        return False
