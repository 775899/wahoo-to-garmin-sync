import os
import json
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta
from garminconnect import Garmin
import dropbox
from dropbox.files import WriteMode

# 支持的活动文件格式
SUPPORTED_FORMATS = ('.fit', '.gpx', '.tcx')

# ========== 配置 ==========
class Config:
    # Garmin 账号配置（从环境变量/Secrets读取）
    GARMIN_EMAIL = os.getenv('GARMIN_EMAIL')
    GARMIN_PASSWORD = os.getenv('GARMIN_PASSWORD')
    
    # Garmin 区域设置："international" 或 "china"
    GARMIN_REGION = os.getenv('GARMIN_REGION', 'international')
    
    # Dropbox 配置
    DROPBOX_ACCESS_TOKEN = os.getenv('DROPBOX_ACCESS_TOKEN')
    # Wahoo 上传到 Dropbox 的路径
    DROPBOX_FOLDER = os.getenv('DROPBOX_FOLDER', '/Apps/Wahoo Fitness')
    
    # 是否递归搜索子文件夹（Wahoo可能按日期建子目录）
    RECURSIVE_SEARCH = os.getenv('RECURSIVE_SEARCH', 'true').lower() == 'true'
    
    # 同步状态文件
    STATE_FILE = 'sync_state.json'
    
    # 错误重试次数
    MAX_RETRIES = 3
    RETRY_DELAY = 5  # 秒

