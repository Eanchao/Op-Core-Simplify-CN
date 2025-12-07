from Scripts import resource_fetcher
from Scripts import utils
import random
import json

class Github:
    """
    GitHub 交互类，用于获取仓库提交记录、发布版本信息和资产文件等
    """
    def __init__(self):
        """
        初始化 Github 类实例
        """
        self.utils = utils.Utils()
        self.fetcher = resource_fetcher.ResourceFetcher()

    def extract_payload(self, response):
        """
        从 GitHub 响应中提取 JSON 负载数据
        
        参数:
            response (str): GitHub 返回的 HTML 响应内容
            
        返回:
            dict: 解析后的 JSON 负载数据，如果未找到则返回 None
        """
        for line in response.splitlines():
            if "type=\"application/json\"" in line:
                payload = line.split(">", 1)[1].split("<", 1)[0]

                try:
                    payload = json.loads(payload)
                    payload = payload["payload"]
                except:
                    continue

                return payload
        return None
        
    def get_commits(self, owner, repo, branch="main", start_commit=None, after=-1):
        """
        获取 GitHub 仓库的提交记录
        
        参数:
            owner (str): 仓库所有者用户名
            repo (str): 仓库名称
            branch (str): 分支名称，默认为 "main"
            start_commit (str): 起始提交 ID，默认为 None
            after (int): 从起始提交后的第几个提交开始获取，默认为 -1（获取最新提交）
            
        返回:
            dict: 包含提交记录的 JSON 数据
            
        异常:
            ValueError: 当无法获取或解析提交信息时抛出
        """
        if after > -1 and not start_commit:
            start_commit = self.get_commits(owner, repo, branch)["currentCommit"]["oid"]

        if after < 0:
            url = "https://github.com/{}/{}/commits/{}".format(owner, repo, branch)
        else:
            url = "https://github.com/{}/{}/commits/{}?after={}+{}".format(owner, repo, branch, start_commit, after)

        response = self.fetcher.fetch_and_parse_content(url)

        if not response:
            raise ValueError("无法从 GitHub 获取提交信息。")

        payload = self.extract_payload(response)

        if not "commitGroups" in payload:
            raise ValueError("无法找到仓库 {} 在分支 {} 上的提交信息。".format(repo, branch))
        
        return payload

    def get_latest_release(self, owner, repo):
        """
        获取 GitHub 仓库的最新发布版本信息
        
        参数:
            owner (str): 仓库所有者用户名
            repo (str): 仓库名称
            
        返回:
            dict: 包含发布版本信息的字典，包括正文内容和资产文件列表
            
        异常:
            ValueError: 当无法获取或解析发布信息时抛出
        """
        url = "https://github.com/{}/{}/releases".format(owner, repo)
        response = self.fetcher.fetch_and_parse_content(url)

        if not response:
            raise ValueError("无法从 GitHub 获取发布信息。")

        tag_name = self._extract_tag_name(response)
        body = self._extract_body_content(response)

        release_tag_url = "https://github.com/{}/{}/releases/expanded_assets/{}".format(owner, repo, tag_name)
        response = self.fetcher.fetch_and_parse_content(release_tag_url)

        if not response:
            raise ValueError("无法从 GitHub 获取扩展资产信息。")

        assets = self._extract_assets(response)

        return {
            "body": body,
            "assets": assets
        }

    def _extract_tag_name(self, response):
        """
        从 HTML 响应中提取发布标签名
        
        参数:
            response (str): GitHub 返回的 HTML 响应内容
            
        返回:
            str: 发布标签名，如果未找到则返回 None
        """
        for line in response.splitlines():
            if "<a" in line and "href=\"" in line and "/releases/tag/" in line:
                return line.split("/releases/tag/")[1].split("\"")[0]
        return None

    def _extract_body_content(self, response):
        """
        从 HTML 响应中提取发布正文内容
        
        参数:
            response (str): GitHub 返回的 HTML 响应内容
            
        返回:
            str: 发布正文内容，如果未找到则返回空字符串
        """
        for line in response.splitlines():
            if "<div" in line and "body-content" in line:
                return response.split(line.split(">", 1)[0], 1)[1].split("</div>", 1)[0][1:]
        return ""

    def _extract_assets(self, response):
        """
        从 HTML 响应中提取发布资产文件信息
        
        参数:
            response (str): GitHub 返回的 HTML 响应内容
            
        返回:
            list: 包含资产文件信息的字典列表
        """
        assets = []

        in_li_block = False

        for line in response.splitlines():

            if "<li" in line:
                in_li_block = True
                download_link = None
                sha256 = None
                asset_id = None
            elif in_li_block and "</li" in line:
                if download_link and asset_id:
                    assets.append({
                        "product_name": self.extract_asset_name(download_link.split("/")[-1]), 
                        "id": int(asset_id), 
                        "url": "https://github.com" + download_link,
                        "sha256": sha256
                    })
                in_li_block = False

            if in_li_block:  
                if download_link is None and "<a" in line and "href=\"" in line and "/releases/download" in line:
                    download_link = line.split("href=\"")[1].split("\"", 1)[0]

                    # 跳过不符合条件的下载链接
                    if not ("tlwm" in download_link or ("tlwm" not in download_link and "DEBUG" not in download_link.upper())):
                        in_li_block = False
                        continue

                if sha256 is None and "sha256:" in line:
                    sha256 = line.split("sha256:", 1)[1].split("<", 1)[0]

                if asset_id is None and "<relative-time" in line:
                    asset_id = self._generate_asset_id(line)

        return assets

    def _generate_asset_id(self, line):
        """
        根据相对时间标签生成资产 ID
        
        参数:
            line (str): 包含相对时间标签的 HTML 行
            
        返回:
            str: 生成的 9 位数字资产 ID
        """
        try:
            # 从 datetime 属性中提取数字并反转，取前 9 位
            return "".join(char for char in line.split("datetime=\"")[-1].split("\"")[0][::-1] if char.isdigit())[:9]
        except:
            # 如果提取失败，生成随机的 9 位数字
            return "".join(random.choices('0123456789', k=9))

    def extract_asset_name(self, file_name):
        """
        从文件名中提取资产名称
        
        参数:
            file_name (str): 完整的文件名
            
        返回:
            str: 提取的资产名称
        """
        end_idx = len(file_name)
        if "-" in file_name:
            end_idx = min(file_name.index("-"), end_idx)
        if "_" in file_name:
            end_idx = min(file_name.index("_"), end_idx)
        if "." in file_name:
            end_idx = min(file_name.index("."), end_idx)
            # 如果点前面是数字，则将结束索引前移一位
            if file_name[end_idx] == "." and file_name[end_idx - 1].isdigit():
                end_idx = end_idx - 1
        asset_name = file_name[:end_idx]

        # 处理特殊情况的资产名称
        if "Sniffer" in file_name:
            asset_name = file_name.split(".")[0]
        if "unsupported" in file_name:
            asset_name += "-unsupported"
        elif "rtsx" in file_name:
            asset_name += "-rtsx"
        elif "itlwm" in file_name.lower():
            # 根据 macOS 版本添加相应的后缀
            if "Sonoma14.4" in file_name:
                asset_name += "23.4"
            elif "Sonoma14.0" in file_name:
                asset_name += "23.0"
            elif "Ventura" in file_name:
                asset_name += "22"
            elif "Monterey" in file_name:
                asset_name += "21"
            elif "BigSur" in file_name:
                asset_name += "20"
            elif "Catalina" in file_name:
                asset_name += "19"
            elif "Mojave" in file_name:
                asset_name += "18"
            elif "HighSierra" in file_name:
                asset_name += "17"

        return asset_name