# ========== 同步状态管理 ==========
class SyncState:
    def __init__(self, filepath=Config.STATE_FILE):
        self.filepath = filepath
        self.state = self.load()
    
    def load(self):
        """加载同步状态"""
        try:
            with open(self.filepath, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                'processed_files': [],
                'last_sync': None,
                'total_synced': 0,
                'failed_files': []
            }
    
    def save(self):
        """保存同步状态"""
        with open(self.filepath, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def is_processed(self, filename):
        """检查文件是否已处理"""
        return filename in self.state['processed_files']
    
    def mark_processed(self, filename):
        """标记文件为已处理"""
        if filename not in self.state['processed_files']:
            self.state['processed_files'].append(filename)
        self.state['last_sync'] = datetime.now().isoformat()
        self.state['total_synced'] += 1
        self.save()
    
    def mark_failed(self, filename, error):
        """标记文件处理失败"""
        self.state['failed_files'].append({
            'filename': filename,
            'error': str(error),
            'timestamp': datetime.now().isoformat()
        })
        self.save()

# ========== Garmin Connect 上传 ==========
class GarminUploader:
    def __init__(self, email, password, region='international'):
        self.email = email
        self.password = password
        self.region = region
        self.client = None
        
    def login(self):
        """登录 Garmin Connect"""
        try:
            self.client = Garmin(self.email, self.password)
            self.client.login()
            print(f"✓ Garmin Connect 登录成功 (区域: {self.region})")
            return True
            
        except Exception as e:
            print(f"✗ Garmin Connect 登录失败: {e}")
            return False
    
    def upload_activity(self, file_data, filename):
        """上传活动文件到 Garmin Connect"""
        if not self.client:
            if not self.login():
                return False
        
        try:
            response = self.client.upload_activity(file_data)
            
            if response:
                print(f"  ✓ 上传成功: {filename}")
                print(f"    活动ID: {response}")
                return True
            else:
                print(f"  ✗ 上传失败: {filename} (无响应)")
                return False
                
        except Exception as e:
            error_str = str(e)
            print(f"  ✗ 上传失败: {filename} - {e}")
            
            # 活动已存在的错误，视为成功
            if 'already' in error_str.lower() or 'duplicate' in error_str.lower():
                print(f"  → 活动已存在于 Garmin Connect，跳过")
                return True
            
            # 登录过期，尝试重新登录
            if 'login' in error_str.lower() or 'auth' in error_str.lower() or '429' in error_str:
                print("  → 尝试重新登录...")
                self.client = None
                time.sleep(3)
                return self.upload_activity(file_data, filename)
            return False

# ========== Dropbox 文件获取 ==========
class DropboxManager:
    def __init__(self, access_token):
        self.access_token = access_token
        self.dbx = None
        
    def connect(self):
        """连接 Dropbox"""
        try:
            self.dbx = dropbox.Dropbox(self.access_token)
            account = self.dbx.users_get_current_account()
            print(f"✓ Dropbox 连接成功: {account.name.display_name}")
            return True
        except Exception as e:
            print(f"✗ Dropbox 连接失败: {e}")
            return False
    
    def list_activity_files(self, folder_path, recursive=True):
        """列出 Dropbox 文件夹中的活动文件（.fit/.gpx/.tcx）"""
        if not self.dbx:
            if not self.connect():
                return []
        
        try:
            activity_files = []
            result = self.dbx.files_list_folder(folder_path, recursive=recursive)
            
            while True:
                for entry in result.entries:
                    if isinstance(entry, dropbox.files.FileMetadata):
                        if entry.name.lower().endswith(SUPPORTED_FORMATS):
                            activity_files.append(entry)
                
                if not result.has_more:
                    break
                result = self.dbx.files_list_folder_continue(result.cursor)
            
            return activity_files
            
        except dropbox.exceptions.ApiError as e:
            if 'not_found' in str(e).lower() or 'path' in str(e).lower():
                print(f"✗ Dropbox 文件夹不存在: {folder_path}")
                print(f"  请确认 Wahoo App 已连接 Dropbox 并上传过活动文件")
                print(f"  请检查 GitHub Secret DROPBOX_FOLDER 的路径是否正确")
            else:
                print(f"✗ 列出文件失败: {e}")
            return []
        except Exception as e:
            print(f"✗ 列出文件失败: {e}")
            return []
    
    def list_all_folders(self, root_path='/'):
        """列出 Dropbox 根目录下的所有文件夹（帮助排查路径问题）"""
        if not self.dbx:
            return []
        
        try:
            result = self.dbx.files_list_folder(root_path)
            folders = [
                entry.path_display 
                for entry in result.entries 
                if isinstance(entry, dropbox.files.FolderMetadata)
            ]
            return folders
        except Exception:
            return []
    
    def download_file(self, file_path):
        """从 Dropbox 下载文件"""
        try:
            _, response = self.dbx.files_download(file_path)
            return response.content
        except Exception as e:
            print(f"✗ 下载文件失败 {file_path}: {e}")
            return None
    
    def move_file(self, from_path, to_folder):
        """移动文件到已处理文件夹"""
        try:
            filename = os.path.basename(from_path)
            to_path = f"{to_folder}/{filename}"
            
            # 如果目标文件已存在，添加时间戳
            try:
                self.dbx.files_get_metadata(to_path)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                name, ext = os.path.splitext(filename)
                to_path = f"{to_folder}/{name}_{timestamp}{ext}"
            except dropbox.exceptions.ApiError:
                pass
            
            # 确保目标文件夹存在
            try:
                self.dbx.files_get_metadata(to_folder)
            except dropbox.exceptions.ApiError:
                self.dbx.files_create_folder_v2(to_folder)
                print(f"  → 创建已处理文件夹: {to_folder}")
            
            self.dbx.files_move_v2(from_path, to_path)
            print(f"  → 文件已移动到: {to_path}")
            return True
            
        except Exception as e:
            print(f"  ✗ 移动文件失败: {e}")
            return False

# ========== 主同步逻辑 ==========
class WahooToGarminSync:
    def __init__(self):
        self.config = Config()
        self.state = SyncState()
        self.garmin = None
        self.dropbox = None
        
    def validate_config(self):
        """验证配置是否完整"""
        required = {
            'GARMIN_EMAIL': self.config.GARMIN_EMAIL,
            'GARMIN_PASSWORD': self.config.GARMIN_PASSWORD,
            'DROPBOX_ACCESS_TOKEN': self.config.DROPBOX_ACCESS_TOKEN,
        }
        
        missing = [k for k, v in required.items() if not v]
        if missing:
            print(f"✗ 配置错误: 缺少必要的Secrets: {', '.join(missing)}")
            return False
            
        return True
    
    def initialize(self):
        """初始化连接"""
        # 初始化 Dropbox（先连Dropbox，因为如果文件夹为空就不需要登录Garmin）
        self.dropbox = DropboxManager(self.config.DROPBOX_ACCESS_TOKEN)
        if not self.dropbox.connect():
            return False
        
        # 初始化 Garmin
        self.garmin = GarminUploader(
            self.config.GARMIN_EMAIL,
            self.config.GARMIN_PASSWORD,
            self.config.GARMIN_REGION
        )
        
        return True
    
    def sync(self):
        """执行同步"""
        if not self.validate_config():
            return False
        
        if not self.initialize():
            return False
        
        print(f"\n{'='*50}")
        print(f"开始同步: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Dropbox 路径: {self.config.DROPBOX_FOLDER}")
        print(f"支持格式: {', '.join(SUPPORTED_FORMATS)}")
        print(f"递归搜索: {'是' if self.config.RECURSIVE_SEARCH else '否'}")
        print(f"{'='*50}\n")
        
        # 获取 Dropbox 中的活动文件
        activity_files = self.dropbox.list_activity_files(
            self.config.DROPBOX_FOLDER, 
            recursive=self.config.RECURSIVE_SEARCH
        )
        
        if not activity_files:
            print("ℹ 没有找到新的活动文件")
            print("\n排查信息:")
            
            # 列出根目录下的文件夹，帮助排查路径问题
            root_folders = self.dropbox.list_all_folders('/')
            if root_folders:
                print("  Dropbox 根目录下的文件夹:")
                for folder in root_folders:
                    print(f"    {folder}")
            else:
                print("  Dropbox 根目录下没有文件夹")
            
            # 尝试列出配置路径的子文件夹
            sub_folders = self.dropbox.list_all_folders(self.config.DROPBOX_FOLDER)
            if sub_folders:
                print(f"\n  {self.config.DROPBOX_FOLDER} 下的子文件夹:")
                for folder in sub_folders:
                    print(f"    {folder}")
            
            self.print_summary()
            return True
        
        print(f"发现 {len(activity_files)} 个活动文件\n")
        
        # 懒登录 Garmin（有文件才登录，避免空跑时触发限流）
        if not self.garmin.login():
            return False
        
        # 处理每个文件
        success_count = 0
        skip_count = 0
        failed_count = 0
        
        for file_entry in activity_files:
            filename = file_entry.name
            file_path = file_entry.path_display
            
            print(f"处理: {filename}")
            
            # 检查是否已处理
            if self.state.is_processed(filename):
                print(f"  → 跳过: 已同步过")
                skip_count += 1
                continue
            
            # 下载文件
            file_data = self.dropbox.download_file(file_path)
            if not file_data:
                failed_count += 1
                self.state.mark_failed(filename, "下载失败")
                continue
            
            # 上传到 Garmin
            if self.garmin.upload_activity(file_data, filename):
                self.state.mark_processed(filename)
                success_count += 1
                
                # 移动文件到已处理文件夹
                processed_folder = f"{self.config.DROPBOX_FOLDER}/processed"
                self.dropbox.move_file(file_path, processed_folder)
            else:
                failed_count += 1
                self.state.mark_failed(filename, "上传失败")
            
            # 避免请求过快
            time.sleep(2)
        
        self.print_summary(success_count, skip_count, failed_count)
        return True
    
    def print_summary(self, success=0, skip=0, failed=0):
        """打印同步摘要"""
        print(f"\n{'='*50}")
        print("同步摘要")
        print(f"{'='*50}")
        print(f"成功: {success}")
        print(f"跳过: {skip}")
        print(f"失败: {failed}")
        print(f"总计已同步: {self.state.state['total_synced']}")
        print(f"最后同步: {self.state.state['last_sync']}")
        
        if self.state.state['failed_files']:
            print(f"\n最近失败记录:")
            for fail in self.state.state['failed_files'][-5:]:
                print(f"  - {fail['filename']}: {fail['error']}")
        
        print(f"{'='*50}\n")

# ========== 主入口 ==========
def main():
    """主函数"""
    try:
        sync = WahooToGarminSync()
        success = sync.sync()
        
        if not success:
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n\n用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ 未预期的错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
